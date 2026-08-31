from __future__ import annotations

import tempfile
import unittest
import plistlib
from pathlib import Path

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
