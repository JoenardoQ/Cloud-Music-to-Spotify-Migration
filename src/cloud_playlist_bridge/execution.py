from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import (
    InputError,
    PartialMigrationError,
    RemoteApiError,
    UncertainMigrationError,
)
from .models import CommitResult, MigrationPlan
from .spotify import SpotifyClient


EXECUTION_SCHEMA_VERSION = 1


@dataclass(slots=True)
class ExecutionJournal:
    plan_checksum: str
    plan_id: str
    public: bool
    status: str = "creating"
    playlist_id: str = ""
    playlist_url: str = ""
    completed_count: int = 0
    snapshot_id: str = ""
    inflight_start: int | None = None
    inflight_uris: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EXECUTION_SCHEMA_VERSION,
            "plan_checksum": self.plan_checksum,
            "plan_id": self.plan_id,
            "public": self.public,
            "status": self.status,
            "playlist_id": self.playlist_id,
            "playlist_url": self.playlist_url,
            "completed_count": self.completed_count,
            "snapshot_id": self.snapshot_id,
            "inflight_start": self.inflight_start,
            "inflight_uris": self.inflight_uris,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExecutionJournal:
        if value.get("schema_version") != EXECUTION_SCHEMA_VERSION:
            raise ValueError(f"不支持的执行日志 schema：{value.get('schema_version')}")
        return cls(
            plan_checksum=str(value["plan_checksum"]),
            plan_id=str(value["plan_id"]),
            public=bool(value["public"]),
            status=str(value.get("status", "creating")),
            playlist_id=str(value.get("playlist_id", "")),
            playlist_url=str(value.get("playlist_url", "")),
            completed_count=int(value.get("completed_count", 0)),
            snapshot_id=str(value.get("snapshot_id", "")),
            inflight_start=(
                int(value["inflight_start"]) if value.get("inflight_start") is not None else None
            ),
            inflight_uris=(
                [str(item) for item in value["inflight_uris"]]
                if value.get("inflight_uris") is not None
                else None
            ),
        )


class ExecutionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ExecutionJournal | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("根节点不是对象")
            return ExecutionJournal.from_dict(value)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise InputError(f"无法读取执行日志 {self.path}：{exc}") from exc

    def save(self, journal: ExecutionJournal) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(journal.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError as exc:
            raise RemoteApiError(f"无法保存执行日志 {self.path}：{exc}") from exc


class PlanExecutor:
    def __init__(self, spotify: SpotifyClient) -> None:
        self.spotify = spotify

    @staticmethod
    def journal_path(plan_path: Path) -> Path:
        return plan_path.with_name(plan_path.name + ".execution.json")

    def _ensure_playlist(
        self,
        plan: MigrationPlan,
        journal: ExecutionJournal,
        store: ExecutionStore,
    ) -> None:
        if journal.playlist_id:
            return
        marker = f"[CPB:{plan.plan_id[:12]}]"
        if journal.status == "uncertain_create":
            matches = self.spotify.find_playlists_by_marker(marker)
            if len(matches) > 1:
                raise UncertainMigrationError(
                    f"发现 {len(matches)} 个包含计划标记的歌单，无法安全选择；请手动保留一个"
                )
            if not matches:
                raise UncertainMigrationError(
                    "上次创建请求结果不确定，暂未找到带计划标记的歌单；"
                    "请稍后再次 apply，避免重复创建"
                )
            created = matches[0]
        else:
            source_url = f"https://music.163.com/playlist?id={plan.source.source_id}"
            description = (
                f"{marker} Migrated from NetEase Cloud Music ({source_url}). "
                f"Matched {len(plan.matched)}/{len(plan.results)} tracks."
            )
            store.save(journal)
            try:
                created = self.spotify.create_playlist(
                    f"{plan.source.name[:80]} {marker}",
                    public=journal.public,
                    description=description,
                )
            except Exception as exc:
                journal.status = "uncertain_create"
                store.save(journal)
                raise UncertainMigrationError(
                    f"Spotify 创建请求结果不确定：{exc}；执行日志已保存"
                ) from exc

        playlist_id = str(created.get("id") or "")
        if not playlist_id:
            journal.status = "uncertain_create"
            store.save(journal)
            raise RemoteApiError("Spotify 创建或恢复的歌单缺少 id")
        journal.playlist_id = playlist_id
        external_urls = created.get("external_urls") or {}
        if not isinstance(external_urls, dict):
            external_urls = {}
        journal.playlist_url = str(
            external_urls.get("spotify") or f"https://open.spotify.com/playlist/{playlist_id}"
        )
        journal.status = "applying"
        store.save(journal)

    def _reconcile_inflight(
        self, journal: ExecutionJournal, store: ExecutionStore
    ) -> None:
        if journal.inflight_start is None or journal.inflight_uris is None:
            return
        expected = journal.inflight_uris
        remote = self.spotify.get_playlist_item_uris(
            journal.playlist_id,
            offset=journal.inflight_start,
            count=len(expected) + 1,
        )
        if remote == expected:
            journal.completed_count = journal.inflight_start + len(expected)
            journal.inflight_start = None
            journal.inflight_uris = None
            journal.status = "applying"
            store.save(journal)
            return
        if remote == expected[: len(remote)]:
            remaining = expected[len(remote) :]
            if remaining:
                snapshot = self.spotify.add_playlist_items(journal.playlist_id, remaining)
                journal.snapshot_id = snapshot
            journal.completed_count = journal.inflight_start + len(expected)
            journal.inflight_start = None
            journal.inflight_uris = None
            journal.status = "applying"
            store.save(journal)
            return
        journal.status = "uncertain"
        store.save(journal)
        raise UncertainMigrationError(
            "Spotify 远端歌曲与执行日志不一致，已停止以避免重复或错序；"
            f"请检查 {journal.playlist_url}"
        )

    def apply(
        self,
        plan: MigrationPlan,
        *,
        plan_path: Path,
        plan_checksum: str,
        public: bool,
        progress: Callable[[int, int], None] | None = None,
    ) -> CommitResult:
        uris = [item.candidate.uri for item in plan.matched if item.candidate]
        if not uris:
            raise RemoteApiError("计划中没有可自动写入的高置信度匹配")
        store = ExecutionStore(self.journal_path(plan_path))
        journal = store.load()
        if journal is None:
            journal = ExecutionJournal(plan_checksum, plan.plan_id, public)
        if journal.plan_checksum != plan_checksum or journal.plan_id != plan.plan_id:
            raise InputError("执行日志不属于当前计划或计划内容已变化")
        if journal.public != public:
            raise InputError("恢复执行时公开/私有设置必须与首次 apply 一致")
        if journal.completed_count > len(uris):
            raise InputError("执行日志完成数量超过当前计划歌曲数")
        if journal.status == "completed":
            if progress:
                progress(journal.completed_count, len(uris))
            return CommitResult(journal.playlist_id, journal.playlist_url, journal.completed_count)

        self._ensure_playlist(plan, journal, store)
        self._reconcile_inflight(journal, store)
        if progress:
            progress(journal.completed_count, len(uris))

        if journal.completed_count and self.spotify.get_playlist_item_uris(
            journal.playlist_id, offset=journal.completed_count, count=1
        ):
            journal.status = "uncertain"
            store.save(journal)
            raise UncertainMigrationError(
                "Spotify 歌单在已确认批次之后存在计划外歌曲；已停止以避免破坏顺序"
            )

        for start in range(journal.completed_count, len(uris), 100):
            batch = uris[start : start + 100]
            journal.inflight_start = start
            journal.inflight_uris = list(batch)
            journal.status = "applying"
            store.save(journal)
            try:
                journal.snapshot_id = self.spotify.add_playlist_items(journal.playlist_id, batch)
            except Exception as exc:
                journal.status = "partial"
                store.save(journal)
                raise PartialMigrationError(
                    f"已写入 {journal.completed_count}/{len(uris)} 首；再次 apply 将协调并恢复：{exc}",
                    playlist_url=journal.playlist_url,
                    added_count=journal.completed_count,
                ) from exc
            journal.completed_count = start + len(batch)
            journal.inflight_start = None
            journal.inflight_uris = None
            store.save(journal)
            if progress:
                progress(journal.completed_count, len(uris))

        journal.status = "finalizing"
        store.save(journal)
        source_url = f"https://music.163.com/playlist?id={plan.source.source_id}"
        self.spotify.update_playlist(
            journal.playlist_id,
            name=plan.source.name,
            description=(
                f"Migrated from NetEase Cloud Music ({source_url}). "
                f"Matched {len(plan.matched)}/{len(plan.results)} tracks."
            ),
        )
        journal.status = "completed"
        store.save(journal)
        return CommitResult(journal.playlist_id, journal.playlist_url, journal.completed_count)
