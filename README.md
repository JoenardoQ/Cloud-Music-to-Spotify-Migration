# Cloud Playlist Bridge

[简体中文](README.zh-CN.md)

Cloud Playlist Bridge migrates playlist metadata that you can access from
NetEase Cloud Music to Spotify. It does not download audio, bypass membership
controls, or circumvent regional and copyright restrictions.

## Features

- A local single-page app with the NetEase playlist on the left, migration
  progress in the center, the Spotify result on the right, and live logs below.
- A two-step workflow: analyze and produce an immutable plan, then explicitly
  create the Spotify playlist.
- Source-order preservation based on complete NetEase `trackIds`.
- Explainable matching using title, artists, album, duration, and version tags.
- Strict rejection of ambiguous and low-confidence matches. Skipped tracks are
  exported to a dedicated manual-add CSV with candidate links.
- SQLite checkpoints and search caching for playlists containing 5,000–10,000
  tracks.
- Resumable Spotify writes in batches of at most 100 items.
- Scriptable `plan` and `apply` CLI commands remain available.

## Requirements

- Python 3.11 or later.
- A Spotify Premium account. Spotify development-mode apps require the app
  owner to have Premium under the 2026 development-mode rules.
- A Spotify Developer app with Web API enabled.
- Redirect URI `http://127.0.0.1:8888/callback`, registered exactly as written.

The runtime uses only the Python standard library. It does not require Codex,
ChatGPT, an agent, a plugin, or an MCP service.

## Install on Ubuntu

```bash
cd '/home/joenardo/My Projects/CloudMusic_to_Spotify_Migration'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Install on Windows

Install Python 3.11 or later, then run from PowerShell:

```powershell
cd 'C:\path\to\CloudMusic_to_Spotify_Migration'
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Install on macOS

Install Python 3.11 or later first, then run from Terminal:

```bash
cd '/path/to/CloudMusic_to_Spotify_Migration'
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Local app

Start the app:

```bash
cloud-playlist-bridge app
```

The command binds only to `127.0.0.1` and opens
`http://127.0.0.1:8765/`. On the single page:

1. Enter a NetEase playlist ID or share URL and your Spotify Client ID.
2. Optionally enter a self-hosted `api-enhanced` base URL.
3. Select **Analyze playlist**. Complete Spotify authorization if the browser
   opens the consent page.
4. Inspect matched and skipped counts. Ambiguous tracks remain skipped.
5. Select **Create Spotify playlist** to perform the external write.

The page renders large playlists with virtualized lists. Closing the page does
not corrupt a checkpoint; start the app and analyze the same playlist again to
resume saved matching work. Reports are written to `reports/` and state to
`.state/`.

Useful app options:

```text
app --host 127.0.0.1       Loopback address; non-loopback values are rejected
app --port 8765            Local page port
app --no-browser           Do not open the default browser automatically
app --state-dir .state     Checkpoints and Spotify token location
app --report-dir reports   Plan and CSV output location
```

Install a native launcher after installing the package:

```bash
cloud-playlist-bridge install-launcher
```

- Linux creates `~/.local/share/applications/cloud-playlist-bridge.desktop`.
- Windows creates `Cloud Playlist Bridge.vbs` in the current user's Start Menu
  Programs folder and stores state under `%LOCALAPPDATA%\Cloud Playlist Bridge`.
- macOS creates `~/Applications/Cloud Playlist Bridge.app`.

All launchers run the same local app and store state under the platform's user
application-data directory. If the virtual environment is moved or recreated,
run `install-launcher` again. The `app`, `plan`, and `apply` commands remain the
fallback on every platform.

## NetEase source API choices

Spotify operations always use the official Web API with Authorization Code
with PKCE. NetEase has two read-only source modes:

- The default adapter reads endpoints used by the public NetEase web page. It
  needs no extra service, but those endpoints are not a stable open-platform
  contract.
- A user-supplied `api-enhanced` URL uses `/playlist/detail` and
  `/song/detail`. `api-enhanced` is a third-party reverse-engineered service,
  not an official NetEase API. Run it locally and do not send cookies to public
  instances.

