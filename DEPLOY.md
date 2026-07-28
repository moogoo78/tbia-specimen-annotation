# Deployment (Docker, single EC2 instance)

Production deployment of the TBIA annotation platform onto **one** AWS EC2
instance using `docker-compose.prod.yml`. The app is **single-node by design**:
both data stores are embedded local files (DuckDB read-only ~700 MB; SQLite
read-write), so it cannot be load-balanced across instances. For HA you'd first
migrate the SQLite annotation store to a managed database.

> Pick **either** this Docker path **or** the systemd path — not both. They both
> bind ports 80/443/8000.

## Architecture

```
:80/:443 ─> web (Caddy)  ── serves built SPA (frontend/dist), auto-TLS
                         └─ /api/* ─> backend (uvicorn, 1 worker) ── mounts ./data
                                                                     tbia.duckdb (ro)
                                                                     annotations.sqlite (rw)
```

The frontend calls a **relative `/api`** and the backend serves no static files,
so Caddy must serve the SPA and proxy `/api` on the **same origin**.

## 1. Provision the instance

- **Type:** `t4g.small` (2 vCPU / 2 GB, ARM/Graviton — cheapest viable; the
  images are multi-arch). `t4g.medium` (4 GB) for comfort.
- **Storage:** 20 GB gp3.
- **Region:** `us-west-2` is the lower-latency US region for Taiwan users;
  `ap-northeast-1` (Tokyo) is best if you'll pay ~10–25% more.
- **Elastic IP:** allocate + associate so the address survives stop/start.
- **Security group:** inbound `80` and `443` open; `22` restricted to your IP.
  Do **not** expose `8000`.
- **Domain (for TLS):** point an `A` record at the Elastic IP. Let's Encrypt
  will **not** issue certs for raw IPs or `*.compute.amazonaws.com` hostnames.

## 2. Install Docker + enable swap

```bash
# Docker engine + compose v2 plugin, from Docker's official repo.
# Works on Debian (bookworm/bullseye) and Ubuntu, arm64 or x86.
# NOTE: Debian has no `docker-compose-v2` package — use the repo below.
# (On Ubuntu only, the shortcut `apt install docker.io docker-compose-v2` also works.)
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
DISTRO=$(. /etc/os-release && echo "$ID")   # debian or ubuntu
sudo curl -fsSL "https://download.docker.com/linux/$DISTRO/gpg" -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/$DISTRO $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
| sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker
docker compose version   # verify v2

# Swap — REQUIRED on a 2 GB box (the in-image `npm run build` spikes memory)
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

## 3. Clone + place the data

```bash
git clone https://github.com/moogoo78/tbia-specimen-annotation.git
cd tbia-specimen-annotation
export APP=$PWD
mkdir -p data/duck-tmp        # DuckDB spill dir (lives in the mounted volume)
```

Build the DBs **on your laptop** (don't run the ~2 M-row ingest on the small
box) and copy them up:

```bash
# on your laptop, after `make prepare && make seed`
scp data/tbia.duckdb data/annotations.sqlite ubuntu@<elastic-ip>:$APP/data/
```

Verify on the box:

```bash
ls -lh data/tbia.duckdb data/annotations.sqlite
```

## 4. Create the secrets file (`backend/.env`)

Gitignored — **never committed**. Unlike the dev compose file, which interpolates
values from the project-root `.env`, the prod backend reads **only** this file
(`env_file: ./backend/.env`) — so ORCID's credentials must live here, not in the
root `.env`.

```bash
cat > backend/.env <<EOF
NDB_JWT_SECRET=$(openssl rand -hex 32)

# Sign-in is ORCID-only. Register a client at https://orcid.org/developer-tools,
# scope /authenticate, and set its Redirect URI to EXACTLY the value below
# (your production domain — not localhost).
ORCID_BASE=https://orcid.org
ORCID_CLIENT_ID=
ORCID_CLIENT_SECRET=
ORCID_REDIRECT_URI=https://your-domain.org/auth/orcid/callback
# Comma-separated ORCID iDs granted \`admin\` on first sign-in (see step 6).
ORCID_ADMIN_IDS=

