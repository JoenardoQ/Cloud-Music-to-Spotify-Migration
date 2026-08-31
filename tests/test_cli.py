import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_playlist_bridge.cli import build_parser, main
from cloud_playlist_bridge.models import SourcePlaylist, SourceTrack, SpotifyTrack


class CliTests(unittest.TestCase):
    def test_plan_and_apply_are_plain_cli_commands(self):
        plan = build_parser().parse_args(["plan", "42", "--spotify-client-id", "client"])
        apply = build_parser().parse_args(
            ["apply", "reports/demo.plan.json", "--spotify-client-id", "client"]
        )
        self.assertEqual(plan.command, "plan")
        self.assertEqual(apply.command, "apply")
        self.assertFalse(apply.private)

    def test_invalid_playlist_is_input_exit_code_two(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main(["plan", "invalid", "--spotify-client-id", "client"])
        self.assertEqual(code, 2)
        self.assertIn("输入错误", stderr.getvalue())

    def test_plan_then_apply_runs_without_agent_runtime(self):
        source_track = SourceTrack(1, "1", "Song", ("Artist",), "Album", 200000)
        source = SourcePlaylist("42", "Demo", "", None, 1, (source_track,))

        class PlanningSpotify:
            def search_tracks(self, query, limit=10):
                return [
                    SpotifyTrack(
                        "spotify:track:one", "Song", ("Artist",), "Album", 200000
                    )
                ]

        class ApplyingSpotify:
            def __init__(self):
                self.remote = []

            def create_playlist(self, name, public, description):
                return {"id": "new", "external_urls": {"spotify": "https://example/new"}}

            def find_playlists_by_marker(self, marker):
                return []

            def add_playlist_items(self, playlist_id, uris):
                self.remote.extend(uris)
                return "snapshot"

            def get_playlist_item_uris(self, playlist_id, offset, count):
                return self.remote[offset : offset + count]

            def update_playlist(self, playlist_id, name, description):
                return None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "cloud_playlist_bridge.cli.NetEaseClient.fetch_playlist", return_value=source
            ), patch(
                "cloud_playlist_bridge.cli._spotify_from_args", return_value=PlanningSpotify()
            ):
                code = main(
                    [
                        "plan",
                        "42",
                        "--spotify-client-id",
                        "client",
                        "--job-file",
                        str(root / "job.sqlite3"),
                        "--report-dir",
                        str(root / "reports"),
                    ]
                )
            self.assertEqual(code, 0)
            plan_file = next((root / "reports").glob("*.plan.json"))
            applying = ApplyingSpotify()
            with patch("cloud_playlist_bridge.cli._spotify_from_args", return_value=applying):
                code = main(["apply", str(plan_file), "--spotify-client-id", "client"])
            self.assertEqual(code, 0)
            self.assertEqual(applying.remote, ["spotify:track:one"])


if __name__ == "__main__":
    unittest.main()
