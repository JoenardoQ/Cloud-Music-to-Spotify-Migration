import tempfile
import unittest
from pathlib import Path

from cloud_playlist_bridge.errors import (
    PartialMigrationError,
    QuotaExceededError,
    SourceIncompleteError,
    UncertainMigrationError,
)
from cloud_playlist_bridge.execution import PlanExecutor
from cloud_playlist_bridge.jobs import JobStore
from cloud_playlist_bridge.matching import assess_candidate
from cloud_playlist_bridge.migration import MigrationService
from cloud_playlist_bridge.models import MatchResult, MigrationPlan, SourcePlaylist, SourceTrack, SpotifyTrack


def playlist(count=205, missing=(), *, identical=False):
    tracks = tuple(
        SourceTrack(
            index,
            str(index),
            "Same" if identical else f"Song {index}",
            ("Artist",),
            "Album",
            200000,
        )
        for index in range(1, count + 1)
    )
    return SourcePlaylist("42", "Source", "", None, count, tracks, tuple(missing))


def matched_result(track):
    candidate = SpotifyTrack(
        f"spotify:track:{track.position}",
        track.title,
        track.artists,
        track.album,
        track.duration_ms,
        f"https://open.spotify.com/track/{track.position}",
    )
    return MatchResult(track, "matched", "ok", (assess_candidate(track, candidate),))


class FakeSpotify:
    def __init__(self, *, fail_search_after=None, fail_add_after_write=None):
        self.created = 0
        self.search_calls = 0
        self.batches = []
        self.remote = []
        self.fail_search_after = fail_search_after
        self.fail_add_after_write = fail_add_after_write
        self.failed_add = False
        self.updated = 0

    def search_tracks(self, query, limit=10):
        self.search_calls += 1
        if self.fail_search_after is not None and self.search_calls > self.fail_search_after:
            raise QuotaExceededError("quota")
        title = query.split('"')[1]
        return [
            SpotifyTrack(
                f"spotify:track:{title}", title, ("Artist",), "Album", 200000
            )
        ]

    def create_playlist(self, name, public, description):
        self.created += 1
        return {
            "id": "new",
            "description": description,
            "external_urls": {"spotify": "https://open.spotify.com/playlist/new"},
        }

    def find_playlists_by_marker(self, marker):
        return []

    def add_playlist_items(self, playlist_id, uris):
        self.remote.extend(uris)
        self.batches.append(list(uris))
        if (
            self.fail_add_after_write is not None
            and len(self.batches) - 1 == self.fail_add_after_write
            and not self.failed_add
        ):
            self.failed_add = True
            raise RuntimeError("response lost")
        return f"snapshot-{len(self.batches)}"

    def get_playlist_item_uris(self, playlist_id, offset, count):
        return self.remote[offset : offset + count]

    def update_playlist(self, playlist_id, name, description):
        self.updated += 1


class PlanningTests(unittest.TestCase):
    def test_build_plan_never_writes(self):
        spotify = FakeSpotify()
        plan = MigrationService(spotify).build_plan(playlist(2))
        self.assertEqual(len(plan.matched), 2)
        self.assertEqual(spotify.created, 0)
        self.assertEqual(spotify.batches, [])
        self.assertEqual(spotify.search_calls, 2)

    def test_missing_source_details_stop_before_search(self):
        spotify = FakeSpotify()
        with self.assertRaises(SourceIncompleteError):
            MigrationService(spotify).build_plan(playlist(1, missing=("9",)))
        self.assertEqual(spotify.search_calls, 0)

    def test_identical_queries_are_cached_and_exact_matches_stop_early(self):
        with tempfile.TemporaryDirectory() as directory:
            spotify = FakeSpotify()
            with JobStore(Path(directory) / "job.sqlite3") as store:
                plan = MigrationService(spotify).build_plan(
                    playlist(3, identical=True), store=store
                )
            self.assertEqual(len(plan.matched), 3)
            self.assertEqual(spotify.search_calls, 1)
            self.assertEqual(plan.results[1].cache_hits, 1)

    def test_quota_interruption_resumes_saved_tracks(self):
        with tempfile.TemporaryDirectory() as directory:
            job_path = Path(directory) / "job.sqlite3"
            source = playlist(3)
            first = FakeSpotify(fail_search_after=1)
            with JobStore(job_path) as store:
                with self.assertRaises(QuotaExceededError):
                    MigrationService(first).build_plan(source, store=store)
                self.assertEqual(store.completed_count, 1)
            second = FakeSpotify()
            with JobStore(job_path) as store:
                plan = MigrationService(second).build_plan(source, store=store)
            self.assertEqual(len(plan.results), 3)
            self.assertEqual(second.search_calls, 2)

    def test_ten_thousand_track_checkpoint_uses_one_search_for_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            spotify = FakeSpotify()
            with JobStore(Path(directory) / "large.sqlite3") as store:
                plan = MigrationService(spotify).build_plan(
                    playlist(10_000, identical=True), store=store
                )
                self.assertEqual(store.completed_count, 10_000)
            self.assertEqual(len(plan.results), 10_000)
            self.assertEqual(spotify.search_calls, 1)


