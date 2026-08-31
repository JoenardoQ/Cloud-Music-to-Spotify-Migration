from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .errors import JobMismatchError
from .models import MatchResult, SourcePlaylist, SpotifyTrack
from .plans import (
    match_result_from_dict,
    match_result_to_dict,
    matching_source_fingerprint,
    spotify_track_from_dict,
    spotify_track_to_dict,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    position INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS query_cache (
    query TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""
JOB_SCHEMA_VERSION = "1"


class JobStore:
    """SQLite-backed planning checkpoint and per-job Spotify search cache."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path)
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.executescript(_SCHEMA)
        except (OSError, sqlite3.Error) as exc:
            raise JobMismatchError(f"无法打开任务数据库 {path}：{exc}") from exc

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> JobStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def bind(self, source: SourcePlaylist, *, threshold: float, ambiguity_gap: float) -> str:
        expected = {
            "job_schema_version": JOB_SCHEMA_VERSION,
            "source_fingerprint": matching_source_fingerprint(source),
            "threshold": repr(threshold),
            "ambiguity_gap": repr(ambiguity_gap),
        }
        with self.connection:
            for key, value in expected.items():
                existing = self._get_meta(key)
                if existing is not None and existing != value:
                    raise JobMismatchError(
                        f"任务文件 {self.path} 的 {key} 与当前歌单或策略不一致；"
                        "请指定新的 --job-file"
                    )
                self._set_meta(key, value)
            plan_id = self._get_meta("plan_id") or uuid4().hex
            self._set_meta("plan_id", plan_id)
        return plan_id

    def get_result(self, position: int, source_id: str) -> MatchResult | None:
        try:
            row = self.connection.execute(
                "SELECT source_id, payload FROM results WHERE position = ?", (position,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise JobMismatchError(f"无法读取任务数据库 {self.path}：{exc}") from exc
        if row is None:
            return None
        if str(row[0]) != source_id:
            raise JobMismatchError(
                f"任务位置 {position} 的源歌曲 ID 已变化；请使用新的任务文件"
            )
        try:
            return match_result_from_dict(json.loads(row[1]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise JobMismatchError(f"任务位置 {position} 的数据已损坏：{exc}") from exc

    def save_result(self, result: MatchResult) -> None:
        payload = json.dumps(
            match_result_to_dict(result), ensure_ascii=False, separators=(",", ":")
        )
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO results(position, source_id, payload) VALUES(?, ?, ?) "
                    "ON CONFLICT(position) DO UPDATE SET source_id = excluded.source_id, "
                    "payload = excluded.payload",
                    (result.source.position, result.source.source_id, payload),
                )
        except sqlite3.Error as exc:
            raise JobMismatchError(f"无法保存任务进度 {self.path}：{exc}") from exc

    def get_query(self, query: str) -> list[SpotifyTrack] | None:
        try:
            row = self.connection.execute(
                "SELECT payload FROM query_cache WHERE query = ?", (query,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise JobMismatchError(f"无法读取任务查询缓存 {self.path}：{exc}") from exc
        if row is None:
            return None
        try:
            values = json.loads(row[0])
            return [spotify_track_from_dict(item) for item in values]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise JobMismatchError(f"任务查询缓存已损坏：{exc}") from exc

    def save_query(self, query: str, tracks: list[SpotifyTrack]) -> None:
        payload = json.dumps(
            [spotify_track_to_dict(item) for item in tracks],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO query_cache(query, payload) VALUES(?, ?) "
                    "ON CONFLICT(query) DO UPDATE SET payload = excluded.payload",
                    (query, payload),
                )
        except sqlite3.Error as exc:
            raise JobMismatchError(f"无法保存任务查询缓存 {self.path}：{exc}") from exc

    @property
    def completed_count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM results").fetchone()
        return int(row[0]) if row else 0
