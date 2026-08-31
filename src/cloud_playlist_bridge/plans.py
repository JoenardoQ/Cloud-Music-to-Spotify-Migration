from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from .errors import InputError, RemoteApiError
from .models import (
    CandidateAssessment,
    MatchResult,
    MatchStatus,
    MigrationPlan,
    SourcePlaylist,
    SourceTrack,
    SpotifyTrack,
)


PLAN_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PlanFiles:
    plan: Path
    report: Path
    manual: Path


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_track_to_dict(track: SourceTrack) -> dict[str, Any]:
    return asdict(track)


def source_track_from_dict(value: dict[str, Any]) -> SourceTrack:
    return SourceTrack(
        position=int(value["position"]),
        source_id=str(value["source_id"]),
        title=str(value["title"]),
        artists=tuple(str(item) for item in value.get("artists", [])),
        album=str(value.get("album", "")),
        duration_ms=(int(value["duration_ms"]) if value.get("duration_ms") is not None else None),
        aliases=tuple(str(item) for item in value.get("aliases", [])),
        release_year=(
            int(value["release_year"]) if value.get("release_year") is not None else None
        ),
    )


def spotify_track_to_dict(track: SpotifyTrack) -> dict[str, Any]:
    return asdict(track)


def spotify_track_from_dict(value: dict[str, Any]) -> SpotifyTrack:
    uri = str(value["uri"])
    if not uri.startswith("spotify:track:"):
        raise ValueError(f"计划包含非 track URI：{uri}")
    return SpotifyTrack(
        uri=uri,
        title=str(value.get("title", "")),
        artists=tuple(str(item) for item in value.get("artists", [])),
        album=str(value.get("album", "")),
        duration_ms=(int(value["duration_ms"]) if value.get("duration_ms") is not None else None),
        external_url=(str(value["external_url"]) if value.get("external_url") else None),
        release_year=(
            int(value["release_year"]) if value.get("release_year") is not None else None
        ),
    )


def match_result_to_dict(result: MatchResult) -> dict[str, Any]:
    return {
        "source": source_track_to_dict(result.source),
        "status": result.status,
        "reason": result.reason,
        "queries_made": result.queries_made,
        "cache_hits": result.cache_hits,
        "assessments": [
            {
                "track": spotify_track_to_dict(item.track),
                "score": item.score,
                "title_score": item.title_score,
                "artist_score": item.artist_score,
                "duration_score": item.duration_score,
                "album_score": item.album_score,
                "version_penalty": item.version_penalty,
                "year_delta": item.year_delta,
            }
            for item in result.assessments
        ],
    }


def match_result_from_dict(value: dict[str, Any]) -> MatchResult:
    status = str(value["status"])
    if status not in {"matched", "not_found", "low_confidence", "ambiguous"}:
        raise ValueError(f"未知匹配状态：{status}")
    assessments = tuple(
        CandidateAssessment(
            track=spotify_track_from_dict(item["track"]),
            score=float(item["score"]),
            title_score=float(item["title_score"]),
            artist_score=float(item["artist_score"]),
            duration_score=float(item["duration_score"]),
            album_score=float(item["album_score"]),
            version_penalty=float(item["version_penalty"]),
            year_delta=(int(item["year_delta"]) if item.get("year_delta") is not None else None),
        )
        for item in value.get("assessments", [])
    )
    return MatchResult(
        source=source_track_from_dict(value["source"]),
        status=cast(MatchStatus, status),
        reason=str(value.get("reason", "")),
        assessments=assessments,
        queries_made=int(value.get("queries_made", 0)),
        cache_hits=int(value.get("cache_hits", 0)),
    )


def source_playlist_to_dict(source: SourcePlaylist) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "name": source.name,
        "description": source.description,
        "cover_url": source.cover_url,
        "declared_count": source.declared_count,
        "tracks": [source_track_to_dict(track) for track in source.tracks],
        "missing_source_ids": list(source.missing_source_ids),
    }


def source_playlist_from_dict(value: dict[str, Any]) -> SourcePlaylist:
    return SourcePlaylist(
        source_id=str(value["source_id"]),
        name=str(value["name"]),
        description=str(value.get("description", "")),
        cover_url=(str(value["cover_url"]) if value.get("cover_url") else None),
        declared_count=int(value["declared_count"]),
        tracks=tuple(source_track_from_dict(item) for item in value.get("tracks", [])),
        missing_source_ids=tuple(str(item) for item in value.get("missing_source_ids", [])),
    )


def source_fingerprint(source: SourcePlaylist) -> str:
    return hashlib.sha256(_canonical_json(source_playlist_to_dict(source)).encode()).hexdigest()


def matching_source_fingerprint(source: SourcePlaylist) -> str:
    value = {
        "source_id": source.source_id,
        "declared_count": source.declared_count,
        "tracks": [source_track_to_dict(track) for track in source.tracks],
        "missing_source_ids": list(source.missing_source_ids),
    }
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def plan_payload(plan: MigrationPlan) -> dict[str, Any]:
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan.plan_id,
        "created_at": plan.created_at,
        "source": source_playlist_to_dict(plan.source),
        "source_fingerprint": source_fingerprint(plan.source),
        "policy": {
            "threshold": plan.threshold,
            "ambiguity_gap": plan.ambiguity_gap,
            "ambiguous_action": "skip_and_report",
        },
        "summary": {
            "source_count": len(plan.source.tracks),
            "matched_count": len(plan.matched),
            "manual_count": len(plan.unmatched),
        },
        "results": [match_result_to_dict(item) for item in plan.results],
    }


