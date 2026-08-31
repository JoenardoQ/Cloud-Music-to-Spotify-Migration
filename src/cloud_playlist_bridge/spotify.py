from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .errors import AuthenticationError, QuotaExceededError, RemoteApiError
from .models import SpotifyTrack


SPOTIFY_API_URL = "https://api.spotify.com/v1"
SPOTIFY_ACCOUNTS_URL = "https://accounts.spotify.com"
SCOPES = "playlist-modify-public playlist-modify-private playlist-read-private"


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
        except OSError as exc:
            raise AuthenticationError(f"无法读取 Spotify token 文件 {self.path}：{exc}") from exc

    def save(self, token: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            temporary.replace(self.path)
        except OSError as exc:
            raise AuthenticationError(f"无法保存 Spotify token 文件 {self.path}：{exc}") from exc


class SpotifyPKCEAuth:
    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        token_store: TokenStore,
        *,
        timeout: float = 180.0,
        browser_open: Callable[[str], bool] = webbrowser.open,
        open_url: Callable[..., Any] = urlopen,
    ) -> None:
        if not client_id.strip():
            raise AuthenticationError("缺少 Spotify Client ID")
        parsed = urlparse(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
            raise AuthenticationError("本地回调必须使用 http://127.0.0.1:端口/... 或 IPv6 ::1")
        if parsed.port is None:
            raise AuthenticationError("Spotify Redirect URI 必须包含显式端口")
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.token_store = token_store
        self.timeout = timeout
        self.browser_open = browser_open
        self.open_url = open_url

    def _post_form(self, url: str, values: dict[str, str]) -> dict[str, Any]:
        request = Request(
            url,
            data=urlencode(values).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.open_url(request, timeout=20) as response:
                value = json.load(response)
                if not isinstance(value, dict):
                    raise AuthenticationError("Spotify 令牌响应不是 JSON 对象")
                return value
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode()).get("error_description", "")
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = ""
            raise AuthenticationError(f"Spotify 令牌请求失败：HTTP {exc.code} {detail}".strip()) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AuthenticationError(f"Spotify 令牌请求失败：{exc}") from exc

    def _with_expiry(
        self, payload: dict[str, Any], previous: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        token = dict(payload)
        token["expires_at"] = time.time() + int(token.get("expires_in", 3600)) - 30
        token["client_id"] = self.client_id
        if "refresh_token" not in token and previous and previous.get("refresh_token"):
            token["refresh_token"] = previous["refresh_token"]
        if "scope" not in token and previous and previous.get("scope"):
            token["scope"] = previous["scope"]
        return token

    def _refresh(self, token: dict[str, Any]) -> dict[str, Any]:
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            return self._authorize()
        response = self._post_form(
            f"{SPOTIFY_ACCOUNTS_URL}/api/token",
            {
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": str(refresh_token),
            },
        )
        refreshed = self._with_expiry(response, token)
        self.token_store.save(refreshed)
        return refreshed

    def _authorize(self) -> dict[str, Any]:
        verifier = secrets.token_urlsafe(72)[:96]
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        state = secrets.token_urlsafe(24)
        authorization_url = f"{SPOTIFY_ACCOUNTS_URL}/authorize?" + urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": SCOPES,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "state": state,
            }
        )

        parsed = urlparse(self.redirect_uri)
        result: dict[str, str] = {}
        callback_path = parsed.path or "/"

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
                incoming = urlparse(self.path)
                if incoming.path != callback_path:
                    self.send_response(404)
                    self.end_headers()
                    return
                values = parse_qs(incoming.query)
                for key in ("code", "state", "error"):
                    if values.get(key):
                        result[key] = values[key][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write("Spotify authorization received. You can close this tab.".encode())

            def log_message(self, _format: str, *_args: object) -> None:
                return

        try:
            server = HTTPServer((parsed.hostname or "127.0.0.1", parsed.port), CallbackHandler)
        except OSError as exc:
            raise AuthenticationError(f"无法监听 Spotify 回调端口 {parsed.port}：{exc}") from exc
        server.timeout = self.timeout
        print(f"请在浏览器完成 Spotify 授权：\n{authorization_url}")
        self.browser_open(authorization_url)
        try:
            server.handle_request()
        finally:
            server.server_close()
        if result.get("error"):
            raise AuthenticationError(f"Spotify 用户授权失败：{result['error']}")
        if result.get("state") != state or not result.get("code"):
            raise AuthenticationError("Spotify 回调超时、缺少 code，或 state 校验失败")

        response = self._post_form(
            f"{SPOTIFY_ACCOUNTS_URL}/api/token",
            {
                "client_id": self.client_id,
                "grant_type": "authorization_code",
                "code": result["code"],
                "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
            },
        )
        token = self._with_expiry(response)
        self.token_store.save(token)
        return token

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        token = self.token_store.load()
        if token and token.get("client_id") != self.client_id:
            token = None
        granted_scopes = set(str(token.get("scope") or "").split()) if token else set()
        if token and not set(SCOPES.split()).issubset(granted_scopes):
            token = None
        try:
            expired = bool(token) and float(token.get("expires_at", 0)) <= time.time()
        except (TypeError, ValueError):
            expired = True
        if token and (force_refresh or expired):
            token = self._refresh(token)
        if not token:
            token = self._authorize()
        access_token = token.get("access_token")
        if not access_token:
            raise AuthenticationError("Spotify 令牌响应缺少 access_token")
        return str(access_token)


class SpotifyClient:
    def __init__(
        self,
        auth: SpotifyPKCEAuth,
        *,
        api_url: str = SPOTIFY_API_URL,
        timeout: float = 20.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        open_url: Callable[..., Any] = urlopen,
    ) -> None:
        self.auth = auth
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep
        self.open_url = open_url

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str | int] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.api_url}{path}"
        if query:
            url += "?" + urlencode(query)
        refreshed = False
        for attempt in range(self.max_retries + 1):
            request = Request(
                url,
                data=json.dumps(body).encode() if body is not None else None,
                headers={
                    "Authorization": (
                        f"Bearer {self.auth.get_access_token(force_refresh=refreshed)}"
                    ),
                    "Content-Type": "application/json",
                },
                method=method,
            )
            refreshed = False
            try:
                with self.open_url(request, timeout=self.timeout) as response:
                    data = response.read()
                    value = json.loads(data) if data else {}
                    if not isinstance(value, dict):
                        raise RemoteApiError("Spotify API 响应不是 JSON 对象")
                    return value
            except HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    refreshed = True
                    continue
                try:
                    raw_detail = exc.read().decode("utf-8", errors="replace")
                except OSError:
                    raw_detail = ""
                if exc.code == 429:
                    try:
                        error_payload = json.loads(raw_detail)
                    except json.JSONDecodeError:
                        error_payload = {}
                    reason = ""
                    if isinstance(error_payload, dict):
                        nested_error = error_payload.get("error")
                        reason = str(
                            error_payload.get("reason")
                            or (
                                nested_error.get("reason")
                                if isinstance(nested_error, dict)
                                else ""
                            )
                            or ""
                        )
                    retry_after = _retry_after_seconds(exc.headers.get("Retry-After"))
                    if reason == "QUOTA_EXCEEDED":
                        raise QuotaExceededError(
                            "Spotify 开发模式配额已耗尽；规划进度已保存，请稍后重试",
                            retry_after=retry_after,
                        ) from exc
                    if attempt < self.max_retries:
                        self.sleep(retry_after if retry_after is not None else min(2**attempt, 8))
                        continue
                if 500 <= exc.code < 600:
                    if attempt < self.max_retries:
                        self.sleep(min(2**attempt, 8))
                        continue
                raise RemoteApiError(f"Spotify API HTTP {exc.code}: {raw_detail[:500]}") from exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt < self.max_retries:
                    self.sleep(min(2**attempt, 8))
                    continue
                raise RemoteApiError(f"Spotify API 请求失败：{exc}") from exc
        raise RemoteApiError("Spotify API 重试次数耗尽")

    def search_tracks(self, query: str, *, limit: int = 10) -> list[SpotifyTrack]:
        payload = self._request(
            "GET", "/search", query={"q": query, "type": "track", "limit": limit}
        )
        tracks_payload = payload.get("tracks")
        if not isinstance(tracks_payload, dict) or not isinstance(
            tracks_payload.get("items"), list
        ):
            raise RemoteApiError("Spotify 搜索响应缺少 tracks.items")
        items = tracks_payload["items"]
        result: list[SpotifyTrack] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("uri"):
                continue
            raw_artists = item.get("artists") or []
            if not isinstance(raw_artists, list):
                raise RemoteApiError("Spotify 搜索歌曲的 artists 字段类型异常")
            album = item.get("album") or {}
            if not isinstance(album, dict):
                album = {}
            release_date = str(album.get("release_date") or "")
            release_year = int(release_date[:4]) if release_date[:4].isdigit() else None
            external_urls = item.get("external_urls") or {}
            if not isinstance(external_urls, dict):
                external_urls = {}
            try:
                duration_ms = (
                    int(item["duration_ms"]) if item.get("duration_ms") is not None else None
                )
            except (TypeError, ValueError) as exc:
                raise RemoteApiError("Spotify 搜索歌曲的 duration_ms 类型异常") from exc
            result.append(
                SpotifyTrack(
                    uri=str(item["uri"]),
                    title=str(item.get("name") or ""),
                    artists=tuple(
                        str(artist.get("name") or "")
                        for artist in raw_artists
                        if isinstance(artist, dict) and artist.get("name")
                    ),
                    album=str(album.get("name") or ""),
                    duration_ms=duration_ms,
                    external_url=external_urls.get("spotify"),
                    release_year=release_year,
                )
            )
        return result

    def create_playlist(self, name: str, *, public: bool, description: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/me/playlists",
            body={"name": name, "public": public, "description": description[:300]},
        )

    def find_playlists_by_marker(self, marker: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self._request(
                "GET", "/me/playlists", query={"limit": 50, "offset": offset}
            )
            items = payload.get("items")
            if not isinstance(items, list):
                raise RemoteApiError("Spotify 用户歌单响应缺少 items")
            for item in items:
                if isinstance(item, dict) and (
                    marker in str(item.get("description") or "")
                    or marker in str(item.get("name") or "")
                ):
                    matches.append(item)
            if len(items) < 50:
                break
            offset += len(items)
        return matches

    def update_playlist(self, playlist_id: str, *, name: str, description: str) -> None:
        self._request(
            "PUT",
            f"/playlists/{playlist_id}",
            body={"name": name, "description": description[:300]},
        )

    def add_playlist_items(self, playlist_id: str, uris: list[str]) -> str:
        if len(uris) > 100:
            raise ValueError("Spotify 每批最多允许 100 个项目")
        response = self._request("POST", f"/playlists/{playlist_id}/items", body={"uris": uris})
        snapshot_id = response.get("snapshot_id")
        if not snapshot_id:
            raise RemoteApiError("Spotify 写入响应缺少 snapshot_id")
        return str(snapshot_id)

    def get_playlist_item_uris(self, playlist_id: str, *, offset: int, count: int) -> list[str]:
        result: list[str] = []
        while len(result) < count:
            limit = min(50, count - len(result))
            payload = self._request(
                "GET",
                f"/playlists/{playlist_id}/items",
                query={"offset": offset + len(result), "limit": limit},
            )
            items = payload.get("items")
            if not isinstance(items, list):
                raise RemoteApiError("Spotify 歌单响应缺少 items")
            for wrapper in items:
                if not isinstance(wrapper, dict):
                    continue
                item = wrapper.get("item") or wrapper.get("track") or wrapper
                if isinstance(item, dict) and item.get("uri"):
                    result.append(str(item["uri"]))
            if len(items) < limit:
                break
        return result


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None
