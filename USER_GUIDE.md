# User Guide

[简体中文](USER_GUIDE.zh-CN.md)

This guide is for people who do not know programming, Git, or command-line
tools. You only need to know how to download a file, copy a command, and open a
web page. Follow every step in order.

## What you need

Prepare:

- a Windows, macOS, or Ubuntu computer;
- Python 3.11 or later;
- a Spotify Premium account;
- a publicly accessible NetEase Cloud Music playlist.

Matching a large playlist can take a long time.

[Spotify Web API](https://developer.spotify.com/documentation/web-api) currently
requires Premium. This tool does not download music. It only matches the track
information in your playlist to Spotify.

## Step 1: Download the project ZIP

1. Open the [project download page](https://github.com/JoenardoQ/Cloud-Music-to-Spotify-Migration/archive/refs/heads/main.zip).
2. Your browser downloads a ZIP archive.
3. Extract it and put the folder somewhere easy to find, such as Downloads or
   Desktop.
4. Complete every later step in this extracted project folder. You can download
   a fresh copy if the folder is damaged or accidentally changed.

## Step 2: Install Python, the environment, and the app

### Windows

1. Open the [Python downloads page for Windows](https://www.python.org/downloads/windows/)
   and install Python 3.11 or later. Select **Add python.exe to PATH** if shown.
2. Open the extracted project folder in File Explorer.
3. Select the address bar, type `cmd`, and press Enter.
4. Run these lines one at a time in the black CMD window:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
```

### macOS

1. Open the [Python downloads page for macOS](https://www.python.org/downloads/macos/)
   and install Python 3.11 or later.
2. Open Terminal, type `cd `, drag the project folder into Terminal, and press Enter.
3. Run these lines one at a time:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install .
```

### Ubuntu

1. Right-click inside the project folder and select **Open in Terminal**.
2. Run these lines one at a time:

```bash
sudo apt update && sudo apt install -y python3 python3-venv
python3 -m venv .venv
./.venv/bin/python -m pip install .
```

If the computer asks for a password, enter your login password and press Enter.
It is normal for no characters to appear while you type the password.

An output line beginning with `Successfully installed cloud-playlist-bridge-`
means installation worked. A pip upgrade notice is harmless and can be ignored.

## Step 3: Get a Spotify Client ID

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Sign in with your Spotify Premium account.
3. Select **Create app**.
4. For App name, you can enter `Cloud Playlist Bridge`. For Description, you
   can enter `Personal playlist migration`.
5. [Spotify requires](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)
   this exact Redirect URI:

   ```text
   http://127.0.0.1:8888/callback
   ```

6. Select **Web API**, accept the terms, and create or save the app.
7. Open the app settings, find **Client ID**, and copy it.

Do not copy, enter, or share the Client Secret. This project does not need it.
Spotify requires an exact Redirect URI match. Do not replace `127.0.0.1` with
`localhost`, and do not omit `/callback`.

## Step 4: Start the app

Return to the terminal you kept open and copy the command for your system.

### Windows

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge app --no-browser
```

### macOS or Ubuntu

```bash
./.venv/bin/python -m cloud_playlist_bridge app --no-browser
```

`Cloud Playlist Bridge App: http://127.0.0.1:8765/` means the app started.
Keep the terminal open, then select or enter this address in your browser:

[http://127.0.0.1:8765/](http://127.0.0.1:8765/)

## Step 5: Move the playlist

The app currently displays Chinese labels. `分析歌单` means **Analyze playlist**,
and `创建 Spotify 歌单` means **Create Spotify playlist**.

1. Paste the NetEase playlist share link or playlist ID into the NetEase field.
2. Paste the Client ID from Step 3 into the Spotify Client ID field.
3. Leave the `api-enhanced` address empty for now.
4. Select `分析歌单`.
5. When the Spotify authorization page opens, sign in and approve access.
6. Wait for analysis to finish, then review the matched and skipped counts.
7. Select `创建 Spotify 歌单` only after you accept the result.

`分析歌单` does not create a Spotify playlist. Only the final create button writes
to Spotify. Uncertain matches are skipped and saved in a manual CSV instead of
silently adding the wrong track.

## How to stop and start again

Return to the terminal running the app and press `Ctrl+C`. You can close the
terminal after it reports that the app stopped.

You do not need to install again next time. Open a terminal in the same project
folder and repeat Step 4.

## Common errors

### `Address already in use`

Another program is using port `8765`, or the app is already running in another
terminal. First try opening `http://127.0.0.1:8765/`. If it does not open, use a
different port.

Windows:

```bat
.venv\Scripts\python.exe -m cloud_playlist_bridge app --no-browser --port 8766
```

macOS or Ubuntu:

```bash
./.venv/bin/python -m cloud_playlist_bridge app --no-browser --port 8766
```

Then open `http://127.0.0.1:8766/`.

### `gio: Operation not supported`

This only means the system could not open the browser automatically. The app is
usually running. Open the address printed in the terminal manually.

### `py`, `python3`, or `python` is not found

Python was not installed correctly. Repeat Step 2. Close the terminal after
installation, then open it again.

### Spotify reports a Redirect URI mismatch

Return to the Spotify Developer Dashboard and make sure the address is exactly
`http://127.0.0.1:8888/callback`. Save the setting and try again.

### The NetEase playlist cannot be read

Check whether the playlist opens in a signed-out browser window. Private,
owner-only, or login-required playlists cannot be read by the default method.

## Privacy reminder

The `.state` folder contains the Spotify login token. The `reports` folder
contains playlist reports. Do not send these folders to other people or upload
them to a public repository or cloud drive. If you stop using the tool, preserve
any reports you need, stop the app, and then delete the project folder.
