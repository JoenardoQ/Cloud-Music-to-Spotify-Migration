from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

from .errors import InputError, RemoteApiError
from .models import MissingSourceTrack, SourcePlaylist, SourceTrack


NETEASE_BASE_URL = "https://music.163.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}


def parse_playlist_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return value
    try:
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        candidate = query.get("id", [""])[0]
    except ValueError as exc:
        raise InputError(f"无效的网易云歌单地址：{value}") from exc
    if not candidate and "playlist" in value:
        match = re.search(r"(?:id=|playlist/)(\d+)", value)
        candidate = match.group(1) if match else ""
    if not candidate.isdigit():
        raise InputError("请输入网易云歌单数字 ID，或包含 id=数字 的歌单 URL")
    return candidate


class NetEaseClient:
    """Read-only adapter for NetEase web or api-enhanced endpoints."""

    def __init__(
        self,
        *,
        base_url: str = NETEASE_BASE_URL,
        enhanced_api: bool = False,
        timeout: float = 20.0,
        request_json: Callable[[Request, float], dict[str, Any]] | None = None,
        detail_batch_size: int = 200,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        open_url: Callable[..., Any] = urlopen,
    ) -> None:
        if detail_batch_size <= 0:
            raise ValueError("detail_batch_size 必须大于 0")
        parsed_base_url = urlparse(base_url)
        if enhanced_api and (
            parsed_base_url.scheme not in {"http", "https"}
            or not parsed_base_url.netloc
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise InputError(
                "--netease-api-base-url 必须是完整的 HTTP(S) 地址，例如 "
                "http://127.0.0.1:3000"
            )
        self.base_url = base_url.rstrip("/")
        self.enhanced_api = enhanced_api
        self.timeout = timeout
        self.request_json = request_json or self._request_json
        self.detail_batch_size = detail_batch_size
        self.max_retries = max_retries
        self.sleep = sleep
        self.open_url = open_url

    def _request_json(self, request: Request, timeout: float) -> dict[str, Any]:
        for attempt in range(self.max_retries + 1):
            try:
                with self.open_url(request, timeout=timeout) as response:
                    value = json.load(response)
                    if not isinstance(value, dict):
                        raise RemoteApiError("网易云接口响应不是 JSON 对象")
                    return value
            except HTTPError as exc:
                if (exc.code == 429 or 500 <= exc.code < 600) and attempt < self.max_retries:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    try:
                        delay = max(0.0, float(retry_after)) if retry_after else min(2**attempt, 8)
                    except ValueError:
                        delay = min(2**attempt, 8)
                    self.sleep(delay)
                    continue
                raise RemoteApiError(f"网易云接口返回 HTTP {exc.code}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt < self.max_retries:
                    self.sleep(min(2**attempt, 8))
                    continue
                raise RemoteApiError(f"无法读取网易云接口：{exc}") from exc
        raise RemoteApiError("网易云接口重试次数耗尽")

    def _playlist_detail(self, playlist_id: str) -> dict[str, Any]:
        path = "/playlist/detail" if self.enhanced_api else "/api/v6/playlist/detail"
        url = f"{self.base_url}{path}?{urlencode({'id': playlist_id})}"
        return self.request_json(Request(url, headers=_HEADERS), self.timeout)

    def _song_detail(self, ids: list[str]) -> dict[str, Any]:
        if self.enhanced_api:
            query = urlencode({"ids": ",".join(ids)})
            request = Request(f"{self.base_url}/song/detail?{query}", headers=_HEADERS)
            return self.request_json(request, self.timeout)
        payload = urlencode({"c": json.dumps([{"id": int(item)} for item in ids])}).encode()
        request = Request(
            f"{self.base_url}/api/v3/song/detail",
            data=payload,
            headers={**_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self.request_json(request, self.timeout)

    def fetch_playlist(
        self, playlist_ref: str, *, expected_count: int | None = None
    ) -> SourcePlaylist:
        playlist_id = parse_playlist_id(playlist_ref)
        payload = self._playlist_detail(playlist_id)
        playlist = payload.get("playlist")
        if not isinstance(playlist, dict) or not isinstance(playlist.get("trackIds"), list):
            raise RemoteApiError("网易云歌单响应缺少 playlist.trackIds，接口可能已变化")

        if not all(isinstance(item, dict) and "id" in item for item in playlist["trackIds"]):
            raise RemoteApiError("网易云 trackIds 包含无法识别的条目")
        track_ids = [str(item["id"]) for item in playlist["trackIds"]]
        try:
            declared_count = int(playlist.get("trackCount", len(track_ids)))
        except (TypeError, ValueError) as exc:
            raise RemoteApiError("网易云 trackCount 不是有效整数") from exc
        if declared_count != len(track_ids):
            raise RemoteApiError(
                f"网易云声明 {declared_count} 首，但 trackIds 只有 {len(track_ids)} 首；已中止"
            )
        if expected_count is not None and expected_count != len(track_ids):
            raise RemoteApiError(
                f"网页预期 {expected_count} 首，但接口返回 {len(track_ids)} 首；已中止"
            )

        by_id: dict[str, dict[str, Any]] = {}
        for start in range(0, len(track_ids), self.detail_batch_size):
            response = self._song_detail(track_ids[start : start + self.detail_batch_size])
            songs = response.get("songs")
            if not isinstance(songs, list):
                raise RemoteApiError("网易云歌曲详情响应缺少 songs，接口可能已变化")
            for song in songs:
                if isinstance(song, dict) and "id" in song:
                    by_id[str(song["id"])] = song

        missing = tuple(item for item in track_ids if item not in by_id)
        playlist_tracks = playlist.get("tracks")
        summary_by_id = (
            {
                str(item["id"]): item
                for item in playlist_tracks
                if isinstance(item, dict) and "id" in item
            }
            if isinstance(playlist_tracks, list)
            else {}
        )
        missing_tracks = tuple(
            _missing_track(track_id, summary_by_id.get(track_id)) for track_id in missing
        )
        missing_by_id = {item.source_id: item for item in missing_tracks}
        tracks: list[SourceTrack] = []
        for position, track_id in enumerate(track_ids, start=1):
            song = by_id.get(track_id)
            if song is None:
                diagnostic = missing_by_id[track_id]
                tracks.append(
                    SourceTrack(
                        position=position,
                        source_id=track_id,
                        title=diagnostic.title or f"未知歌曲 {track_id}",
                        artists=diagnostic.artists,
                        album="",
                        release_year=(
                            int(diagnostic.release_date[:4])
                            if diagnostic.release_date
                            else None
                        ),
                    )
                )
                continue
            raw_artists = song.get("ar") or []
            if not isinstance(raw_artists, list):
                raise RemoteApiError(f"网易云歌曲 {track_id} 的 ar 字段类型异常")
            artists = tuple(
                str(artist.get("name", "")).strip()
                for artist in raw_artists
                if isinstance(artist, dict) and artist.get("name")
            )
            album = song.get("al") or {}
            if not isinstance(album, dict):
                raise RemoteApiError(f"网易云歌曲 {track_id} 的 al 字段类型异常")
            tracks.append(
                SourceTrack(
                    position=position,
                    source_id=track_id,
                    title=str(song.get("name", "")).strip(),
                    artists=artists,
                    album=str(album.get("name", "")).strip(),
                    duration_ms=int(song["dt"]) if song.get("dt") is not None else None,
                    aliases=tuple(str(alias) for alias in song.get("alia", []) if alias),
                    release_year=_release_year(song.get("publishTime")),
                )
            )

        return SourcePlaylist(
            source_id=playlist_id,
            name=str(playlist.get("name") or f"NetEase playlist {playlist_id}"),
            description=str(playlist.get("description") or ""),
            cover_url=playlist.get("coverImgUrl"),
            declared_count=declared_count,
            tracks=tuple(tracks),
            missing_source_ids=missing,
            missing_tracks=missing_tracks,
        )


def _release_year(value: object) -> int | None:
    try:
        year = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).year
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    current_year = datetime.now(timezone.utc).year
    return year if 1900 <= year <= current_year + 1 else None


def _missing_track(source_id: str, song: dict[str, Any] | None) -> MissingSourceTrack:
    if not song:
        return MissingSourceTrack(source_id)
    raw_artists = song.get("ar")
    artists = tuple(
        str(artist.get("name", "")).strip()
        for artist in raw_artists
        if isinstance(artist, dict) and artist.get("name")
    ) if isinstance(raw_artists, list) else ()
    release_date = None
    try:
        release_date = datetime.fromtimestamp(
            int(song.get("publishTime")) / 1000, tz=timezone.utc
        ).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    return MissingSourceTrack(
        source_id=source_id,
        title=str(song.get("name") or "").strip() or None,
        artists=artists,
        release_date=release_date,
    )
