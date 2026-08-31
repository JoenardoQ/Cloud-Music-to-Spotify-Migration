import io
import json
import tempfile
import time
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

from cloud_playlist_bridge.errors import QuotaExceededError, RemoteApiError
from cloud_playlist_bridge.spotify import SpotifyClient, SpotifyPKCEAuth, TokenStore


class FakeAuth:
    def __init__(self):
        self.forced = []

    def get_access_token(self, force_refresh=False):
        self.forced.append(force_refresh)
        return "token"


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.payload


def http_error(code, payload, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(
        "https://api.spotify.com/v1/search",
        code,
        "error",
        headers,
        io.BytesIO(json.dumps(payload).encode()),
    )


class SpotifyClientTests(unittest.TestCase):
    def test_quota_exceeded_is_not_retried(self):
        calls = []

        def opening(*_args, **_kwargs):
            calls.append(1)
            raise http_error(429, {"reason": "QUOTA_EXCEEDED"}, "120")

        client = SpotifyClient(FakeAuth(), open_url=opening, sleep=lambda _: None)
        with self.assertRaises(QuotaExceededError) as caught:
            client.search_tracks("track:test")
        self.assertEqual(len(calls), 1)
        self.assertEqual(caught.exception.retry_after, 120)

    def test_nested_quota_reason_is_recognized(self):
        client = SpotifyClient(
            FakeAuth(),
            open_url=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                http_error(429, {"error": {"reason": "QUOTA_EXCEEDED"}})
            ),
            sleep=lambda _: None,
        )
        with self.assertRaises(QuotaExceededError):
            client.search_tracks("track:test")

    def test_unauthorized_response_forces_one_token_refresh(self):
        auth = FakeAuth()
        responses = [http_error(401, {"error": "expired"}), Response({"tracks": {"items": []}})]

        def opening(*_args, **_kwargs):
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        client = SpotifyClient(auth, open_url=opening, sleep=lambda _: None)
        self.assertEqual(client.search_tracks("track:test"), [])
        self.assertEqual(auth.forced, [False, True])

    def test_bad_retry_after_falls_back_and_retries(self):
        responses = [
            http_error(429, {"reason": "RATE_LIMITED"}, "not-a-number"),
            Response({"tracks": {"items": []}}),
        ]
        sleeps = []

        def opening(*_args, **_kwargs):
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        client = SpotifyClient(FakeAuth(), open_url=opening, sleep=sleeps.append)
        self.assertEqual(client.search_tracks("track:test"), [])
        self.assertEqual(sleeps, [1])

    def test_malformed_search_shape_is_user_facing_error(self):
        client = SpotifyClient(FakeAuth(), open_url=lambda *_args, **_kwargs: Response({"tracks": []}))
        with self.assertRaises(RemoteApiError):
            client.search_tracks("track:test")

    def test_token_store_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TokenStore(Path(directory) / "token.json")
            store.save({"access_token": "secret"})
            self.assertEqual(store.load()["access_token"], "secret")

    def test_token_missing_new_scope_requires_reauthorization(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TokenStore(Path(directory) / "token.json")
            store.save(
                {
                    "client_id": "client",
                    "access_token": "old",
                    "expires_at": time.time() + 3600,
                    "scope": "playlist-modify-public playlist-modify-private",
                }
            )
            auth = SpotifyPKCEAuth(
                "client",
                "http://127.0.0.1:8888/callback",
                store,
                browser_open=lambda _: False,
            )
            auth._authorize = lambda: {"access_token": "new"}  # type: ignore[method-assign]
            self.assertEqual(auth.get_access_token(), "new")


if __name__ == "__main__":
    unittest.main()
