from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .errors import BridgeError, InputError
from .execution import PlanExecutor
from .jobs import JobStore
from .migration import MigrationService, ProgressEvent
from .models import MatchResult, MigrationPlan, SourcePlaylist
from .netease import NetEaseClient, parse_playlist_id
from .plans import PlanFiles, load_plan, write_plan_bundle
from .spotify import SpotifyClient, SpotifyPKCEAuth, TokenStore


MAX_REQUEST_BYTES = 64 * 1024
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"


def _track_dict(track: Any) -> dict[str, Any]:
    return {
        "position": track.position,
        "title": track.title,
        "artists": " / ".join(track.artists),
        "album": track.album,
    }


def _result_dict(result: MatchResult) -> dict[str, Any]:
    candidate = result.candidate
    return {
        "position": result.source.position,
        "status": result.status,
        "reason": result.reason,
        "score": round(result.score, 4),
        "title": candidate.title if candidate else "未写入 Spotify",
        "artists": " / ".join(candidate.artists) if candidate else "",
        "album": candidate.album if candidate else "",
        "url": candidate.external_url if candidate else None,
    }


def _slice_index(query: dict[str, list[str]], name: str) -> int:
    try:
        return max(0, int(query.get(name, ["0"])[0]))
    except (TypeError, ValueError):
        return 0


