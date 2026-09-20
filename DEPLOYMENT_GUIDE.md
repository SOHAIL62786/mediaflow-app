# Deploying MediaFlow to your VM — full guide

This walks through putting the app on your Linux VM, running it 24/7 behind
Nginx, and keeping it reasonably secure with only an IP address (no domain).

Assumes a Debian/Ubuntu-based VM. If you're on something else (CentOS,
Rocky, etc.) the package manager commands differ (`dnf`/`yum` instead of
`apt`) — tell me your distro and I'll adjust these.

---

## 0. What you'll end up with

```
Internet ──► Nginx (port 80) ──► Uvicorn/FastAPI (port 8000, localhost only)
                                        │
                                        └──► YouTube API
```

Nginx is the only thing exposed to the internet. It forwards requests to
your app, which only listens on localhost — so the app itself is never
directly reachable, only through Nginx. This also gives you a normal port
80 URL instead of `http://IP:8000`.

---

## 1. Connect to your VM

```bash
ssh your_user@YOUR_VM_IP
```

## 2. Update the system and install what you need

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip nginx ufw unzip ffmpeg
```

`ffmpeg` is optional but recommended — MediaFlow uses it to automatically
re-encode and retry a video Instagram rejects during its own processing
step (see README.md's "How the Instagram re-encode fallback works").
Instagram publishing still works fine without it, just without that
automatic retry.

## 3. Copy the app onto the VM

From your **local machine** (not the VM), in a terminal where the
`mediaflow-app.zip` file is:

```bash
scp mediaflow-app.zip your_user@YOUR_VM_IP:~/
```

Back on the **VM**:

```bash
cd ~
unzip mediaflow-app.zip -d mediaflow-app
cd mediaflow-app
ls
```

You should see `server.py`, `static/`, `credentials/`, `requirements.txt`,
`mediaflow.service`, `mediaflow.nginx.conf`, `mediaflow.env.example`.

## 4. Set up the Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 5. Lock down the credentials folder

Your `credentials/` folder has your Google OAuth secret and refresh token
in it. Restrict it to your own user:

```bash
chmod 700 credentials
chmod 600 credentials/*.json
```

## 6. Seed a first account (optional)

MediaFlow has real sign-up/login — once the app is running, anyone who
reaches it can create their own account from the Sign Up page, and
everyone who signs up shares the same dashboard and data.

If you'd rather have a ready-to-use login before your first visit
(instead of using Sign Up), copy the example env file and edit it:

```bash
cp mediaflow.env.example mediaflow.env
nano mediaflow.env
```

Change `APP_PASSWORD` to something long and random (a password manager's
generator is fine). Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano).
This only takes effect once, before any account exists — safe to remove
afterward.

Then lock that file down too, since it holds a password in plain text:

```bash
chmod 600 mediaflow.env
```

## 7. Test it manually before making it a service

```bash
python server.py
```

You should see Uvicorn start on `0.0.0.0:8000`. In another terminal on the
VM, sanity-check it responds:

```bash
curl -u admin:YOUR_PASSWORD http://localhost:8000/api/status
```

You should get back JSON with your YouTube connection status. If that
works, stop the server with `Ctrl+C` — you're about to hand it off to
systemd instead of running it in a terminal.

## 8. Set it up as a systemd service (so it runs 24/7)

Edit the placeholders in `mediaflow.service` first:

```bash
nano mediaflow.service
```

Replace every `YOUR_USER` with your actual VM username (check with
`whoami` if unsure), and confirm the paths match where you unzipped the
app (`/home/YOUR_USER/mediaflow-app`).

Install and start it:

```bash
sudo cp mediaflow.service /etc/systemd/system/mediaflow.service
sudo systemctl daemon-reload
sudo systemctl enable mediaflow
sudo systemctl start mediaflow
sudo systemctl status mediaflow
```

`status` should show `active (running)`. If it doesn't, jump to
Troubleshooting below.

Useful commands going forward:
```bash
sudo systemctl restart mediaflow     # after you change server.py
sudo journalctl -u mediaflow -f      # live logs
sudo journalctl -u mediaflow -n 100  # last 100 log lines
```

## 9. Set up Nginx as the reverse proxy

```bash
sudo cp mediaflow.nginx.conf /etc/nginx/sites-available/mediaflow
sudo ln -s /etc/nginx/sites-available/mediaflow /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
```

`nginx -t` should say the config is okay. Then:

```bash
sudo systemctl restart nginx
```

## 10. Configure the firewall

Allow SSH (so you don't lock yourself out), HTTP, and nothing else. Notably,
**don't** open port 8000 — Nginx is the only public entry point now.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw enable
sudo ufw status
```

If your VM provider also has its own firewall/security-group settings
(AWS, GCP, Azure, DigitalOcean, etc.), make sure port 80 is allowed there
too — `ufw` alone isn't enough on most cloud providers, since they filter
traffic before it reaches the VM's own firewall.

If your provider lets you restrict inbound rules to a specific IP (your
home/office IP) instead of "anywhere," that's a meaningful extra layer —
worth doing if you don't need access from random locations.

## 11. Test it from your own computer

Open a browser and go to:

```
http://YOUR_VM_IP
```

You should get a login prompt (username/password from `mediaflow.env`),
then the dashboard, with YouTube showing as connected.

---

## Keeping it updated

When I send you an updated `server.py` or `static/index.html`:

```bash
# from your local machine
scp server.py your_user@YOUR_VM_IP:~/mediaflow-app/
scp static/index.html your_user@YOUR_VM_IP:~/mediaflow-app/static/

# on the VM
sudo systemctl restart mediaflow
```

## Backups worth keeping

- `credentials/accounts/<id>/token.json` for each connected account — if
  one is lost and its refresh token stops working, you'll need to redo the
  Google OAuth flow from scratch for that account. Back up the whole
  `credentials/accounts/` folder to catch every account at once.
- `mediaflow.env` — your login password.

Keep a copy of both somewhere safe (password manager, encrypted backup) —
not in plain email or chat.

---

## Troubleshooting

**`systemctl status mediaflow` shows "failed"**
Run `sudo journalctl -u mediaflow -n 50` and read the actual error at the
bottom. Common causes:
- Wrong paths/username left as `YOUR_USER` in `mediaflow.service`
- `venv` not created in the exact path the service file points to
- `mediaflow.env` missing or has a typo in a variable name

**Browser hangs or times out at `http://YOUR_VM_IP`**
- Check `sudo ufw status` — is port 80 allowed?
- Check your cloud provider's firewall/security group separately from ufw
- Check Nginx is actually running: `sudo systemctl status nginx`

**Login prompt works but then "502 Bad Gateway"**
Nginx is up but can't reach the app. Check the app itself is running:
```bash
sudo systemctl status mediaflow
curl http://localhost:8000/api/status
```

**Upload fails on large videos**
Check `client_max_body_size` in `mediaflow.nginx.conf` (currently set to
2G) — raise it if you're uploading bigger files, then
`sudo nginx -t && sudo systemctl restart nginx`.

**"401 Unauthorized" from the browser repeatedly**
Double-check `mediaflow.env` has the password you're typing, and that you
restarted the service after changing it (`sudo systemctl restart
mediaflow`).

---

## What's still HTTP, not HTTPS

This guide gets you a working, always-on setup over plain HTTP. Your
password and video data are unencrypted in transit. It's a reasonable
starting point for a personal tool, but if you get a domain later, tell me
and I'll extend this with Let's Encrypt for free, trusted HTTPS — it's a
straightforward addition to the Nginx config you already have.
