# MediaFlow (local)

A local video-publishing dashboard. **YouTube and Facebook uploads are real
and functional**; Instagram publishes through the same Facebook connection.
TikTok is stubbed in the UI but not wired up yet (see bottom of this file).

## What's functional

- **New Upload** — drag in a video, publish now or schedule for later,
  real upload to YouTube, Facebook, and Instagram. Scheduling now works
  identically across all three (see "How scheduling actually works"
  below) — Instagram included, even though it has no native scheduling
  of its own.
- **Dashboard** — live counts (scheduled / published / connected accounts /
  failed) and a recent-activity feed, backed by a local SQLite database
  (`mediaflow.db`, created automatically next to `server.py`).
- **Accounts** — connect/disconnect YouTube via Google login, and
  connect/disconnect Facebook (+ Instagram, if linked) by pasting in your
  Page credentials. TikTok shows as "Not set up" until wired in.
- **Scheduled** / **Published** — real lists pulled from the database. A
  background job checks every 30 seconds for anything due and actually
  publishes it then (see below); the Refresh button also triggers an
  immediate catch-up check.
- **Analytics** — YouTube, Facebook, and Instagram tabs with real data
  from each platform's API, a 7/28/90-day toggle, and a filterable
  video/post list (Top 5/10/25/All, sortable by views, watch time, likes,
  comments, or retention %). Clicking **Metrics** on any item opens a
  detail view instead of the video itself — lifetime + period stats, and
  for YouTube specifically, the actual per-second audience retention
  curve (Facebook/Instagram don't expose that via their public APIs, so
  those show the closest real equivalents instead: drop-off checkpoints
  for Facebook, reach/saves/shares for Instagram). YouTube needs the
  `yt-analytics.readonly` scope — if you connected before this feature
  existed, reconnect from Accounts to grant it (you'll see a prompt on
  the page if so).
- **Settings**, **Help & Support** — placeholders for now.

## 1. Install Python dependencies

Open a terminal in this folder and run:

```
python -m venv venv
venv\Scripts\activate        (Windows)
source venv/bin/activate     (Mac/Linux)

pip install -r requirements.txt
```

## 2. Connecting YouTube

Your Google OAuth client goes in `credentials/client_secret.json` (shared
across accounts by default — see "Multi-account support" below for the
per-account override). **Treat this folder like a password file** — don't
commit it to git or share it.

Open the app, go to **Accounts**, and click **Connect** next to YouTube —
this runs Google's OAuth flow in your browser (via `/api/connect/youtube`)
and saves a fresh token for whichever account is currently selected in the
top-right switcher, at `credentials/accounts/<account_id>/token.json`,
refresh token included, so you won't need to log in again unless you click
**Disconnect** or the token gets revoked.

The connect flow requests upload, read-only, and analytics scopes together,
so Google's consent screen will list all three — that's intentional, it
means a future Analytics page won't need yet another re-auth.

**Note:** while your Google Cloud OAuth app is in "Testing" publishing
status, only email addresses added as Test Users (OAuth consent screen →
Test users, in Google Cloud Console) can complete this flow — anyone else
gets an "hasn't completed verification" block.

## 3. Connecting Facebook + Instagram

Unlike YouTube, this is a paste-in form rather than a login button — since
you already have a Page Access Token, there's no real benefit to building
a full "Login with Facebook" OAuth flow on top of it (same access either
way — it's the token's permissions that matter, not how you got it).

Go to **Accounts** → **Facebook** → **Connect**, and fill in:

