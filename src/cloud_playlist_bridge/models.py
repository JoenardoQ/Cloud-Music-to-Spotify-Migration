from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class SourceTrack:
    position: int
    source_id: str
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int | None = None
    aliases: tuple[str, ...] = ()
    release_year: int | None = None


@dataclass(frozen=True, slots=True)
class MissingSourceTrack:
    source_id: str
    title: str | None = None
    artists: tuple[str, ...] = ()
    release_date: str | None = None


@dataclass(frozen=True, slots=True)
class SourcePlaylist:
    source_id: str
    name: str
    description: str
    cover_url: str | None
    declared_count: int
    tracks: tuple[SourceTrack, ...]
    missing_source_ids: tuple[str, ...] = ()
    missing_tracks: tuple[MissingSourceTrack, ...] = ()


@dataclass(frozen=True, slots=True)
class SpotifyTrack:
    uri: str
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int | None
    external_url: str | None = None
    release_year: int | None = None


MatchStatus = Literal["matched", "not_found", "low_confidence", "ambiguous"]


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    track: SpotifyTrack
    score: float
    title_score: float
    artist_score: float
    duration_score: float
    album_score: float
    version_penalty: float
    year_delta: int | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    source: SourceTrack
    status: MatchStatus
    reason: str
    assessments: tuple[CandidateAssessment, ...] = ()
    queries_made: int = 0
    cache_hits: int = 0

    @property
    def score(self) -> float:
        return self.assessments[0].score if self.assessments else 0.0

    @property
    def candidate(self) -> SpotifyTrack | None:
        return self.assessments[0].track if self.assessments else None

    @property
    def runner_up_score(self) -> float | None:
        return self.assessments[1].score if len(self.assessments) > 1 else None

    @property
    def candidates_considered(self) -> int:
        return len(self.assessments)


@dataclass(slots=True)
class MigrationPlan:
    source: SourcePlaylist
    results: list[MatchResult] = field(default_factory=list)
    threshold: float = 0.82
    ambiguity_gap: float = 0.05
    plan_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def matched(self) -> list[MatchResult]:
        return [item for item in self.results if item.status == "matched"]

    @property
    def unmatched(self) -> list[MatchResult]:
        return [item for item in self.results if item.status != "matched"]

@dataclass(frozen=True, slots=True)
class CommitResult:
    playlist_id: str
    playlist_url: str
    added_count: int
