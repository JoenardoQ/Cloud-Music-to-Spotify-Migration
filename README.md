# Cloud Playlist Bridge

[简体中文](README.zh-CN.md) · [User guide](USER_GUIDE.md)

Migrate a publicly accessible NetEase Cloud Music playlist to Spotify. The
program reads playlist metadata locally, searches Spotify, and creates a
reviewable matching plan. It creates a Spotify playlist only after your final
confirmation.

It does not download audio, bypass membership controls, read private playlists,
or circumvent regional and copyright restrictions.

## What it does

- Processes tracks in their original NetEase playlist order.
- Matches Spotify tracks using title, artists, album, duration, and version tags.
- Writes only high-confidence matches; ambiguous, low-confidence, and missing
  results are skipped.
- Produces a full CSV, a manual-add CSV, and a checksummed migration plan.
- Saves matching and write progress so interrupted work can resume.
- Provides a local web app and `plan` / `apply` commands that work without the
  app page.
- Supports Windows, macOS, and Linux and uses only the Python standard library
  at runtime.

## Before you start

You need:

- Python 3.11 or later;
- a Spotify Premium account;
- a Spotify Developer app that you created and its Client ID;
- a NetEase Cloud Music public playlist that opens without signing in; and
- a working internet connection during installation, playlist reading, Spotify
  authorization, and migration.

Spotify requires the owner of a development-mode app to keep Premium and limits
authorized users and API quota. For personal use, use a Client ID created under
your own account. See Spotify's official
[development-mode rules](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).

## Choose a workflow

| Workflow | Best for | Opens the local app page |
| --- | --- | --- |
| Local app | Users who prefer a form and live progress | Yes |
| Command line | Users running from CMD, a terminal, or a script | No |
| Native launcher | Installed users who want a Start menu or Applications entry | Yes |

All three use the same migration logic. The first command-line authorization
may still open or print a Spotify login URL. That is OAuth authentication, not
the local app page.

## 1. Download the project

