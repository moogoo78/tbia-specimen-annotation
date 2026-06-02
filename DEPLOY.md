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
                                                                     occurrences.duckdb (ro)
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
# on your laptop, after `make ingest && make seed`
scp data/occurrences.duckdb data/annotations.sqlite ubuntu@<elastic-ip>:$APP/data/
```

Verify on the box:

```bash
ls -lh data/occurrences.duckdb data/annotations.sqlite
```

## 4. Create the secrets file (`backend/.env`)

Gitignored — **never committed**. Generate a real JWT secret:

```bash
cat > backend/.env <<EOF
NDB_JWT_SECRET=$(openssl rand -hex 32)
EOF
chmod 600 backend/.env
```

> The DuckDB caps (`NDB_DUCK_THREADS`, `NDB_DUCK_MEMORY_LIMIT`,
> `NDB_DUCK_TEMP_DIR`) and the DB paths are already set in
> `docker-compose.prod.yml`; only the secret needs to live here.

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

## 6. Lock down the public demo accounts (required)

The seeded `demo1234` users (`admin@tbia.test`, etc.) are public in this repo.
Reset their passwords in the running stack:

```bash
docker compose -f docker-compose.prod.yml exec backend python - <<'PY'
from app.db import SessionLocal, init_db
from app.auth import hash_password
from app.models import User
from sqlalchemy import select
init_db()
with SessionLocal() as db:
    for email in ("admin@tbia.test", "reviewer@tbia.test", "curator@tbia.test"):
        u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if u:
            u.pw_hash = hash_password("CHANGE-ME-strong-unique-per-user")
    db.commit()
print("passwords reset")
PY
```

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

DuckDB is rebuilt from scratch by ingest. Re-run `make ingest` on your laptop,
`scp` the new `occurrences.duckdb` up, then
`docker compose -f docker-compose.prod.yml restart backend`.

## Troubleshooting

- **502 from Caddy** — backend not healthy; check `logs backend`. Common cause:
  missing `data/occurrences.duckdb` (the backend raises on startup).
- **TLS not issued** — `SITE_ADDRESS` must be a real domain resolving to this
  box; Let's Encrypt rejects IPs and `*.compute.amazonaws.com`.
- **OOM / container killed** — confirm swap is on (`free -h`) and that only the
  Docker path is running (not also a systemd uvicorn).
- **`database is locked`** — keep the backend at `--workers 1` (already set);
  SQLite doesn't like concurrent writers.
