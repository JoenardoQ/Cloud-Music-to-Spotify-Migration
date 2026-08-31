from __future__ import annotations

import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_playlist_bridge.launchers import install_launcher


class LauncherTests(unittest.TestCase):
    def test_linux_desktop_launcher_uses_selected_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = install_launcher(
                platform="linux", python=Path("/opt/cpb venv/bin/python"), home=home
            )
            self.assertEqual(result.path.name, "cloud-playlist-bridge.desktop")
            desktop = result.path.read_text(encoding="utf-8")
            wrapper = home / ".local/share/cloud-playlist-bridge/launch.sh"
            self.assertIn(f"Exec={wrapper}", desktop)
            self.assertIn(
                "'/opt/cpb venv/bin/python' -m cloud_playlist_bridge app",
                wrapper.read_text(),
            )
            self.assertTrue(wrapper.stat().st_mode & 0o100)

    def test_windows_start_menu_launcher_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "用户 Profile"
            roaming = root / "Roaming Data"
            local = root / "Local Data"
            python = home / "venv" / "Scripts" / "python.exe"
            result = install_launcher(
                platform="windows",
                python=python,
                home=home,
                roaming_app_data=roaming,
                local_app_data=local,
            )
            self.assertEqual(result.platform, "windows")
            self.assertEqual(
                result.path,
                roaming
                / "Microsoft/Windows/Start Menu/Programs/Cloud Playlist Bridge.vbs",
            )
            launcher = result.path.read_text(encoding="utf-16")
            self.assertIn(str(python.resolve()), launcher)
            self.assertIn(str(local / "Cloud Playlist Bridge" / "state"), launcher)
            self.assertIn(str(local / "Cloud Playlist Bridge" / "reports"), launcher)
            self.assertIn("cloud_playlist_bridge", launcher)
            self.assertIn(f'"""{python.resolve()}""', launcher)
            self.assertIn(", 0, False", launcher)

    def test_win32_is_detected_as_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roaming = root / "roaming"
            local = root / "local"
            with patch("cloud_playlist_bridge.launchers.sys.platform", "win32"), patch.dict(
                os.environ,
                {"APPDATA": str(roaming), "LOCALAPPDATA": str(local)},
            ):
                result = install_launcher(
                    python=root / "python.exe",
                    home=root,
                )
            self.assertEqual(result.platform, "windows")
            self.assertEqual(result.path.suffix, ".vbs")
            self.assertTrue(result.path.is_relative_to(roaming))
            self.assertIn(
                str(local / "Cloud Playlist Bridge"),
                result.path.read_text("utf-16"),
            )

    def test_macos_app_bundle_uses_application_support(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = install_launcher(
                platform="macos", python=Path("/opt/cpb/bin/python3"), home=home
            )
            self.assertEqual(result.path.suffix, ".app")
            executable = result.path / "Contents/MacOS/CloudPlaylistBridge"
            plist = result.path / "Contents/Info.plist"
            self.assertIn(
                "Library/Application Support/Cloud Playlist Bridge",
                executable.read_text(),
            )
            with plist.open("rb") as handle:
                metadata = plistlib.load(handle)
            self.assertEqual(metadata["CFBundleIdentifier"], "local.cloud-playlist-bridge")
            self.assertTrue(executable.stat().st_mode & 0o100)


if __name__ == "__main__":
    unittest.main()
