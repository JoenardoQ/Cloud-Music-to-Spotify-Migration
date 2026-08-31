import csv
import json
import tempfile
import unittest
from pathlib import Path

from cloud_playlist_bridge.errors import InputError
from cloud_playlist_bridge.matching import choose_match
from cloud_playlist_bridge.models import MigrationPlan, SourcePlaylist, SourceTrack, SpotifyTrack
from cloud_playlist_bridge.plans import load_plan, write_plan_bundle


def sample_plan():
    first = SourceTrack(1, "1", "Exact", ("Artist",), "Album", 200000)
    second = SourceTrack(2, "2", "Ambiguous", ("Artist",), "Album", 200000)
    exact = SpotifyTrack(
        "spotify:track:exact",
        "Exact",
        ("Artist",),
        "Album",
        200000,
        "https://open.spotify.com/track/exact",
    )
    ambiguous_one = SpotifyTrack(
        "spotify:track:one",
        "Ambiguous",
        ("Artist",),
        "Album",
        200000,
        "https://open.spotify.com/track/one",
    )
    ambiguous_two = SpotifyTrack(
        "spotify:track:two",
        "Ambiguous",
        ("Artist",),
        "Album",
        200100,
        "https://open.spotify.com/track/two",
    )
    source = SourcePlaylist("42", "Demo", "", None, 2, (first, second))
    return MigrationPlan(
        source,
        [
            choose_match(first, [exact]),
            choose_match(second, [ambiguous_one, ambiguous_two]),
        ],
    )


class PlanTests(unittest.TestCase):
    def test_plan_round_trip_and_manual_list(self):
        with tempfile.TemporaryDirectory() as directory:
            files = write_plan_bundle(sample_plan(), Path(directory))
            loaded, checksum = load_plan(files.plan)
            self.assertEqual(len(loaded.matched), 1)
            self.assertEqual(len(loaded.unmatched), 1)
            self.assertEqual(len(checksum), 64)
            with files.manual.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "ambiguous")
            self.assertIn("open.spotify.com/track/one", rows[0]["candidate_1_url"])
            self.assertIn("open.spotify.com/track/two", rows[0]["candidate_2_url"])

    def test_tampered_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            files = write_plan_bundle(sample_plan(), Path(directory))
            document = json.loads(files.plan.read_text(encoding="utf-8"))
            document["results"][0]["assessments"][0]["track"]["uri"] = "spotify:track:changed"
            files.plan.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(InputError):
                load_plan(files.plan)

    def test_unique_plan_ids_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first = write_plan_bundle(sample_plan(), Path(directory))
            second = write_plan_bundle(sample_plan(), Path(directory))
            self.assertNotEqual(first.plan, second.plan)
            self.assertTrue(first.plan.exists())
            self.assertTrue(second.plan.exists())


if __name__ == "__main__":
    unittest.main()
