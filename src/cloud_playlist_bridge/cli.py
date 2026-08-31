from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .errors import BridgeError, InputError, PartialMigrationError, QuotaExceededError
from .execution import PlanExecutor
from .jobs import JobStore
from .migration import MigrationService, ProgressEvent
from .netease import NetEaseClient, parse_playlist_id
from .plans import load_plan, write_plan_bundle
from .spotify import SpotifyClient, SpotifyPKCEAuth, TokenStore


def _probability(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是数字") from exc
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("必须在 0 到 1 之间")
    return parsed


def _add_spotify_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--spotify-client-id",
        default=os.environ.get("SPOTIFY_CLIENT_ID"),
        help="Spotify Developer Client ID（也可用 SPOTIFY_CLIENT_ID）",
    )
    parser.add_argument(
        "--redirect-uri",
        default="http://127.0.0.1:8888/callback",
        help="必须已登记在 Spotify 应用中的 loopback URI",
    )
    parser.add_argument(
        "--token-file", type=Path, default=Path(".state/spotify-token.json")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cloud-playlist-bridge",
        description="独立、可恢复地把网易云歌单迁移到 Spotify",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    app = subparsers.add_parser("app", help="启动本地单页迁移应用")
    app.add_argument("--host", default="127.0.0.1", help="仅允许回环地址")
    app.add_argument("--port", type=int, default=8765)
    app.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    app.add_argument("--state-dir", type=Path, default=Path(".state"))
    app.add_argument("--report-dir", type=Path, default=Path("reports"))

    launcher = subparsers.add_parser(
        "install-launcher", help="安装当前系统的 Linux/macOS 图形启动器"
    )

    plan = subparsers.add_parser("plan", help="生成或恢复带校验和的迁移计划")
    plan.add_argument("playlist", help="网易云歌单 ID 或分享 URL")
    _add_spotify_options(plan)
    plan.add_argument("--job-file", type=Path, help="SQLite 检查点；默认按歌单 ID 生成")
    plan.add_argument("--report-dir", type=Path, default=Path("reports"))
    plan.add_argument("--expected-count", type=int)
    plan.add_argument(
        "--netease-api-base-url",
        default=os.environ.get("NETEASE_API_BASE_URL"),
        help=(
            "自建 api-enhanced 地址，例如 http://127.0.0.1:3000 "
            "（也可用 NETEASE_API_BASE_URL）"
        ),
    )
    plan.add_argument("--threshold", type=_probability, default=0.82)
    plan.add_argument("--ambiguity-gap", type=_probability, default=0.05)

    apply = subparsers.add_parser("apply", help="执行或恢复一个已固定的迁移计划")
    apply.add_argument("plan_file", type=Path, help="plan 命令生成的 .plan.json")
    _add_spotify_options(apply)
    visibility = apply.add_mutually_exclusive_group()
    visibility.add_argument("--private", action="store_true", help="创建私有歌单")
    visibility.add_argument("--public", action="store_true", help="创建公开歌单（默认）")
    return parser


def _spotify_from_args(args: argparse.Namespace) -> SpotifyClient:
    if not args.spotify_client_id:
        raise InputError("缺少 --spotify-client-id 或 SPOTIFY_CLIENT_ID")
    auth = SpotifyPKCEAuth(
        args.spotify_client_id,
        args.redirect_uri,
        TokenStore(args.token_file),
    )
    return SpotifyClient(auth)


def run_plan(args: argparse.Namespace) -> int:
    if args.expected_count is not None and args.expected_count < 0:
        raise InputError("--expected-count 不能为负数")
    playlist_id = parse_playlist_id(args.playlist)
    job_path = args.job_file or Path(".state/jobs") / f"netease-{playlist_id}.sqlite3"
    print(f"任务检查点：{job_path}")
    print("读取并验证网易云歌单…")
    if args.netease_api_base_url:
        print(f"网易云来源：自建 api-enhanced（{args.netease_api_base_url}）")
        netease = NetEaseClient(base_url=args.netease_api_base_url, enhanced_api=True)
    else:
        print("网易云来源：内置只读网页适配器")
        netease = NetEaseClient()
    source = netease.fetch_playlist(args.playlist, expected_count=args.expected_count)
    print(f"《{source.name}》：{len(source.tracks)} 首")

    spotify = _spotify_from_args(args)

    def show_progress(event: ProgressEvent) -> None:
        if event.completed == 1 or event.completed == event.total or event.completed % 25 == 0:
            origin = "恢复" if event.resumed else "处理"
            print(
                f"[{event.completed}/{event.total}] {origin}：{event.result.status} "
                f"{event.result.source.title}"
            )

    with JobStore(job_path) as store:
        if store.completed_count:
            print(f"发现 {store.completed_count} 首已保存结果，将从检查点继续。")
        plan = MigrationService(spotify).build_plan(
            source,
            threshold=args.threshold,
            ambiguity_gap=args.ambiguity_gap,
            store=store,
            progress=show_progress,
        )

    files = write_plan_bundle(plan, args.report_dir)
    print(f"计划完成：自动匹配 {len(plan.matched)}，手动添加 {len(plan.unmatched)}")
    print(f"固定计划：{files.plan}")
    print(f"完整报告：{files.report}")
    print(f"手动名单：{files.manual}")
    print(f"执行命令：cloud-playlist-bridge apply \"{files.plan}\" --spotify-client-id YOUR_CLIENT_ID")
    return 0


def run_apply(args: argparse.Namespace) -> int:
    plan, checksum = load_plan(args.plan_file)
    print(
        f"计划 {plan.plan_id[:12]}：自动写入 {len(plan.matched)}，"
        f"跳过并留待手动添加 {len(plan.unmatched)}"
    )
    spotify = _spotify_from_args(args)
    result = PlanExecutor(spotify).apply(
        plan,
        plan_path=args.plan_file,
        plan_checksum=checksum,
        public=not args.private,
    )
    print(f"执行完成：{result.added_count} 首，{result.playlist_url}")
    if plan.unmatched:
        manual = args.plan_file.with_name(args.plan_file.name.replace(".plan.json", ".manual.csv"))
        print(f"仍需手动添加 {len(plan.unmatched)} 首：{manual}")
    return 0


def run_app(args: argparse.Namespace) -> int:
    from .app import run_local_app

    return run_local_app(
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        state_dir=args.state_dir,
        report_dir=args.report_dir,
    )


def run_install_launcher() -> int:
    from .launchers import install_launcher

    result = install_launcher()
    print(f"已安装 {result.platform} 启动器：{result.path}")
    print("移动或重建 Python 虚拟环境后，请重新执行 install-launcher。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "install-launcher":
            return run_install_launcher()
        if args.command == "app":
            return run_app(args)
        if args.command == "plan":
            return run_plan(args)
        if args.command == "apply":
            return run_apply(args)
    except PartialMigrationError as exc:
        print(f"部分完成：{exc}", file=sys.stderr)
        print(f"已创建歌单：{exc.playlist_url}", file=sys.stderr)
        return 1
    except QuotaExceededError as exc:
        suffix = f"，建议等待至少 {exc.retry_after:.0f} 秒" if exc.retry_after else ""
        print(f"配额暂停：{exc}{suffix}", file=sys.stderr)
        return 1
    except InputError as exc:
        print(f"输入错误：{exc}", file=sys.stderr)
        return 2
    except BridgeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
