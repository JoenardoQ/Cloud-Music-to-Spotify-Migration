# Architecture Contract

[简体中文](architecture.zh-CN.md)

## Outcome and users

This document is for maintainers of the playlist migration tool. A successful
migration preserves source order, produces a reviewable result for every source
entry, writes only high-confidence matches, and requires explicit user approval
before changing Spotify.

## Boundaries

```text
local SPA / standalone CLI -> NetEase read adapter -> source models
                           -> SQLite job/checkpoint + Spotify search cache
                           -> staged search -> deterministic Matcher
                           -> checksummed immutable plan + CSV + manual CSV
explicit apply action      -> verified plan -> execution journal
                           -> Spotify playlist writer -> resumable batches
```

- `netease.py` reads public NetEase metadata and validates counts and required
  fields. It supports the read-only endpoints used by the public web page and a
  user-operated, `api-enhanced`-compatible service. Both modes share the same
  integrity checks and domain models.
- `spotify.py` owns PKCE authorization, token refresh, HTTP retries, search, and
  playlist writes.
- `matching.py` contains the deterministic, network-free matching algorithm.
- `jobs.py` owns planning checkpoints and the search cache for the active
  migration.
- `plans.py` is the sole owner of plan serialization, integrity validation,
  reports, and manual-add lists.
- `execution.py` owns the external-write journal, batch recovery, and uncertain
  state reconciliation.
- `migration.py` coordinates staged searches without hiding quota or source-data
  failures.
- `cli.py` handles input and human-readable output, but contains no business
  algorithm. The installed entry point and `python -m cloud_playlist_bridge`
  both expose `plan` and `apply` without starting the web app.
- `app.py` is a loopback-only HTTP orchestration layer. It calls the same
  services on background threads and exposes incremental state to the SPA.
- `web/` is a self-contained SPA. Its track lists use windowed rendering to
  avoid creating a DOM node for every track in a large playlist.
- `launchers.py` creates platform launchers that invoke the same Python module
  and browser UI. Launcher state is stored in the current user's application
  data directory.
- The application is ordinary Python and does not require an agent, plugin, or
  Codex runtime.

## Data flow and invariants

1. Parse a numeric playlist ID from the input.
2. Fetch playlist details. `trackIds`, not a possibly truncated `tracks` list,
   define the complete source order.
3. Fetch track details in batches, index them by ID, and restore `trackIds`
   order.
4. Stop on conflicts among `trackCount`, `trackIds`, and `--expected-count`.
   Missing details stop planning unless the user explicitly allows an
   incomplete migration.
5. Commit search and matching results to the job database one track at a time.
   Resume only against the same source snapshot.
6. Try the exact query first. Stop early when it meets the automatic-match
   requirements; otherwise run fallback queries. Reuse cached identical
   queries.
7. Include the schema version, plan ID, source digest, policy settings, and a
   SHA-256 integrity checksum in every completed plan. `apply` accepts only a
   valid plan and never searches again.
8. Write only `matched` URIs, in source order. Put every skipped item, its
   reason, and up to three candidate links in `manual.csv`.
9. Write at most 100 tracks per Spotify request. Record an inflight batch before
   sending it and persist the confirmed count and snapshot ID afterward.
   Reconcile an uncertain batch before resuming.

## Matching contract

The matcher applies Unicode NFKC normalization, case folding, and whitespace
and punctuation normalization. It recognizes common version labels as complete
words or explicit Chinese labels. Scores combine title, complete artist set,
duration, and album. An automatic match must meet the minimum total score,
minimum title score, and ambiguity gap; otherwise it is `low_confidence` or
`ambiguous`. The algorithm does not use machine learning or Spotify content for
model training.

## Security and privacy

- The desktop client uses Authorization Code with PKCE and never requests a
  client secret.
- OAuth scopes are limited to public and private playlist modification plus the
  private-playlist read access needed for recovery.
- Validate OAuth state and listen for callbacks only on an explicit loopback
  address.
- Restrict token files to the current user where the platform permits, and keep
  them outside version control.
- Never place access tokens, refresh tokens, or NetEase cookies in logs or
  reports.
- Bind the app to `127.0.0.1` by default and require its process-generated CSRF
  token on every state-changing request. Spotify tokens must not enter browser
  state or logs.
- Accept an `api-enhanced` service only when the user configures it explicitly.
  Users are responsible for third-party service installation, updates, and
  cookie handling.

## Failure semantics

- Invalid input exits with status 2 and performs no external write.
- Network, schema, authentication, or exhausted-rate-limit failures exit with
  status 1 and identify the failing stage.
- Planning progress remains resumable after quota exhaustion.
- A missing match is a result, not a program failure; report it and continue.
  Refuse to apply a plan with no matches.
- A failure after Spotify playlist creation leaves the execution journal in
  `partial` or `uncertain`. A repeated `apply` reconciles and resumes. If remote
  state cannot be determined safely, stop and report the recovery condition.

## Maintainer verification

Run the offline checks from the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

The maintained behavior includes URL and ID parsing, source-order restoration,
matching and ambiguity rejection, cached and resumable planning, plan integrity,
write batching and recovery, report generation, loopback and CSRF boundaries,
and launcher generation. New behavior must add or update the corresponding
tests without introducing real account data or generated migration reports into
the repository.