def plan_document(plan: MigrationPlan) -> dict[str, Any]:
    payload = plan_payload(plan)
    return {
        **payload,
        "integrity_sha256": hashlib.sha256(_canonical_json(payload).encode()).hexdigest(),
    }


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding=encoding)
    temporary.replace(path)


def load_plan(path: Path) -> tuple[MigrationPlan, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("根节点不是对象")
        checksum = str(document.pop("integrity_sha256"))
        actual = hashlib.sha256(_canonical_json(document).encode()).hexdigest()
        if not hmac.compare_digest(checksum, actual):
            raise ValueError("SHA-256 完整性校验失败，计划可能已被修改")
        if document.get("schema_version") != PLAN_SCHEMA_VERSION:
            raise ValueError(f"不支持的计划 schema：{document.get('schema_version')}")
        source = source_playlist_from_dict(document["source"])
        if document.get("source_fingerprint") != source_fingerprint(source):
            raise ValueError("源歌单摘要与计划内容不一致")
        policy = document["policy"]
        threshold = float(policy["threshold"])
        ambiguity_gap = float(policy["ambiguity_gap"])
        if not 0 <= threshold <= 1 or not 0 <= ambiguity_gap <= 1:
            raise ValueError("计划匹配阈值超出 0 到 1")
        if policy.get("ambiguous_action") != "skip_and_report":
            raise ValueError("计划不满足歧义歌曲必须跳过并报告的策略")
        results = [match_result_from_dict(item) for item in document.get("results", [])]
        if len(results) != len(source.tracks):
            raise ValueError("计划结果数量与源歌曲数量不一致")
        for expected_track, result in zip(source.tracks, results):
            if result.source != expected_track:
                raise ValueError(f"计划位置 {expected_track.position} 的源歌曲副本不一致")
            if result.status == "matched" and result.candidate is None:
                raise ValueError(f"计划位置 {expected_track.position} 已匹配但缺少 Spotify URI")
        summary = document.get("summary") or {}
        matched_count = sum(item.status == "matched" for item in results)
        if (
            summary.get("source_count") != len(source.tracks)
            or summary.get("matched_count") != matched_count
            or summary.get("manual_count") != len(results) - matched_count
        ):
            raise ValueError("计划 summary 与结果不一致")
        plan = MigrationPlan(
            source=source,
            results=results,
            threshold=threshold,
            ambiguity_gap=ambiguity_gap,
            plan_id=str(document["plan_id"]),
            created_at=str(document["created_at"]),
        )
        return plan, checksum
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InputError(f"无法加载计划 {path}：{exc}") from exc
def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned[:60] or "playlist"


def _candidate_columns(result: MatchResult, rank: int) -> dict[str, Any]:
    if len(result.assessments) < rank:
        return {
            f"candidate_{rank}_title": "",
            f"candidate_{rank}_artists": "",
            f"candidate_{rank}_score": "",
            f"candidate_{rank}_year": "",
            f"candidate_{rank}_url": "",
        }
    item = result.assessments[rank - 1]
    return {
        f"candidate_{rank}_title": item.track.title,
        f"candidate_{rank}_artists": " / ".join(item.track.artists),
        f"candidate_{rank}_score": item.score,
        f"candidate_{rank}_year": item.track.release_year or "",
        f"candidate_{rank}_url": item.track.external_url or item.track.uri,
    }


def _report_row(result: MatchResult) -> dict[str, Any]:
    best = result.assessments[0] if result.assessments else None
    row: dict[str, Any] = {
        "position": result.source.position,
        "source_id": result.source.source_id,
        "source_url": f"https://music.163.com/song?id={result.source.source_id}",
        "source_title": result.source.title,
        "source_artists": " / ".join(result.source.artists),
        "source_album": result.source.album,
        "duration_ms": result.source.duration_ms,
        "source_year": result.source.release_year,
        "status": result.status,
        "reason": result.reason,
        "score": result.score,
        "title_score": best.title_score if best else "",
        "artist_score": best.artist_score if best else "",
        "duration_score": best.duration_score if best else "",
        "album_score": best.album_score if best else "",
        "version_penalty": best.version_penalty if best else "",
        "year_delta": best.year_delta if best else "",
        "queries_made": result.queries_made,
        "cache_hits": result.cache_hits,
    }
    for rank in range(1, 4):
        row.update(_candidate_columns(result, rank))
    return row


_REPORT_FIELDS = [
    "position", "source_id", "source_url", "source_title", "source_artists", "source_album",
    "duration_ms", "source_year", "status", "reason", "score", "title_score", "artist_score",
    "duration_score", "album_score", "version_penalty", "year_delta", "queries_made", "cache_hits",
] + [
    f"candidate_{rank}_{field}"
    for rank in range(1, 4)
    for field in ("title", "artists", "score", "year", "url")
]


def _atomic_write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_plan_bundle(plan: MigrationPlan, directory: Path) -> PlanFiles:
    stem = f"{_safe_name(plan.source.name)}-{plan.source.source_id}-{plan.plan_id[:12]}"
    plan_path = directory / f"{stem}.plan.json"
    report_path = directory / f"{stem}.csv"
    manual_path = directory / f"{stem}.manual.csv"
    try:
        _atomic_write_text(
            plan_path,
            json.dumps(plan_document(plan), ensure_ascii=False, indent=2),
        )
        rows = [_report_row(item) for item in plan.results]
        _atomic_write_csv(report_path, rows)
        _atomic_write_csv(
            manual_path,
            [row for item, row in zip(plan.results, rows) if item.status != "matched"],
        )
    except OSError as exc:
        raise RemoteApiError(f"无法写入计划或报告到 {directory}：{exc}") from exc
    return PlanFiles(plan_path, report_path, manual_path)
