# Auto-Delete Posts

Automatically deletes your old social media posts, **for free**. You set the rules, for example "delete everything older
than 30 days, but keep my pinned post, anything with 100+ likes, and anything tagged `#keep`". The app then
cleans up on a schedule. It runs on your own computer, and your logins never leave it.

## Download (no install needed)

**[⬇ Get the latest version](https://github.com/Zutrak00/Auto-Delete-Post-/releases/latest)**. Pick the file for
your computer:

| Your computer | File |
|---|---|
| Windows | `AutoDeletePosts-Windows.zip` |
| Mac (Apple Silicon: M1 or newer) | `AutoDeletePosts-Mac.zip` |
| Linux | `AutoDeletePosts-Linux.tar.gz` |

1. Unzip it and double-click **AutoDeletePosts**.
2. A small window opens and the dashboard appears in your browser. Keep that window open while you use the app;
   closing it stops the app. Double-clicking again later just reopens the dashboard.
3. The app isn't signed by Apple or Microsoft, so the first launch shows a warning:
   * **Windows:** "Windows protected your PC" → **More info** → **Run anyway**.
   * **Mac:** after the warning, open **System Settings → Privacy & Security**, scroll down and click
     **Open Anyway**.
4. Connect an account. For **X** and **Instagram**, type your username, click **Open login window** and log in
   as usual. The app remembers the login.
5. Click **Run preview** to see exactly what would be deleted. Nothing is deleted until you click **Go Live**.

X and Instagram need **Google Chrome or Microsoft Edge** on the computer. Windows always has Edge. If neither is
found, the app downloads a browser once (about 150 MB).

Your settings are saved in `%APPDATA%\AutoDeletePosts` on Windows, `~/Library/Application Support/AutoDeletePosts`
on Mac and `~/.local/share/autodeleteposts` on Linux.

## Supported networks

| Network | What gets deleted | Notes |
|---|---|---|
| **X (Twitter)** | Posts, replies, reposts | Free. Log in once in a browser window. Import your free X archive to reach posts older than the latest ~3,200. |
| **Instagram** | Posts and reels | Free. Log in once in a browser window. Deletes at most 30 posts per run, about 25 seconds apart. |
| **Bluesky** | Posts, replies, reposts | Free. Uses an app password. |
| **Mastodon** (any server) | Posts, replies, boosts | Free. |
| **Reddit** | Posts and comments | Free. Can overwrite comments with `[deleted]` before deleting them, so archive sites keep nothing. |
| **Threads** | Posts and replies | Needs a Meta developer app with the `threads_delete` permission. Meta caps it at 100 deletes per day. |
| **Tumblr** | Posts and reblogs | Free. Needs a Tumblr app plus a token from the Tumblr API console. |
| **Facebook Pages** | Page posts | Pages you manage only, not personal profiles. Needs a Meta developer app. |

**About X and Instagram:** neither offers a free way for apps to delete posts, so this app does it the way the
free tools do. It opens a normal browser with your saved login and clicks Delete for you, slowly. Automating either
site is against its rules. These tools are widely used, but there's a small risk of a temporary account lock. If X
or Instagram changes its website, the app may need an update.

**Not supported yet:** Facebook personal profiles, TikTok and LinkedIn. The dashboard shows how to bulk-delete on
each one by hand.

## Safety first

* **New accounts start in Preview mode.** A preview lists exactly which posts would be deleted and why each of
  the others is kept. Nothing is deleted until you press **Go Live** for that account.
* **There is a per-run cap** (default 100) so a rule typo can't wipe everything at once.
* **Deletion is permanent.** Download your archive from each network first if you might want your posts later.
* Your logins (tokens and the X/Instagram browser session) are stored only on your computer (see the folders above, or `data/autodelete.db` when
  running from source). Keep that file private. Its permissions are set to owner-only.

## Run from source (if you have Python)

If the download above doesn't suit you (for example on an Intel Mac):

1. Install **Python 3.10 or newer** from https://www.python.org/downloads/. On Windows, tick
   *"Add python.exe to PATH"* during the install.
2. Download this project: on GitHub click **Code → Download ZIP** and unzip it.
3. Double-click the launcher for your computer:
   * **Windows:** `start.bat`
   * **Mac:** `start.command` (the first time, right-click it → **Open** to get past the security prompt)
   * **Linux:** run `./start.sh` in a terminal

The first launch takes about a minute to set up. After that, the dashboard opens in your browser at
http://127.0.0.1:8080. Keep the window open while you want the schedule to run. Close it to stop.

## Using the dashboard

Click **+ Bluesky** (or another network) and follow the instructions on the page to get your login token. Then:

1. Set your rules and click **Connect & preview**.
2. Click **Run preview** and check the "Would delete" list.
3. If it looks right, go back to **Accounts** and click **Go Live**.
4. Click **Delete now**, or let the schedule handle it. By default it runs every 24 hours while the app is
   running; change this under **Schedule**.

## Manual install (developers)

```bash
git clone https://github.com/zutrak00/auto-delete-post-.git
cd auto-delete-post-
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m autodelete web --open
```

To reach the dashboard from another device, set a password and listen on all interfaces. Use HTTPS
(a reverse proxy) if this is reachable from the internet:

```bash
AUTODELETE_PASSWORD='choose-a-strong-one' python -m autodelete web --host 0.0.0.0
```

## Run it 24/7 on a server (Docker)

The schedule only runs while the app is running. To keep it going on a home server or VPS, use Docker. X and
Instagram need the desktop app, because logging in requires a browser window.

```bash
echo "AUTODELETE_PASSWORD=choose-a-strong-one" > .env
docker compose up -d --build
```

The dashboard is then at http://127.0.0.1:8080 on that machine, behind the password. Accounts and history are
saved in `./data`. The container only accepts connections from the machine itself. To reach it from elsewhere,
put a reverse proxy with HTTPS in front (for example Caddy or nginx), or use an SSH tunnel:
`ssh -L 8080:127.0.0.1:8080 you@server`.

## Run it without keeping the dashboard open

Set up accounts in the dashboard once, then let your operating system's scheduler call the command line:

```bash
python -m autodelete list              # show accounts and their IDs
python -m autodelete run --preview     # dry run for every account
python -m autodelete run               # real run (only accounts switched to Live delete anything)
python -m autodelete run --account 2   # one account only
```

Example cron entry (Linux/macOS, `crontab -e`) that runs every night at 3am:

```
0 3 * * * cd /path/to/auto-delete-post- && .venv/bin/python -m autodelete run >> data/cron.log 2>&1
```

On Windows, use Task Scheduler to run `.venv\Scripts\python.exe -m autodelete run` with the project folder as
"Start in".

## Getting your login tokens

The dashboard shows these steps next to each form.

* **Bluesky:** Settings → Privacy and security → App passwords → Add. Use that, never your real password.
* **Mastodon:** type your server (e.g. `mastodon.social`) and click **Log in with Mastodon**. To paste a token
  instead: Preferences → Development → New application, tick `read:accounts`, `read:statuses` and
  `write:statuses`, then copy *Your access token*.
* **Reddit:** https://www.reddit.com/prefs/apps → *create another app* → type **script**, redirect URI
  `http://localhost:8080`. Copy the client ID and secret. Scheduled runs work best on an account without 2FA.
* **X and Instagram:** nothing to set up. Enter your username, click **Open login window** and log in. For X's
  older posts, request your archive on X (*Settings → Your account → Download an archive of your data*), then
  choose the .zip on the account's **Log in / archive** page.
* **Tumblr:** register an app at https://www.tumblr.com/oauth/apps (callback URL can be `http://localhost:8080`),
  then open https://api.tumblr.com/console, enter the app's keys, allow access and click *Show keys*.
* **Facebook Page:** in the Graph API Explorer at https://developers.facebook.com, select your Page and grant
  `pages_show_list`, `pages_read_engagement` and `pages_manage_posts`. Exchange the token for a long-lived one,
  then call `/me/accounts`. The Page token it returns doesn't expire.
* **Threads:** https://developers.facebook.com → create an app with the Threads use case and the permissions
  `threads_basic`, `threads_read_replies` and `threads_delete`. Add yourself as a tester and create a long-lived
  token. The app refreshes the token on every run so it doesn't expire.

## Rules reference

| Rule | Meaning |
|---|---|
| Delete posts older than N days | Only posts at least this old are candidates. `0` means everything. |
| Include replies / reposts | Untick to leave replies or reposts alone. |
| Keep pinned post | Never delete the post pinned to your profile. |
| Keep posts with at least N likes | Spares your popular posts. Threads doesn't report likes, so this has no effect there. |
| Keep posts containing… | Comma-separated words or hashtags, case-insensitive. Default `#keep`. |
| Never delete these IDs | Exact post IDs, copied from the preview table. |
| Maximum deletions per run | Safety cap. Leftover posts are handled on the next run. |

## Publishing a new version (maintainer)

On GitHub, open **Actions → release → Run workflow** and type the new version (e.g. `v1.0.1`). Pushing a tag such
as `v1.0.1` does the same. GitHub Actions tests the code, builds the Windows, Mac and Linux apps and attaches them
to a new release.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

The code lives in `autodelete/`. Each network is one file in `autodelete/providers/`. To add a network, subclass
`Provider`, implement `login`, `iter_posts` and `delete`, and register it in `providers/__init__.py`.
