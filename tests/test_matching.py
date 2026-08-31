import unittest

from cloud_playlist_bridge.matching import (
    _versions,
    assess_candidate,
    build_search_queries,
    choose_match,
)
from cloud_playlist_bridge.models import SourceTrack, SpotifyTrack


def source(title="七里香", artists=("周杰伦",), duration=299000):
    return SourceTrack(1, "1", title, artists, "七里香", duration)


def candidate(uri, title="七里香", artists=("周杰伦",), duration=299500, album="七里香"):
    return SpotifyTrack(uri, title, artists, album, duration, f"https://open.spotify.com/{uri}")


class MatchingTests(unittest.TestCase):
    def test_exact_metadata_matches_and_has_auditable_components(self):
        result = choose_match(source(), [candidate("spotify:track:1")], queries_made=1)
        self.assertEqual(result.status, "matched")
        self.assertGreaterEqual(result.score, 0.95)
        self.assertEqual(result.queries_made, 1)
        self.assertEqual(result.assessments[0].title_score, 1.0)

    def test_version_mismatch_is_penalized(self):
        normal = assess_candidate(source(), candidate("spotify:track:normal"))
        live = assess_candidate(
            source(), candidate("spotify:track:live", title="七里香 Live")
        )
        self.assertGreater(normal.score - live.score, 0.1)

    def test_version_words_require_token_boundaries(self):
        self.assertEqual(_versions("Liverpool"), set())
        self.assertEqual(_versions("Demons"), set())
        self.assertEqual(_versions("Live at Wembley"), {"live"})
        self.assertEqual(_versions("伴奏"), {"伴奏"})

    def test_close_candidates_are_ambiguous_and_retained_for_manual_list(self):
        result = choose_match(
            source(),
            [
                candidate("spotify:track:one", duration=299500),
                candidate("spotify:track:two", duration=300000),
            ],
        )
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(len(result.assessments), 2)
        self.assertTrue(result.assessments[1].track.external_url)

    def test_wrong_title_is_rejected_even_with_artist(self):
        result = choose_match(
            source(), [candidate("spotify:track:wrong", title="晴天")]
        )
        self.assertEqual(result.status, "low_confidence")

    def test_queries_use_field_filters(self):
        queries = build_search_queries(source())
        self.assertTrue(queries[0].startswith('track:"七里香" artist:"周杰伦"'))


if __name__ == "__main__":
    unittest.main()
