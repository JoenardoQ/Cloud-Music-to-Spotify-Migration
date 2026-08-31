from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cloud_playlist_bridge.app import (
    AppController,
    _handler,
    _loopback_host,
    _valid_host_header,
)
from cloud_playlist_bridge.models import SourcePlaylist, SourceTrack, SpotifyTrack


def wait_for_idle(controller: AppController, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = controller.snapshot({})
        if not state["busy"]:
            return state
        time.sleep(0.01)
    raise AssertionError("app worker did not finish")


class FakeSpotify:
    def __init__(self):
        self.remote = []

    def search_tracks(self, _query, limit=10):
        return [SpotifyTrack("spotify:track:1", "Song", ("Artist",), "Album", 100)]

    def create_playlist(self, _name, public, description):
        return {
            "id": "playlist",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist"},
        }

    def find_playlists_by_marker(self, _marker):
        return []

    def add_playlist_items(self, _playlist_id, uris):
        self.remote.extend(uris)
        return "snapshot"

    def get_playlist_item_uris(self, _playlist_id, offset, count):
        return self.remote[offset : offset + count]

    def update_playlist(self, _playlist_id, name, description):
        return None


class AppControllerTests(unittest.TestCase):
    def test_plan_and_apply_are_separate_actions_with_incremental_state(self):
        source = SourcePlaylist(
            "42",
            "Demo",
            "",
            None,
            1,
            (SourceTrack(1, "1", "Song", ("Artist",), "Album", 100),),
        )
        fake_spotify = FakeSpotify()
        with tempfile.TemporaryDirectory() as directory, patch(
            "cloud_playlist_bridge.app.NetEaseClient.fetch_playlist", return_value=source
        ), patch("cloud_playlist_bridge.app.SpotifyPKCEAuth"), patch(
            "cloud_playlist_bridge.app.SpotifyClient", return_value=fake_spotify
        ):
            root = Path(directory)
            controller = AppController(root / "state", root / "reports")
            controller.start_plan(
                {"playlist": "42", "spotify_client_id": "client", "private": True}
            )
            planned = wait_for_idle(controller)
            self.assertEqual(planned["phase"], "ready")
            self.assertTrue(planned["can_apply"])
            self.assertEqual(planned["summary"], {"matched": 1, "skipped": 0})
            self.assertEqual(fake_spotify.remote, [])

            generation = str(planned["generation"])
            no_repeat = controller.snapshot(
                {"generation": [generation], "source_after": ["1"], "result_after": ["1"]}
            )
            self.assertEqual(no_repeat["source_tracks"], [])
            self.assertEqual(no_repeat["results"], [])
            reset_client = controller.snapshot(
                {"generation": [str(planned["generation"] - 1)], "source_after": ["999"]}
            )
            self.assertEqual(len(reset_client["source_tracks"]), 1)

            controller.start_apply()
            applied = wait_for_idle(controller)
            self.assertEqual(applied["phase"], "completed")
            self.assertEqual(fake_spotify.remote, ["spotify:track:1"])
            self.assertEqual(
                applied["playlist_url"], "https://open.spotify.com/playlist/playlist"
            )

    def test_loopback_validation(self):
        self.assertTrue(_loopback_host("127.0.0.1"))
        self.assertFalse(_loopback_host("192.0.2.10"))
        self.assertTrue(_valid_host_header("localhost:8765"))
        self.assertTrue(_valid_host_header("127.0.0.1:8765"))
        self.assertFalse(_valid_host_header("attacker.example"))


class AppHttpTests(unittest.TestCase):
    def test_static_state_and_csrf_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = AppController(root / "state", root / "reports")
            server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(controller))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(f"{base}/", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b"Cloud Playlist Bridge", response.read())
                    self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
                with urlopen(f"{base}/api/state", timeout=2) as response:
                    state = json.load(response)
                self.assertEqual(state["phase"], "idle")
                request = Request(
                    f"{base}/api/plan",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request, timeout=2)
                self.assertEqual(caught.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