class AppController:
    def __init__(self, state_dir: Path, report_dir: Path) -> None:
        self.state_dir = state_dir
        self.report_dir = report_dir
        self.csrf_token = secrets.token_urlsafe(32)
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._generation = 0
        self._phase = "idle"
        self._message = "等待输入歌单"
        self._progress_completed = 0
        self._progress_total = 0
        self._source: SourcePlaylist | None = None
        self._results: list[dict[str, Any]] = []
        self._logs: list[str] = []
        self._plan: MigrationPlan | None = None
        self._plan_files: PlanFiles | None = None
        self._plan_checksum = ""
        self._spotify: SpotifyClient | None = None
        self._public = True
        self._playlist_url = ""

    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self._lock:
            self._logs.append(f"[{stamp}] {message}")

    def _set_error(self, exc: Exception) -> None:
        message = str(exc) or exc.__class__.__name__
        with self._lock:
            self._phase = "error"
            self._message = message
        self._log(f"错误：{message}")

    def _is_busy(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def _start_worker(self, target: Any) -> None:
        self._worker = threading.Thread(target=target, daemon=True)
        self._worker.start()

    def start_plan(self, payload: dict[str, Any]) -> None:
        playlist = str(payload.get("playlist") or "").strip()
        client_id = str(payload.get("spotify_client_id") or "").strip()
        api_base_url = str(payload.get("netease_api_base_url") or "").strip()
        allow_incomplete_source = bool(payload.get("allow_incomplete_source"))
        if not playlist:
            raise InputError("请输入网易云歌单 ID 或分享 URL")
        if not client_id:
            raise InputError("请输入 Spotify Client ID")
        playlist_id = parse_playlist_id(playlist)
        try:
            expected_raw = payload.get("expected_count")
            expected_count = int(expected_raw) if expected_raw not in (None, "") else None
            threshold = float(payload.get("threshold", 0.82))
            ambiguity_gap = float(payload.get("ambiguity_gap", 0.05))
        except (TypeError, ValueError) as exc:
            raise InputError("数量和匹配阈值必须是有效数字") from exc
        if expected_count is not None and expected_count < 0:
            raise InputError("预期歌曲数不能为负数")
        if not 0 <= threshold <= 1 or not 0 <= ambiguity_gap <= 1:
            raise InputError("匹配阈值必须在 0 到 1 之间")

        with self._lock:
            if self._is_busy():
                raise InputError("已有任务正在运行")
            self._generation += 1
            self._phase = "loading"
            self._message = "正在读取网易云歌单"
            self._progress_completed = 0
            self._progress_total = 0
            self._source = None
            self._results = []
            self._logs = []
            self._plan = None
            self._plan_files = None
            self._plan_checksum = ""
            self._spotify = None
            self._public = not bool(payload.get("private"))
            self._playlist_url = ""

        def work() -> None:
            try:
                self._log("开始读取网易云歌单")
                netease = (
                    NetEaseClient(base_url=api_base_url, enhanced_api=True)
                    if api_base_url
                    else NetEaseClient()
                )
                source = netease.fetch_playlist(playlist, expected_count=expected_count)
                with self._lock:
                    self._source = source
                    self._phase = "matching"
                    self._message = "正在匹配 Spotify 曲库"
                    self._progress_total = len(source.tracks)
                self._log(f"已读取《{source.name}》，共 {len(source.tracks)} 首")

                auth = SpotifyPKCEAuth(
                    client_id,
                    DEFAULT_REDIRECT_URI,
                    TokenStore(self.state_dir / "spotify-token.json"),
                )
                spotify = SpotifyClient(auth)
                job_path = self.state_dir / "jobs" / f"netease-{playlist_id}.sqlite3"

                def progress(event: ProgressEvent) -> None:
                    with self._lock:
                        self._progress_completed = event.completed
                        self._results.append(_result_dict(event.result))
                    action = "恢复" if event.resumed else "匹配"
                    self._log(
                        f"{action} {event.completed}/{event.total}："
                        f"{event.result.source.title} → {event.result.status}"
                    )

                with JobStore(job_path) as store:
                    plan = MigrationService(spotify).build_plan(
                        source,
                        threshold=threshold,
                        ambiguity_gap=ambiguity_gap,
                        allow_incomplete_source=allow_incomplete_source,
                        store=store,
                        progress=progress,
                    )
                plan_files = write_plan_bundle(plan, self.report_dir)
                loaded_plan, checksum = load_plan(plan_files.plan)
                with self._lock:
                    self._plan = loaded_plan
                    self._plan_files = plan_files
                    self._plan_checksum = checksum
                    self._spotify = spotify
                    self._phase = "ready"
                    self._message = "分析完成，等待确认写入"
                self._log(
                    f"分析完成：匹配 {len(plan.matched)} 首，"
                    f"跳过 {len(plan.unmatched)} 首"
                )
            except Exception as exc:
                self._set_error(exc)

        self._start_worker(work)

    def start_apply(self) -> None:
        with self._lock:
            if self._is_busy():
                raise InputError("已有任务正在运行")
            if not self._plan or not self._plan_files or not self._spotify:
                raise InputError("请先完成歌单分析")
            plan = self._plan
            plan_files = self._plan_files
            spotify = self._spotify
            checksum = self._plan_checksum
            public = self._public
            self._phase = "applying"
            self._message = "正在写入 Spotify 歌单"
            self._progress_completed = 0
            self._progress_total = len(plan.matched)

        def work() -> None:
            try:
                self._log("用户已确认，开始创建或恢复 Spotify 歌单")

                def progress(completed: int, total: int) -> None:
                    with self._lock:
                        self._progress_completed = completed
                        self._progress_total = total
                    self._log(f"Spotify 写入进度：{completed}/{total}")

                result = PlanExecutor(spotify).apply(
                    plan,
                    plan_path=plan_files.plan,
                    plan_checksum=checksum,
                    public=public,
                    progress=progress,
                )
                with self._lock:
                    self._phase = "completed"
                    self._message = "迁移完成"
                    self._playlist_url = result.playlist_url
                self._log(f"迁移完成：已写入 {result.added_count} 首")
            except Exception as exc:
                self._set_error(exc)

        self._start_worker(work)

    def snapshot(self, query: dict[str, list[str]]) -> dict[str, Any]:
        with self._lock:
            client_generation = _slice_index(query, "generation")
            generation_matches = client_generation == self._generation
            source_after = _slice_index(query, "source_after") if generation_matches else 0
            result_after = _slice_index(query, "result_after") if generation_matches else 0
            log_after = _slice_index(query, "log_after") if generation_matches else 0
            source_tracks = self._source.tracks if self._source else ()
            source_summary = (
                {
                    "name": self._source.name,
                    "count": len(self._source.tracks),
                    "cover_url": self._source.cover_url,
                }
                if self._source
                else None
            )
            matched = sum(item["status"] == "matched" for item in self._results)
            return {
                "csrf_token": self.csrf_token,
                "generation": self._generation,
                "phase": self._phase,
                "message": self._message,
                "busy": self._is_busy(),
                "can_apply": bool(self._plan and self._plan_files and self._spotify),
                "progress": {
                    "completed": self._progress_completed,
                    "total": self._progress_total,
                },
                "summary": {
                    "matched": matched,
                    "skipped": len(self._results) - matched,
                },
                "source": source_summary,
                "source_tracks": [_track_dict(item) for item in source_tracks[source_after:]],
                "source_count": len(source_tracks),
                "results": self._results[result_after:],
                "result_count": len(self._results),
                "logs": self._logs[log_after:],
                "log_count": len(self._logs),
                "manual_available": bool(self._plan_files),
                "playlist_url": self._playlist_url,
            }

    def manual_report(self) -> tuple[str, bytes] | None:
        with self._lock:
            path = self._plan_files.manual if self._plan_files else None
        if not path or not path.is_file():
            return None
        return path.name, path.read_bytes()


def _loopback_host(host: str) -> bool:
    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return bool(addresses) and all(
        ipaddress.ip_address(item[4][0]).is_loopback for item in addresses
    )


def _valid_host_header(value: str) -> bool:
    try:
        hostname = urlparse(f"//{value}").hostname
    except ValueError:
        return False
    if not hostname:
        return False
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return hostname.lower() == "localhost"


def _handler(controller: AppController) -> type[BaseHTTPRequestHandler]:
    class AppHandler(BaseHTTPRequestHandler):
        server_version = "CloudPlaylistBridge/0.4"

        def _headers(self, status: int, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; connect-src 'self'; img-src 'self' https: data:; "
                "style-src 'self'; script-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self._headers(status, content_type, len(body))
            self.wfile.write(body)

        def _json(self, status: int, value: dict[str, Any]) -> None:
            self._send(
                status,
                "application/json; charset=utf-8",
                json.dumps(value, ensure_ascii=False).encode("utf-8"),
            )

        def do_GET(self) -> None:  # noqa: N802
            if not _valid_host_header(self.headers.get("Host", "")):
                self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Host 不允许"})
                return
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                self._json(HTTPStatus.OK, controller.snapshot(parse_qs(parsed.query)))
                return
            if parsed.path == "/api/manual":
                report = controller.manual_report()
                if not report:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "手动报告尚未生成"})
                    return
                name, body = report
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", 'attachment; filename="manual.csv"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.css": ("app.css", "text/css; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            }
            asset = assets.get(parsed.path)
            if not asset:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            name, content_type = asset
            body = files("cloud_playlist_bridge").joinpath("web", name).read_bytes()
            self._send(HTTPStatus.OK, content_type, body)

        def do_POST(self) -> None:  # noqa: N802
            if not _valid_host_header(self.headers.get("Host", "")):
                self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Host 不允许"})
                return
            if not secrets.compare_digest(
                self.headers.get("X-CSRF-Token", ""), controller.csrf_token
            ):
                self._json(HTTPStatus.FORBIDDEN, {"error": "CSRF token 无效"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "请求过大"})
                return
            try:
                value = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(value, dict):
                    raise ValueError("请求必须是 JSON 对象")
                if self.path == "/api/plan":
                    controller.start_plan(value)
                elif self.path == "/api/apply":
                    controller.start_apply()
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                    return
                self._json(HTTPStatus.ACCEPTED, {"ok": True})
            except (BridgeError, ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                print(f"App 请求处理失败：{exc}", file=sys.stderr)
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "本地服务内部错误"})

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return AppHandler


def run_local_app(
    *,
    host: str,
    port: int,
    open_browser: bool,
    state_dir: Path,
    report_dir: Path,
) -> int:
    if not _loopback_host(host):
        raise InputError("App 仅允许监听回环地址，例如 127.0.0.1")
    if not 1 <= port <= 65535:
        raise InputError("--port 必须在 1 到 65535 之间")
    controller = AppController(state_dir, report_dir)
    try:
        server = ThreadingHTTPServer((host, port), _handler(controller))
    except OSError as exc:
        raise InputError(f"无法监听 http://{host}:{port}：{exc}") from exc
    url = f"http://{host}:{port}/"
    print(f"Cloud Playlist Bridge App：{url}")
    print("按 Ctrl+C 停止。")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nApp 已停止。")
    finally:
        server.server_close()
    return 0
