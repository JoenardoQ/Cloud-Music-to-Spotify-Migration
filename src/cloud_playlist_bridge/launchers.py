from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import InputError, RemoteApiError


@dataclass(frozen=True, slots=True)
class LauncherResult:
    platform: str
    path: Path


def _write(
    path: Path, content: str, *, executable: bool = False, encoding: str = "utf-8"
) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        if executable:
            path.chmod(0o755)
    except OSError as exc:
        raise RemoteApiError(f"无法创建启动器 {path}：{exc}") from exc


def _linux_launcher(python: Path, home: Path) -> LauncherResult:
    data_root = home / ".local" / "share" / "cloud-playlist-bridge"
    wrapper = data_root / "launch.sh"
    command = " ".join(
        [
            shlex.quote(str(python)),
            "-m cloud_playlist_bridge app",
            "--state-dir",
            shlex.quote(str(data_root / "state")),
            "--report-dir",
            shlex.quote(str(data_root / "reports")),
        ]
    )
    _write(wrapper, f"#!/bin/sh\nexec {command}\n", executable=True)
    desktop = home / ".local" / "share" / "applications" / "cloud-playlist-bridge.desktop"
    _write(
        desktop,
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                "Name=Cloud Playlist Bridge",
                "Comment=Migrate NetEase playlists to Spotify",
                f"Exec={wrapper}",
                "Icon=audio-x-generic",
                "Terminal=false",
                "Categories=AudioVideo;Utility;",
                "StartupNotify=true",
                "",
            ]
        ),
        executable=True,
    )
    return LauncherResult("linux", desktop)


def _windows_launcher(
    python: Path,
    home: Path,
    *,
    roaming_app_data: Path | None = None,
    local_app_data: Path | None = None,
) -> LauncherResult:
    roaming_root = roaming_app_data or Path(
        os.environ.get("APPDATA") or home / "AppData" / "Roaming"
    )
    local_root = local_app_data or Path(
        os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local"
    )
    data_root = local_root / "Cloud Playlist Bridge"
    command = subprocess.list2cmdline(
        [
            str(python),
            "-m",
            "cloud_playlist_bridge",
            "app",
            "--state-dir",
            str(data_root / "state"),
            "--report-dir",
            str(data_root / "reports"),
        ]
    )
    escaped_command = command.replace('"', '""')
    launcher = (
        roaming_root
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Cloud Playlist Bridge.vbs"
    )
    _write(
        launcher,
        "Option Explicit\r\n"
        "Dim shell\r\n"
        'Set shell = CreateObject("WScript.Shell")\r\n'
        f'shell.Run "{escaped_command}", 0, False\r\n',
        encoding="utf-16",
    )
    return LauncherResult("windows", launcher)


def _macos_launcher(python: Path, home: Path) -> LauncherResult:
    app = home / "Applications" / "Cloud Playlist Bridge.app"
    executable = app / "Contents" / "MacOS" / "CloudPlaylistBridge"
    data_root = home / "Library" / "Application Support" / "Cloud Playlist Bridge"
    command = " ".join(
        [
            shlex.quote(str(python)),
            "-m cloud_playlist_bridge app",
            "--state-dir",
            shlex.quote(str(data_root / "state")),
            "--report-dir",
            shlex.quote(str(data_root / "reports")),
        ]
    )
    _write(executable, f"#!/bin/sh\nexec {command}\n", executable=True)
    plist = app / "Contents" / "Info.plist"
    _write(
        plist,
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDisplayName</key><string>Cloud Playlist Bridge</string>
  <key>CFBundleExecutable</key><string>CloudPlaylistBridge</string>
  <key>CFBundleIdentifier</key><string>local.cloud-playlist-bridge</string>
  <key>CFBundleName</key><string>Cloud Playlist Bridge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.5.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
""",
    )
    return LauncherResult("macos", app)


def install_launcher(
    *,
    platform: str | None = None,
    python: Path | None = None,
    home: Path | None = None,
    roaming_app_data: Path | None = None,
    local_app_data: Path | None = None,
) -> LauncherResult:
    if platform:
        selected = platform
    elif sys.platform == "darwin":
        selected = "macos"
    elif sys.platform == "win32":
        selected = "windows"
    elif sys.platform.startswith("linux"):
        selected = "linux"
    else:
        selected = sys.platform
    interpreter = (python or Path(sys.executable)).resolve()
    user_home = (home or Path.home()).resolve()
    if selected == "linux":
        return _linux_launcher(interpreter, user_home)
    if selected == "windows":
        return _windows_launcher(
            interpreter,
            user_home,
            roaming_app_data=roaming_app_data,
            local_app_data=local_app_data,
        )
    if selected == "macos":
        return _macos_launcher(interpreter, user_home)
    raise InputError(
        "启动器仅支持 Linux、Windows 和 macOS；仍可使用 app、plan 和 apply 命令"
    )
