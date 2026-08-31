from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .errors import SourceIncompleteError
from .jobs import JobStore
from .matching import build_search_queries, choose_match
from .models import (
    MatchResult,
    MigrationPlan,
    MissingSourceTrack,
    SourcePlaylist,
    SpotifyTrack,
)
from .spotify import SpotifyClient


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    completed: int
    total: int
    result: MatchResult
    resumed: bool


class MigrationService:
    def __init__(self, spotify: SpotifyClient) -> None:
        self.spotify = spotify

    def build_plan(
        self,
        source: SourcePlaylist,
        *,
        threshold: float = 0.82,
        ambiguity_gap: float = 0.05,
        allow_incomplete_source: bool = False,
        store: JobStore | None = None,
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> MigrationPlan:
        if source.missing_source_ids and not allow_incomplete_source:
            details = source.missing_tracks or tuple(
                MissingSourceTrack(item) for item in source.missing_source_ids
            )
            rows = "\n".join(
                f"- 歌曲：{item.title or '未知'}；歌手："
                f"{', '.join(item.artists) or '未知'}；发布时间："
                f"{item.release_date or '未知'}；ID：{item.source_id}"
                for item in details
            )
            raise SourceIncompleteError(
                f"{len(source.missing_source_ids)} 首源歌曲缺少详情：\n{rows}\n"
                "已停止迁移：源歌单不完整时继续可能造成漏歌、错序或错误匹配。"
            )
        plan_id = (
            store.bind(source, threshold=threshold, ambiguity_gap=ambiguity_gap)
            if store
            else None
        )
        plan = MigrationPlan(
            source=source,
            threshold=threshold,
            ambiguity_gap=ambiguity_gap,
            **({"plan_id": plan_id} if plan_id else {}),
        )
        total = len(source.tracks)
        for completed, track in enumerate(source.tracks, start=1):
            if track.source_id in source.missing_source_ids:
                result = MatchResult(
                    track, "not_found", "网易云未返回歌曲详情；用户已允许跳过"
                )
                plan.results.append(result)
                if progress:
                    progress(ProgressEvent(completed, total, result, False))
                continue
            existing = store.get_result(track.position, track.source_id) if store else None
            if existing is not None:
                plan.results.append(existing)
                if progress:
                    progress(ProgressEvent(completed, total, existing, True))
                continue

            candidates: list[SpotifyTrack] = []
            queries_made = 0
            cache_hits = 0
            queries = build_search_queries(track)
            for index, query in enumerate(queries):
                cached = store.get_query(query) if store else None
                if cached is not None:
                    found = cached
                    cache_hits += 1
                else:
                    found = self.spotify.search_tracks(query, limit=10)
                    queries_made += 1
                    if store:
                        store.save_query(query, found)
                candidates.extend(found)

                interim = choose_match(
                    track,
                    candidates,
                    threshold=threshold,
                    ambiguity_gap=ambiguity_gap,
                    queries_made=queries_made,
                    cache_hits=cache_hits,
                )
                # Exact field-filtered search already returns up to ten candidates. A strong,
                # unambiguous result needs no broader query; uncertain items use every fallback.
                if index == 0 and interim.status == "matched":
                    break

            result = choose_match(
                track,
                candidates,
                threshold=threshold,
                ambiguity_gap=ambiguity_gap,
                queries_made=queries_made,
                cache_hits=cache_hits,
            )
            if store:
                store.save_result(result)
            plan.results.append(result)
            if progress:
                progress(ProgressEvent(completed, total, result, False))
        return plan