class ExecutionTests(unittest.TestCase):
    def test_apply_preserves_order_and_batches_at_100(self):
        with tempfile.TemporaryDirectory() as directory:
            spotify = FakeSpotify()
            source = playlist(205)
            plan = MigrationPlan(source, [matched_result(track) for track in source.tracks])
            result = PlanExecutor(spotify).apply(
                plan,
                plan_path=Path(directory) / "p.plan.json",
                plan_checksum="checksum",
                public=False,
            )
            self.assertEqual(result.added_count, 205)
            self.assertEqual([len(batch) for batch in spotify.batches], [100, 100, 5])
            self.assertEqual(spotify.remote[0], "spotify:track:1")
            self.assertEqual(spotify.remote[-1], "spotify:track:205")

    def test_lost_response_is_reconciled_without_duplicate_items(self):
        with tempfile.TemporaryDirectory() as directory:
            spotify = FakeSpotify(fail_add_after_write=0)
            source = playlist(101)
            plan = MigrationPlan(source, [matched_result(track) for track in source.tracks])
            plan_path = Path(directory) / "p.plan.json"
            executor = PlanExecutor(spotify)
            with self.assertRaises(PartialMigrationError):
                executor.apply(
                    plan,
                    plan_path=plan_path,
                    plan_checksum="checksum",
                    public=True,
                )
            result = executor.apply(
                plan,
                plan_path=plan_path,
                plan_checksum="checksum",
                public=True,
            )
            self.assertEqual(result.added_count, 101)
            self.assertEqual(spotify.remote, [f"spotify:track:{i}" for i in range(1, 102)])
            self.assertEqual(spotify.created, 1)

    def test_ambiguous_items_are_skipped_from_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            spotify = FakeSpotify()
            source = playlist(2)
            matched = matched_result(source.tracks[0])
            candidate = SpotifyTrack(
                "spotify:track:ambiguous",
                source.tracks[1].title,
                source.tracks[1].artists,
                source.tracks[1].album,
                source.tracks[1].duration_ms,
            )
            ambiguous = MatchResult(
                source.tracks[1],
                "ambiguous",
                "manual",
                (assess_candidate(source.tracks[1], candidate),),
            )
            plan = MigrationPlan(source, [matched, ambiguous])
            result = PlanExecutor(spotify).apply(
                plan,
                plan_path=Path(directory) / "p.plan.json",
                plan_checksum="checksum",
                public=True,
            )
            self.assertEqual(result.added_count, 1)
            self.assertEqual(spotify.remote, ["spotify:track:1"])

    def test_uncertain_create_is_recovered_by_plan_marker(self):
        class CreateResponseLostSpotify(FakeSpotify):
            def __init__(self):
                super().__init__()
                self.discovered = None

            def create_playlist(self, name, public, description):
                self.created += 1
                self.discovered = {
                    "id": "recovered",
                    "name": name,
                    "description": description,
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/recovered"},
                }
                raise RuntimeError("response lost")

            def find_playlists_by_marker(self, marker):
                return [self.discovered] if self.discovered else []

        with tempfile.TemporaryDirectory() as directory:
            spotify = CreateResponseLostSpotify()
            source = playlist(1)
            plan = MigrationPlan(source, [matched_result(source.tracks[0])])
            plan_path = Path(directory) / "p.plan.json"
            executor = PlanExecutor(spotify)
            with self.assertRaises(UncertainMigrationError):
                executor.apply(
                    plan,
                    plan_path=plan_path,
                    plan_checksum="checksum",
                    public=True,
                )
            result = executor.apply(
                plan,
                plan_path=plan_path,
                plan_checksum="checksum",
                public=True,
            )
            self.assertEqual(result.added_count, 1)
            self.assertEqual(spotify.created, 1)


if __name__ == "__main__":
    unittest.main()
