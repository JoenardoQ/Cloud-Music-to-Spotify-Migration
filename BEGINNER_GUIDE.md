# Piglet's Foolproof Guide

[简体中文](https://github.com/JoenardoQ/Cloud-Music-to-Spotify-Migration/blob/main/小猪专供傻瓜式教学.md)

This guide is for first-time Cloud Playlist Bridge users. Its goal is to move
your own NetEase Cloud Music playlist to Spotify without experimenting inside
the primary development checkout.

## Remember three things

1. Install and run in a separate lab directory, not the checkout used to
   maintain the source code.
2. `plan` only analyzes and creates a plan. Only `apply`, or **Create Spotify
   playlist** in the app, writes to Spotify.
3. Never share `.state/spotify-token.json`, credentials other than the Spotify
   Client ID, or cookies. This project does not need a Spotify Client Secret.

## Step 1: Prepare Spotify

1. Confirm that your Spotify account meets the current Developer app
   requirements.
2. Create a Spotify Developer app with Web API enabled.
3. Add this Redirect URI exactly:

   ```text
   http://127.0.0.1:8888/callback
   ```

4. Copy the Client ID. Do not create, paste, or commit a Client Secret.

## Step 2: Create a separate lab

The safest approach is another clone. Virtual environments, caches, and reports
created during experiments then remain outside the source-maintenance checkout.

Linux or macOS:

```bash
cd ~
git clone https://github.com/JoenardoQ/Cloud-Music-to-Spotify-Migration.git CloudPlaylistBridge-Lab
cd CloudPlaylistBridge-Lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Windows PowerShell:

```powershell
cd $HOME
git clone https://github.com/JoenardoQ/Cloud-Music-to-Spotify-Migration.git CloudPlaylistBridge-Lab
cd CloudPlaylistBridge-Lab
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

`Successfully installed cloud-playlist-bridge-0.5.0` means installation
succeeded. A pip upgrade notice can be ignored; it does not affect migration.

## Step 3A: Use the graphical app

Run this in the activated virtual environment:

```bash
cloud-playlist-bridge app --no-browser
```

Keep the terminal open and visit:

[http://127.0.0.1:8765/](http://127.0.0.1:8765/)

Use the page in this order:

1. Enter the NetEase playlist ID or share URL.
2. Enter the Spotify Client ID.
3. Leave the `api-enhanced` address empty unless you already run that service.
4. Select **Analyze playlist**. Complete Spotify OAuth authorization when
   prompted the first time.
5. Review automatic matches, ambiguities, and skipped tracks.
6. Select **Create Spotify playlist** only after accepting the result. This is
   the step that writes to Spotify.

The terminal must remain running. Return to it and press `Ctrl+C` to stop the
app.

## Step 3B: Use only the command line

Run the two-stage CLI directly if you do not want the app page.

On Linux or macOS, create the plan first:

```bash
./.venv/bin/python -m cloud_playlist_bridge plan 'https://music.163.com/playlist?id=123456789' --spotify-client-id YOUR_CLIENT_ID
```

On Windows Command Prompt or PowerShell, create the plan first:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge plan "https://music.163.com/playlist?id=123456789" --spotify-client-id YOUR_CLIENT_ID
```

The command creates these files under `reports/`:

- `*.plan.json`: the verified, fixed execution plan;
- `*.csv`: the complete track audit report;
- `*.manual.csv`: tracks that need manual handling.

Inspect the reports before applying the plan.

Linux or macOS:

```bash
./.venv/bin/python -m cloud_playlist_bridge apply reports/NAME.plan.json --spotify-client-id YOUR_CLIENT_ID --private
```

Windows Command Prompt or PowerShell:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge apply reports\NAME.plan.json --spotify-client-id YOUR_CLIENT_ID --private
```

Replace `NAME` with the actual filename. Removing `--private` creates a public
playlist.

## Files that belong only to local experiments

The following must not enter a release commit. The project `.gitignore` already
excludes them:

- `.venv/`: the local Python virtual environment;
- `.state/`: checkpoints and the Spotify token;
- `reports/`: migration plans and CSV reports;
- `dist/`, `build/`, and `*.egg-info/`: build output and installation metadata;
- `__pycache__/` and `*.pyc`: Python bytecode caches.

Run this before and after work in the maintenance repository:

```bash
git status --short
git status --ignored --short
```

No output from the first command means tracked source files are unchanged. Items
shown with `!!` by the second command are ignored local files and ordinary
`git add` will not include them. They can still contain private data and must
not be shared.

## Common problems

### `Address already in use`

Another process holds port `8765`. First check whether the app is already
running, or use another port:

```bash
cloud-playlist-bridge app --no-browser --port 8766
```

Then open `http://127.0.0.1:8766/`. The app page port and Spotify OAuth callback
port `8888` are different ports.

### `gio: Operation not supported`

The app is running, but WSL or headless Linux could not open a browser. Use
`--no-browser`, then open the address printed in the terminal manually.

### `cloud-playlist-bridge: command not found`

The virtual environment is inactive, or this terminal uses another environment.
Bypass the generated command and invoke the module directly:

```bash
./.venv/bin/python -m cloud_playlist_bridge --help
```

On Windows:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge --help
```

### Both `(.venv)` and `(base)` are visible

The Python virtual environment and Conda base prompts are both active. This is
usually harmless. Confirm that the interpreter belongs to this project's
`.venv`:

```bash
python -c "import sys; print(sys.executable)"
```

### Spotify reports a Redirect URI mismatch

The Developer Dashboard value must match the command character for character:
`http://127.0.0.1:8888/callback`.

### You want to discard the lab

First decide whether to preserve migration reports and the manual list, then
stop the app. Delete only the dedicated `CloudPlaylistBridge-Lab` directory.
Never run a recursive delete against a home directory, workspace root, or any
path whose identity is uncertain.

## Final check

Before a real migration, confirm that:

- the current directory is the separate `CloudPlaylistBridge-Lab`;
- the Spotify Redirect URI is registered;
- the Client ID is correct and no Client Secret is used;
- you ran `plan` or selected **Analyze playlist** first;
- you inspected skipped and ambiguous tracks;
- you run `apply` or select the create button only after accepting the result.