Open the [GitHub project](https://github.com/JoenardoQ/Cloud-Music-to-Spotify-Migration),
select **Code → Download ZIP**, and extract the archive. Run every command below
from the extracted project folder.

If folders, CMD, or terminals are unfamiliar, use the
[user guide](USER_GUIDE.md).

## 2. Install Python, the environment, and the app

The project is currently installed from the downloaded source into an isolated
`.venv` inside the project folder. Installing Python or Ubuntu system packages
may require administrator approval, but the app itself is not installed
system-wide.

### Windows (Command Prompt)

1. Install Python 3.11 or later from the
   [Python Windows downloads page](https://www.python.org/downloads/windows/).
   Select **Add python.exe to PATH** if the installer offers it.
2. Open the project folder in File Explorer, select the address bar, type `cmd`,
   and press Enter.
3. Run these lines one at a time in the black Command Prompt window:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
```

### macOS

1. Install Python 3.11 or later from the
   [Python macOS downloads page](https://www.python.org/downloads/macos/).
2. Open Terminal, type `cd `, drag the project folder into Terminal, and press
   Enter.
3. Run these lines one at a time:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install .
```

### Ubuntu / Debian

Open a terminal in the project folder and run:

```bash
sudo apt update
sudo apt install -y python3 python3-venv
python3 -m venv .venv
./.venv/bin/python -m pip install .
```

The rest of this guide calls the Python interpreter inside `.venv` explicitly.
You do not need to run `activate`, and another Python environment cannot be used
by mistake.

## 3. Prepare a Spotify Client ID

1. Sign in to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Create an app; choose any suitable name and description.
3. Add the following Redirect URI in the app settings. It must match exactly:

   ```text
   http://127.0.0.1:8888/callback
   ```

4. Save the settings and copy the **Client ID**.

The program uses Authorization Code with PKCE and does not need the Client
Secret. Do not enter or share the Client Secret. Spotify requires an explicit
loopback IP for this callback; do not replace `127.0.0.1` with `localhost`. See
Spotify's official [Redirect URI rules](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri).

## 4. Use the local app

### Start the app

Windows Command Prompt:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge app --no-browser
```

macOS or Linux:

```bash
./.venv/bin/python -m cloud_playlist_bridge app --no-browser
```

When the following address is printed, keep CMD or the terminal open and open
the address in your browser:

[http://127.0.0.1:8765/](http://127.0.0.1:8765/)

`--no-browser` only disables automatic browser opening; it does not disable the
app. The service accepts only loopback bindings, so other devices cannot reach
it over the local network.

### Migrate a playlist

1. Paste a NetEase playlist share URL or numeric playlist ID.
2. Paste the Spotify Client ID.
3. Select `分析歌单` (**Analyze playlist**) and complete Spotify authorization.
4. Wait for matching to finish, review matched and skipped counts, and download
   the manual-add list if needed.
5. Select `创建 Spotify 歌单` (**Create Spotify playlist**) only after accepting
   the result.

`分析歌单` reads data, searches, and writes local plan files. It does not create
a Spotify playlist. Only the final action writes to Spotify. The default target
playlist is public. To make it private, open `高级设置` (**Advanced settings**)
and select `创建为私有歌单` (**Create as private playlist**) before analysis.

The current app interface uses Chinese labels. `分析歌单` means **Analyze
playlist**, `创建 Spotify 歌单` means **Create Spotify playlist**, and `高级设置`
means **Advanced settings**.

### Advanced options

- `Local api-enhanced`: use a compatible service that you operate; leave blank
  for normal use.
- `Expected track count`: if you know the count shown by the web page, enter it;
  a mismatch stops the operation instead of silently losing tracks.
- `Minimum score`: default `0.82`.
- `Ambiguity gap`: default `0.05`.
- `Allow incomplete migration`: continue when NetEase omits individual track
  details, with those tracks skipped.

Do not lower matching thresholds unless you understand the consequence. Lower
values increase the chance of writing a wrong song or recording version.

## 5. Use the command line

The command-line workflow has two explicit stages: `plan` creates a plan for
review, and only `apply` writes to Spotify.

### Create or resume a plan

Windows Command Prompt:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge plan "https://music.163.com/playlist?id=123456789" --spotify-client-id YOUR_CLIENT_ID
```

macOS or Linux:

```bash
./.venv/bin/python -m cloud_playlist_bridge plan 'https://music.163.com/playlist?id=123456789' --spotify-client-id YOUR_CLIENT_ID
```

Replace the example playlist and `YOUR_CLIENT_ID` with your values. A numeric
playlist ID also works.

If NetEase omits track details, the default is to stop and list every available
title, artist, release date, and ID. If you accept skipping those tracks, append
this option to the `plan` command:

```text
--allow-incomplete-source
```

### Review the output

`plan` writes three files to `reports` by default:

```text
<name>-<playlist-ID>-<plan-ID>.plan.json   Checksummed fixed execution plan
<name>-<playlist-ID>-<plan-ID>.csv         Full per-track matching report
<name>-<playlist-ID>-<plan-ID>.manual.csv  All skipped tracks and up to 3 candidate links
```

Review the CSV first. `matched` entries will be written automatically;
`ambiguous`, `low_confidence`, and `not_found` entries are skipped. After the
plan is created, `apply` does not search again or change the matches.

### Apply the plan

Windows Command Prompt:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge apply "reports\NAME.plan.json" --spotify-client-id YOUR_CLIENT_ID --private
```

macOS or Linux:

```bash
./.venv/bin/python -m cloud_playlist_bridge apply 'reports/NAME.plan.json' --spotify-client-id YOUR_CLIENT_ID --private
```

Replace `NAME.plan.json` with the generated filename. Omit `--private` to create
a public playlist; `--public` can also state the default explicitly. The shorter
installed `cloud-playlist-bridge` command works too, but the explicit interpreter
form does not depend on PATH or terminal activation.

Useful environment variables:

```text
SPOTIFY_CLIENT_ID       Replaces --spotify-client-id
NETEASE_API_BASE_URL    Replaces --netease-api-base-url
```

## Incomplete sources and matching results

NetEase `trackIds` define the complete count and order. If NetEase omits details
for any track, the program stops before Spotify search by default because
continuing could cause missing tracks, wrong order, or incorrect matches.

The program continues only after you select **Allow incomplete migration** in
the app or add `--allow-incomplete-source` to the CLI. Missing tracks keep their
original positions, receive `not_found`, and enter the manual report. They are
never sent to Spotify search or written to the Spotify playlist.

Other uncertain results are also skipped. The app does not provide a per-track
force-accept control. Use the candidate links in `manual.csv` to complete the
playlist manually when necessary.

## Interruptions, recovery, and file locations

- Planning progress is stored in a SQLite checkpoint. Repeating the same
  playlist with the same matching settings reuses saved results.
- Spotify writes use batches of at most 100 tracks. After an interrupted
  `apply`, run the same plan again; the execution journal checks the remote
  playlist and resumes instead of blindly duplicating the playlist or tracks.
- If the remote playlist was manually changed, the program may stop and ask you
  to inspect it instead of guessing the correct state.
- Direct app and CLI workflows store tokens and checkpoints in `.state`, and
  plans and reports in `reports`, by default.

To stop the app, return to its CMD or terminal window and press `Ctrl+C`. You do
not need to reinstall next time; run the same start command again.

## Optional native launcher

After installation, create a launcher for the current platform.

Windows Command Prompt:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge install-launcher
```

macOS or Linux:

```bash
./.venv/bin/python -m cloud_playlist_bridge install-launcher
```

- Windows: `Cloud Playlist Bridge.vbs` in the current user's Start Menu Programs
  folder; data under `%LOCALAPPDATA%\Cloud Playlist Bridge`.
- macOS: `~/Applications/Cloud Playlist Bridge.app`; data under
  `~/Library/Application Support/Cloud Playlist Bridge`.
- Linux: `~/.local/share/applications/cloud-playlist-bridge.desktop`; data under
  `~/.local/share/cloud-playlist-bridge`.

The launcher records the Python path used during installation. Run
`install-launcher` again after moving the project, deleting `.venv`, or rebuilding
the environment.

## NetEase source modes

The default mode reads the endpoints used by the public NetEase web page. It
needs no NetEase login or cookie, but those endpoints are not a stable official
open-platform contract and may break after a NetEase change.

Advanced users can supply a locally operated compatible `api-enhanced` service
with `--netease-api-base-url http://127.0.0.1:3000` or the app's advanced field.
Such services are third-party reverse-engineered implementations, not an
official NetEase API. Use only a trusted local instance and never send cookies
to a public instance.

## Troubleshooting

### `Address already in use`

Port `8765` is occupied, or the app is already running in another window. Try
opening `http://127.0.0.1:8765/` first. If it does not respond, use another port:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge app --no-browser --port 8766
```

On macOS/Linux, replace the command prefix with `./.venv/bin/python`, then open
`http://127.0.0.1:8766/`.

### `gio: Operation not supported`

This usually means only that the system could not open a browser automatically.
Start with `--no-browser` and open the printed address manually.

### Spotify callback port failure or Redirect URI mismatch

Confirm that the Developer Dashboard contains exactly
`http://127.0.0.1:8888/callback`. Close any other program using port `8888` and
try again.

### Spotify returns 403, 429, or a quota pause

Confirm that the app owner still has Premium and that the signed-in user may use
the development-mode app. A 429 can be a short rate limit or exhausted
development-mode quota. Planning progress is saved; retry the same command
later.

### The NetEase playlist cannot be read

Open the playlist in a signed-out or private browser window first. Private,
owner-only, and login-required playlists are unsupported by the default source.
Changes to the public endpoints may also require a project update.

## Privacy and security

- `.state/spotify-token.json` contains a Spotify login token. Do not share it or
  commit it to Git.
- `reports` contains playlist names, track metadata, and match candidates. Review
  it before uploading it anywhere.
- The program does not need a Spotify Client Secret and should not receive a
  NetEase cookie.
- The local app binds to `127.0.0.1` by default and validates a CSRF token for
  write requests.
- `.state`, `reports`, virtual environments, and build output are excluded by
  the project's `.gitignore`.

## Limitations

- Only playlist metadata is migrated, not audio, save times, comments, or
  listening history.
- The default source supports only NetEase public playlists readable without a
  login.
- Cross-catalog metadata matching cannot prove that two entries are the same
  recording; manual review remains necessary.
- Spotify has no batch search endpoint. Large playlists can take a long time and
  may reach rate or development-mode quota limits.
## Developer entry point

Regular users do not need this section. See
[docs/architecture.md](docs/architecture.md) for architecture, data flow,
invariants, and failure semantics. Offline verification commands:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```