# MUST stay false here — it is a full auth bypass outside local dev.
NDB_DEV_LOGIN=false
EOF
chmod 600 backend/.env
```

With an empty `ORCID_CLIENT_ID` the API returns **503** on `/api/auth/orcid/*`
and nobody can sign in. Optional extras (`ANTHROPIC_API_KEY` for AI
transcription, `DISCORD_WEBHOOK_URL` for review pings) go in the same file; see
`.env.example` for the full list.

> The DuckDB caps (`NDB_DUCK_THREADS`, `NDB_DUCK_MEMORY_LIMIT`,
> `NDB_DUCK_TEMP_DIR`) and the DB paths are already set in
> `docker-compose.prod.yml` and don't belong here.

## 5. Bring it up

```bash
export SITE_ADDRESS=https://your-domain.org    # or leave unset -> :80 plain HTTP
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f
```

Health check (from the box):

```bash
curl -s http://127.0.0.1/api/health
```

> Tight on RAM during `--build`? Build the images on your laptop and transfer
> them: `docker save <img> | ssh ubuntu@<ip> docker load`, then `up -d` without
> `--build`.

### TLS modes — direct vs Cloudflare

Caddy obtains TLS automatically, but **how** depends on whether a Cloudflare
proxy sits in front.

**Direct / "DNS only" (grey cloud):** nothing extra. Leave `CADDY_TLS` unset and
Caddy gets a Let's Encrypt cert for `SITE_ADDRESS`. Requires a real domain (not
a raw IP or `*.compute.amazonaws.com`) resolving to the box, with ports 80/443
reachable.

**Behind a Cloudflare proxy (orange cloud):** ACME challenges are intercepted by
Cloudflare's edge, so Caddy can't get a Let's Encrypt cert — you'd get a
Cloudflare **525 "SSL handshake failed"**. Use a Cloudflare **Origin
Certificate** instead:

1. Cloudflare dashboard → **SSL/TLS → Origin Server → Create Certificate**
   (free, 15-year). Save the two PEM blocks on the box:
   ```bash
   sudo mkdir -p /etc/caddy/certs
   sudo tee /etc/caddy/certs/cf-origin.pem >/dev/null   # paste the certificate, Ctrl-D
   sudo tee /etc/caddy/certs/cf-origin.key >/dev/null   # paste the private key, Ctrl-D
   sudo chmod 600 /etc/caddy/certs/cf-origin.key
   ```
2. Cloudflare → **SSL/TLS → Overview → set encryption mode to "Full (strict)"**.
   Do **not** use "Flexible" — it causes a redirect loop with Caddy.
3. Bring up with `CADDY_TLS` pointing at the cert (it's mounted read-only into
   the `web` container at `/etc/caddy/certs`):
   ```bash
   export SITE_ADDRESS=https://your-domain.org
   export CADDY_TLS="tls /etc/caddy/certs/cf-origin.pem /etc/caddy/certs/cf-origin.key"
   docker compose -f docker-compose.prod.yml up -d --build
   ```

Keep your security group allowing 443 (from `0.0.0.0/0`, or restrict to
[Cloudflare's IP ranges](https://www.cloudflare.com/ips/) to force traffic
through the proxy).

## 6. Sign-in and admin roles

There are **no passwords to lock down** — auth is ORCID-only and the backend
never handles a password. Two things to check instead:

**a. `NDB_DEV_LOGIN` must be false.** The `annotations.sqlite` you copied up
carries the three seeded demo rows (`curator/reviewer/admin@tbia.test`). They
have no password and no ORCID iD, so they are unreachable — *unless*
`NDB_DEV_LOGIN=true`, which exposes a password-less "sign in as <demo user>"
flow. Verify:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python -c "from app.config import settings; print('dev_login =', settings.dev_login)"
```

**b. Grant yourself `admin`.** `ORCID_ADMIN_IDS` is applied **only when the user
row is first created**, so put your iD there *before* your first sign-in;
everyone else lands on `contributor`. For an iD that has already signed in, or
to promote someone later, update the row directly:

```bash
docker compose -f docker-compose.prod.yml exec backend python - <<'PY'
from sqlalchemy import select
from app.db import SessionLocal, init_db
from app.models import User
init_db()
with SessionLocal() as db:
    for u in db.execute(select(User)).scalars():
        print(u.id, u.orcid, u.email, u.display_name, u.role)
    # Promote (uncomment and set the iD):
    # u = db.execute(select(User).where(User.orcid == "0000-0002-1825-0097")).scalar_one()
    # u.role = "admin"; db.commit()
PY
```

Roles are `contributor | reviewer | admin`. A role change takes effect without
re-issuing tokens: every request resolves the user from SQLite (the `role` claim
in the JWT is not what's enforced), so the user only needs to reload the page.

## Operations

| Task | Command |
|---|---|
| Logs | `docker compose -f docker-compose.prod.yml logs -f` |
| Restart | `docker compose -f docker-compose.prod.yml restart` |
| Update code | `git pull && docker compose -f docker-compose.prod.yml up -d --build` |
| Stop | `docker compose -f docker-compose.prod.yml down` |
| Backup state | `cp data/annotations.sqlite data/annotations.$(date +%F).sqlite` (only mutable store) |

`restart: always` brings the stack back up after a reboot (Docker starts on
boot). Back up `annotations.sqlite` regularly — a nightly cron copy to S3 is
enough; everything else (DuckDB) is regenerable from the source export.

## Updating the occurrence data

DuckDB is rebuilt from scratch by the TBIA ETL. Take the fresh export, run
`make prepare` over it on your laptop, `scp` the new `tbia.duckdb` up, then
`docker compose -f docker-compose.prod.yml restart backend`.

## Troubleshooting

- **502 from Caddy** — backend not healthy; check `logs backend`. Common cause:
  missing `data/tbia.duckdb` (the backend raises on startup).
- **TLS not issued** — `SITE_ADDRESS` must be a real domain resolving to this
  box; Let's Encrypt rejects IPs and `*.compute.amazonaws.com`.
- **Cloudflare 525 "SSL handshake failed"** — the domain is proxied (orange
  cloud), so ACME can't reach Caddy. Use a Cloudflare Origin Certificate +
  `CADDY_TLS` + "Full (strict)" mode (see *TLS modes* above), or grey-cloud the
  record to go direct.
- **Sign-in button dead / 503 from `/api/auth/orcid/config`** — `ORCID_CLIENT_ID`
  is empty in `backend/.env`. Note the prod compose does **not** read the
  project-root `.env` for these (step 4).
- **ORCID returns `redirect_uri mismatch`** — `ORCID_REDIRECT_URI` must match the
  Redirect URI registered on the ORCID client *byte for byte*, and point at the
  production domain (`https://your-domain.org/auth/orcid/callback`).
- **OOM / container killed** — confirm swap is on (`free -h`) and that only the
  Docker path is running (not also a systemd uvicorn).
- **`database is locked`** — keep the backend at `--workers 1` (already set);
  SQLite doesn't like concurrent writers.
