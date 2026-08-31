import json
import io
import unittest
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.request import Request

from cloud_playlist_bridge.errors import InputError, RemoteApiError
from cloud_playlist_bridge.netease import NetEaseClient, parse_playlist_id


class PlaylistIdTests(unittest.TestCase):
    def test_accepts_id_and_common_urls(self):
        self.assertEqual(parse_playlist_id("12345"), "12345")
        self.assertEqual(
            parse_playlist_id("https://music.163.com/#/playlist?id=987&userid=1"), "987"
        )
        self.assertEqual(parse_playlist_id("https://music.163.com/playlist?id=456"), "456")

    def test_rejects_unrelated_input(self):
        with self.assertRaises(InputError):
            parse_playlist_id("not-a-playlist")


class NetEaseClientTests(unittest.TestCase):
    @staticmethod
    def fake_request(request, _timeout):
        if "playlist/detail" in request.full_url:
            return {
                "playlist": {
                    "name": "ordered",
                    "description": "demo",
                    "trackCount": 2,
                    "trackIds": [{"id": 2}, {"id": 1}],
                }
            }
        body = parse_qs(request.data.decode())
        requested = [str(item["id"]) for item in json.loads(body["c"][0])]
        songs = {
            "1": {"id": 1, "name": "one", "ar": [{"name": "A"}], "al": {"name": "X"}, "dt": 10},
            "2": {"id": 2, "name": "two", "ar": [{"name": "B"}], "al": {"name": "Y"}, "dt": 20},
        }
        return {"songs": [songs[item] for item in reversed(requested)]}

    def test_reorders_details_by_track_ids(self):
        playlist = NetEaseClient(request_json=self.fake_request).fetch_playlist("42")
        self.assertEqual([track.source_id for track in playlist.tracks], ["2", "1"])
        self.assertEqual([track.position for track in playlist.tracks], [1, 2])
        self.assertEqual(playlist.missing_source_ids, ())

    def test_expected_count_mismatch_stops(self):
        with self.assertRaises(RemoteApiError):
            NetEaseClient(request_json=self.fake_request).fetch_playlist("42", expected_count=3)

    def test_missing_song_keeps_playlist_summary_for_diagnostics(self):
        def request(request, _timeout):
            if "playlist/detail" in request.full_url:
                return {
                    "playlist": {
                        "name": "missing",
                        "trackCount": 1,
                        "trackIds": [{"id": 9}],
                        "tracks": [{
                            "id": 9,
                            "name": "Lost Song",
                            "ar": [{"name": "A"}],
                            "publishTime": 1577836800000,
                        }],
                    }
                }
            return {"songs": []}

        playlist = NetEaseClient(request_json=request).fetch_playlist("42")
        missing = playlist.missing_tracks[0]
        self.assertEqual(
            (missing.title, missing.artists, missing.release_date),
            ("Lost Song", ("A",), "2020-01-01"),
        )

    def test_enhanced_api_uses_documented_http_routes(self):
        requests = []

        def fake_enhanced(request, _timeout):
            requests.append(request)
            if "/playlist/detail?" in request.full_url:
                return {
                    "playlist": {
                        "name": "api",
                        "trackCount": 2,
                        "trackIds": [{"id": 2}, {"id": 1}],
                    }
                }
            ids = parse_qs(request.full_url.split("?", 1)[1])["ids"][0].split(",")
            return {
                "songs": [
                    {
                        "id": int(item),
                        "name": item,
                        "ar": [{"name": "artist"}],
                        "al": {"name": "album"},
                        "dt": 100,
                    }
                    for item in ids
                ]
            }

        playlist = NetEaseClient(
            base_url="http://127.0.0.1:3000/",
            enhanced_api=True,
            request_json=fake_enhanced,
        ).fetch_playlist("42")

        self.assertEqual([track.source_id for track in playlist.tracks], ["2", "1"])
        self.assertEqual(requests[0].get_method(), "GET")
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:3000/playlist/detail?id=42")
        self.assertEqual(requests[1].get_method(), "GET")
        self.assertEqual(parse_qs(requests[1].full_url.split("?", 1)[1])["ids"], ["2,1"])

    def test_enhanced_api_requires_complete_base_url(self):
        with self.assertRaisesRegex(InputError, "完整的 HTTP"):
            NetEaseClient(base_url="localhost:3000", enhanced_api=True)

    def test_transient_server_error_is_retried(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"ok": true}'

        responses = [
            HTTPError("https://music.163.com", 500, "error", Message(), io.BytesIO()),
            Response(),
        ]
        sleeps = []

        def opening(*_args, **_kwargs):
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        client = NetEaseClient(open_url=opening, sleep=sleeps.append)
        result = client._request_json(Request("https://music.163.com/test"), 1)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(sleeps, [1])


if __name__ == "__main__":
    unittest.main()
