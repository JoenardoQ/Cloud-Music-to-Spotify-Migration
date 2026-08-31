from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import CandidateAssessment, MatchResult, SourceTrack, SpotifyTrack


_FEATURE_RE = re.compile(r"\b(?:feat(?:uring)?|ft)\.?\s+.+$", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_VERSION_WORDS = {
    "live",
    "remaster",
    "remastered",
    "acoustic",
    "instrumental",
    "karaoke",
    "demo",
    "radio edit",
    "伴奏",
    "现场",
    "重制",
}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("&", " and ")
    value = _FEATURE_RE.sub("", value)
    chars = [char if char.isalnum() else " " for char in value]
    return _SPACE_RE.sub(" ", "".join(chars)).strip()


def _versions(value: str) -> set[str]:
    normalized = normalize_text(value)
    padded = f" {normalized} "
    return {word for word in _VERSION_WORDS if f" {word} " in padded}


def _similarity(left: str, right: str) -> float:
    left_n, right_n = normalize_text(left), normalize_text(right)
    if not left_n or not right_n:
        return 0.0
    if left_n == right_n:
        return 1.0
    return SequenceMatcher(None, left_n, right_n).ratio()


def _artist_score(source: tuple[str, ...], candidate: tuple[str, ...]) -> float:
    if not source or not candidate:
        return 0.0
    scores = [
        _similarity(source_artist, candidate_artist)
        for source_artist in source
        for candidate_artist in candidate
    ]
    best = max(scores, default=0.0)
    source_set = {normalize_text(item) for item in source}
    candidate_set = {normalize_text(item) for item in candidate}
    union = source_set | candidate_set
    overlap = len(source_set & candidate_set) / len(union) if union else 0.0
    return 0.7 * best + 0.3 * overlap


def _duration_score(source_ms: int | None, candidate_ms: int | None) -> float:
    if source_ms is None or candidate_ms is None:
        return 0.5
    delta = abs(source_ms - candidate_ms)
    if delta <= 3_000:
        return 1.0
    if delta <= 10_000:
        return 0.8
    if delta <= 30_000:
        return 0.4
    return 0.0


def assess_candidate(source: SourceTrack, candidate: SpotifyTrack) -> CandidateAssessment:
    title_score = max(
        [_similarity(source.title, candidate.title)]
        + [_similarity(alias, candidate.title) for alias in source.aliases]
    )
    artist_score = _artist_score(source.artists, candidate.artists)
    duration_score = _duration_score(source.duration_ms, candidate.duration_ms)
    album_score = _similarity(source.album, candidate.album)
    score = (
        0.55 * title_score
        + 0.25 * artist_score
        + 0.15 * duration_score
        + 0.05 * album_score
    )
    source_versions, candidate_versions = _versions(source.title), _versions(candidate.title)
    version_penalty = 0.0
    if source_versions != candidate_versions and (source_versions or candidate_versions):
        version_penalty = 0.12
        score -= version_penalty
    return CandidateAssessment(
        track=candidate,
        score=round(max(0.0, min(1.0, score)), 4),
        title_score=round(title_score, 4),
        artist_score=round(artist_score, 4),
        duration_score=round(duration_score, 4),
        album_score=round(album_score, 4),
        version_penalty=version_penalty,
        year_delta=(
            abs(source.release_year - candidate.release_year)
            if source.release_year is not None and candidate.release_year is not None
            else None
        ),
    )


def build_search_queries(track: SourceTrack) -> list[str]:
    title = track.title.replace('"', " ").strip()
    artist = track.artists[0].replace('"', " ").strip() if track.artists else ""
    queries = []
    if artist:
        queries.append(f'track:"{title}" artist:"{artist}"')
    queries.append(f'track:"{title}"')
    normalized = normalize_text(title)
    if normalized and normalized != title.casefold():
        queries.append(f"{normalized} {artist}".strip())
    return list(dict.fromkeys(queries))


def choose_match(
    source: SourceTrack,
    candidates: list[SpotifyTrack],
    *,
    threshold: float = 0.82,
    ambiguity_gap: float = 0.05,
    minimum_title_score: float = 0.62,
    queries_made: int = 0,
    cache_hits: int = 0,
) -> MatchResult:
    unique = list({candidate.uri: candidate for candidate in candidates}.values())
    if not unique:
        return MatchResult(
            source,
            "not_found",
            "Spotify 搜索没有返回候选",
            queries_made=queries_made,
            cache_hits=cache_hits,
        )

    ranked = sorted(
        (assess_candidate(source, candidate) for candidate in unique),
        key=lambda item: item.score,
        reverse=True,
    )
    best = ranked[0]
    runner_up = ranked[1].score if len(ranked) > 1 else None
    common = {
        "source": source,
        "assessments": tuple(ranked[:3]),
        "queries_made": queries_made,
        "cache_hits": cache_hits,
    }
    if best.title_score < minimum_title_score:
        return MatchResult(status="low_confidence", reason="最佳候选的歌名相似度过低", **common)
    if best.score < threshold:
        return MatchResult(status="low_confidence", reason=f"最佳评分低于阈值 {threshold:.2f}", **common)
    if runner_up is not None and best.score - runner_up < ambiguity_gap:
        return MatchResult(status="ambiguous", reason="前两名候选差距不足，拒绝自动选择", **common)
    return MatchResult(status="matched", reason="满足评分与歧义阈值", **common)