The current NetEase open platform does not expose a general replacement for
reading any personal playlist by share ID. The project therefore does not
invent open-platform credentials or present `api-enhanced` as official.

Example local `api-enhanced` service:

```bash
docker run --rm -p 127.0.0.1:3000:3000 moefurina/ncm-api:latest
```

## CLI workflow

The browser app is optional. `plan` and `apply` run the complete migration
workflow directly from a terminal and do not start the local app UI. Use the
virtual environment's interpreter explicitly so the commands do not depend on
shell activation or a generated console-script path:

Linux and macOS:

```bash
./.venv/bin/python -m cloud_playlist_bridge plan 'https://music.163.com/playlist?id=123456789' --spotify-client-id YOUR_CLIENT_ID
./.venv/bin/python -m cloud_playlist_bridge apply reports/NAME.plan.json --spotify-client-id YOUR_CLIENT_ID --private
```

Windows Command Prompt or PowerShell:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge plan "https://music.163.com/playlist?id=123456789" --spotify-client-id YOUR_CLIENT_ID
.venv\Scripts\python.exe -m cloud_playlist_bridge apply reports\NAME.plan.json --spotify-client-id YOUR_CLIENT_ID --private
```

The installed `cloud-playlist-bridge` command is a shorter equivalent on all
three systems. The first Spotify authorization still prints and normally opens
an OAuth URL in the default browser; this is authentication, not the local app
UI. The loopback callback must remain registered in the Spotify Developer app.

Create or resume a matching plan:

```bash
cloud-playlist-bridge plan \
  'https://music.163.com/playlist?id=123456789' \
  --spotify-client-id YOUR_CLIENT_ID
```

Use a local `api-enhanced` service:

```bash
cloud-playlist-bridge plan \
  'https://music.163.com/playlist?id=123456789' \
  --netease-api-base-url http://127.0.0.1:3000 \
  --spotify-client-id YOUR_CLIENT_ID
```

The plan command writes:

```text
<name>-<id>-<plan>.plan.json   Checksummed immutable execution plan
<name>-<id>-<plan>.csv         Full audit report
<name>-<id>-<plan>.manual.csv  Skipped tracks and up to three candidate links
```

Apply the fixed plan:

```bash
cloud-playlist-bridge apply reports/NAME.plan.json \
  --spotify-client-id YOUR_CLIENT_ID \
  --private
```

`SPOTIFY_CLIENT_ID` and `NETEASE_API_BASE_URL` can replace the corresponding
arguments. Spotify tokens default to `.state/spotify-token.json`; do not commit
or share that file.

## Matching and large playlists

The matcher weights title 55%, artists 25%, duration 15%, and album 5%.
Version mismatches such as live, remaster, instrumental, or demo are penalized.
A result must pass the total-score threshold, title floor, and ambiguity gap.
Otherwise it is marked `ambiguous`, `low_confidence`, or `not_found`, skipped,
and included in the manual CSV.

Spotify search has no batch endpoint, so a unique source track generally needs
at least one search request. Exact-query early stopping, per-job query caching,
bounded retry, and SQLite checkpoints reduce repeat work. Normal 429 responses
honor `Retry-After`; quota exhaustion stops with progress preserved. A 10,000
track write requires approximately 100 Spotify write batches.

## Non-goals and limitations

- No audio files, save timestamps, comments, or listening history are moved.
- Private or login-only NetEase playlists are not supported by the baseline.
- Cross-catalog metadata cannot prove that two tracks are the same recording.
- The app never auto-accepts a low-confidence result or deletes a partially
  created Spotify playlist after failure.
- Real Spotify OAuth and end-to-end writes require the user's credentials and
  cannot be completed by the offline test suite.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

See [docs/architecture.md](docs/architecture.md) for data flow, invariants,
failure behavior, and acceptance criteria.

## Status

Version 0.5.0 supports the local app on Linux, Windows, and macOS, CLI planning
and application, public NetEase playlists, optional self-hosted `api-enhanced`,
resumable planning and writes, and manual-add reports. Linux is runtime-tested;
the Windows and macOS launcher structures are generated and tested but have not
been executed on physical hosts for those systems in this environment.