| Field | Where to get it |
|---|---|
| App ID / App Secret | Your app's dashboard at developers.facebook.com |
| Page ID | Your Facebook Page's "About" section, or Graph API Explorer |
| Page Access Token | Graph API Explorer (select your Page, request `pages_manage_posts` + `pages_read_engagement`), then exchange for a **long-lived** token so it doesn't expire every 60 days — see Meta's [access token guide](https://developers.facebook.com/docs/pages/access-tokens) |

MediaFlow validates the token against the Graph API when you click
**Save & Connect**, and stores everything for the currently-selected
account at `credentials/accounts/<account_id>/facebook.json` (same "treat
it like a password" rule applies).

**Instagram** rides on this same connection — no separate credentials. If
your Page has an Instagram **Business or Creator** account linked to it
(Page Settings → Linked Accounts), MediaFlow detects it automatically and
the Instagram card lights up too. If it doesn't show as linked, that's the
most common reason: the account has to be a Business/Creator account, and
it has to be linked to the Page specifically (not just "connected" loosely).

## 4. Multi-account support

The top-right pill is an account switcher, not a user login — there's
still just one shared app password. Each account has its own YouTube
token, Facebook/Instagram connection, scheduled/published posts, and
analytics, completely separate from every other account. Use **+ Add
account** in that dropdown to create a new one, then connect its
platforms from the Accounts page same as above.

`credentials/client_secret.json` (the Google OAuth *app* client, not a
per-user token) is shared across all accounts by default so you don't
have to re-upload it each time — drop a `client_secret.json` inside a
specific account's own folder (`credentials/accounts/<id>/`) if that
account needs its own separate Google Cloud project instead.

One real limitation that still applies regardless of scheduling: Instagram's
publishing API requires a public URL to fetch the video from — it can't
accept a direct upload. MediaFlow handles this by briefly serving the file at
`/media/<random-filename>` (no login required, since Instagram's servers
can't complete an interactive sign-in) and deleting it right after the publish finishes. The filename is
a random tempfile name, not guessable or listable, so the exposure window is
small — but it's worth knowing this happens.

## How scheduling actually works

MediaFlow does **not** use each platform's own native scheduling
(YouTube's `publishAt`, Facebook's `scheduled_publish_time`) — for two
reasons:

1. **Instagram has no native scheduling at all**, so there was no way to
   support it consistently across platforms otherwise.
2. **YouTube appears to distribute scheduled Shorts more slowly** than
   ones made public immediately — a video uploaded as private with a
   future `publishAt` seems to get less of the initial algorithmic push
   than one uploaded directly as public. Since this isn't officially
   documented behavior, treat it as an observation rather than a
   guarantee, but it's the reason this project avoids relying on it.

Instead, when you schedule something, MediaFlow holds the video file on
disk and writes a database row with no platform API calls made yet. A
background job (`_scheduler_loop` in `server.py`) checks every 30 seconds
for anything whose time has arrived, and when it finds one, runs the
exact same "publish now" call you'd get from clicking Publish Now
manually — for every platform you selected, at the same moment. The
video only ever touches YouTube/Facebook/Instagram's servers once, right
when it's supposed to go live, uploaded directly at your chosen final
privacy level (no private-then-flip-to-public step).

A few consequences of this design:
- **The video sits on your server, not the platform's, until the
  scheduled moment.** If your server goes down before then, the publish
  won't happen until it's back up and the scheduler catches up (it
  checks for overdue items on every restart and on every Dashboard/
  Scheduled-tab load, not just its 30-second tick).
- **Facebook's old 10-minute-minimum rule no longer applies** — you can
  schedule as close to "now" as you like, since MediaFlow is the one
  deciding when to call Facebook, not Facebook itself.
- **Disk space**: scheduled videos are stored in full in `uploads/` until
  they publish. If you schedule several large videos far in advance,
  make sure the server has room for all of them at once.
- **Instagram scheduling needs `PUBLIC_BASE_URL` set** (see
  `mediaflow.env.example`) — the background job has no live browser
  request to build a public URL from the way an immediate "Publish Now"
  click does, so it has to be told explicitly where the server is
  reachable from the internet. Scheduling YouTube/Facebook doesn't need
  this.

## 4. Run the app

```
uvicorn server:app --reload --port 8000
```

Then open **http://localhost:8000** in Chrome.

## 5. Using it

- Platform cards on the New Upload page light up once the status check
  finds a valid connection (happens automatically on page load).
- Only platforms marked "Connected" can be selected.
- Videos upload as **private** by default on YouTube (safer default while
  testing). Once you're happy it's working, change the default in the
  privacy dropdown or in `server.py`.

## Adding TikTok

TikTok's Content Posting API genuinely requires a real OAuth login flow —
unlike Facebook, there's no "just paste an API key" option, since posting
on someone's behalf always requires their explicit per-account
authorization. To wire it in:

1. Register an app at developers.tiktok.com and request Content Posting
   API access.
2. Note that unaudited apps can only post as **private drafts** until
   TikTok approves your app — public posting isn't available until then.

Let me know when you have a Client Key/Secret and I'll add the OAuth
connect flow (same pattern as YouTube's) plus the matching upload function.

---

## Running this on a VM (public IP, no domain)

The app now has a real login (its own Sign In / Sign Up pages, not a
browser popup) — required once it's reachable from the internet, or
anyone with the URL could sign up and publish to your channel.

### 1. Copy the app to the VM

From your machine:
```
scp -r mediaflow-app your_user@YOUR_VM_IP:~/mediaflow-app
```
(or `git clone` / `rsync`, whatever you normally use)

### 2. On the VM: install dependencies

```
ssh your_user@YOUR_VM_IP
cd ~/mediaflow-app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. First login

MediaFlow has real sign-up/login now — anyone who can reach the app can
create their own account from the Sign Up page, and everyone who's signed
up shares the same dashboard and data (there's no per-user data
separation, just per-user credentials).

For a brand-new install with no accounts yet, you can optionally seed one
via env vars so you're not stuck if you'd rather not use the Sign Up page
first — otherwise a one-time random-password account is created for you
and printed to the server log on first boot:

```
export APP_USERNAME=admin
export APP_PASSWORD="pick something long and random"
export PORT=8000
python server.py
```

These two vars only matter once, before any account exists — safe to
unset afterward. Visit `http://YOUR_VM_IP:8000`, which redirects to a
custom Sign In / Sign Up page (no more browser popup).

Because sign-up is open to anyone who reaches the URL, treat the app's
address itself as the access control — see "Open the port" and "A note
on HTTPS" below.

### 4. Open the port in your VM's firewall

Depends on your provider (AWS security group, GCP firewall rule, or on the
VM itself):
```
sudo ufw allow 8000/tcp
```
If your provider's console lets you restrict this to your own IP address
only rather than "anywhere," do that — it's meaningfully safer than relying
on the password alone.

### 5. Keep it running (systemd)

`mediaflow.service` is included — edit the `YOUR_USER` and path placeholders
inside it, then:

```
sudo cp mediaflow.service /etc/systemd/system/mediaflow.service
sudo systemctl daemon-reload
sudo systemctl enable mediaflow
sudo systemctl start mediaflow
sudo systemctl status mediaflow
```

This keeps the app running after you disconnect SSH and restarts it if it
crashes or the VM reboots.

### A note on HTTPS

Right now this serves plain HTTP — fine to get running, but your login
password and the video itself travel unencrypted between your browser and
the VM. Two ways to fix that later:
- **Get a cheap domain** and point it at the VM's IP — then I can set up
  Nginx + Let's Encrypt for a free, trusted HTTPS certificate.
- Without a domain, you can still encrypt the connection with a
  self-signed certificate, but browsers will show a security warning you
  have to click past each time.

For now, at minimum: restrict the firewall to your own IP if your VM
provider allows it, since sign-up is open to anyone who reaches the URL.
