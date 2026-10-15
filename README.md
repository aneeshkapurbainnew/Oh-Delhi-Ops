# Oh Delhi Ops

Replaces `October2026InventorySheet.xlsx`. It covers:

- **Daily orders:** chefs enter tomorrow's needs, orders go to vendor WhatsApp groups (an item can be split across vendors), and the store records what arrived and what each station got, with pending alerts.
- **Stock:** prices, purchases with bill photos, station issues, cooked-food wastage, any-day audits, the month-end summary, and min/par ordering.
- **Money:** sales and channel costs, expenses, the P&L with PDF export, and reviews.
- **Owner view:** a dashboard pulling it all together.

**Stack:** React (Vite) + FastAPI + Postgres. Login is built into the app, and bill photos are stored on the server. Everything runs on **one AWS Lightsail server in Mumbai** with Docker Compose: no Supabase or other third-party backend.

| Doc | What's in it |
|---|---|
| `PLAN.md` | Phases, sheet → screen map, every calculation rule |
| `CHANGELOG.md` | What changed in each version |
| `CONTRIBUTING.md` | How to make changes, release versions and update the server |

```
backend/     FastAPI app, Alembic migrations, tests, seed template from the workbook
frontend/    React app (served by Caddy in production)
deploy/      docker-compose.yml, .env.example, backup.sh, update.sh
.github/     CI: tests + builds on every push
VERSION      current version (shown at the bottom of the app menu)
```

---

## 1. Test it on your laptop (Docker Desktop)

1. Install **Docker Desktop**, open it, and wait for "Engine running".
2. Open a terminal in `deploy/` and create the settings file: `cp .env.example .env` (Windows: `copy .env.example .env`).
3. Edit `.env` so it contains:
   ```
   DOMAIN=:80
   COOKIE_SECURE=false
   POSTGRES_PASSWORD=localtest123
   APP_SECRET=any-long-random-text-just-for-testing-1234567890
   ```
4. Start everything, load your template, and create your login:
   ```bash
   docker compose up -d --build
   docker compose exec api python -m app.seed.load --price-date 2026-10-01
   docker compose exec api python -m app.users create you@ohdelhi.in "Aneesh"   # you type the password (hidden)
   ```
5. Open **http://localhost**.
6. When you're done: `docker compose down` stops it and keeps the data; `docker compose down -v` stops it and **wipes** it.

If port 80 is busy, change `"80:80"` to `"8080:80"` in `docker-compose.yml` and open http://localhost:8080.

## 2. Put it on GitHub (once)

1. On github.com, create a **private** repo called `ohdelhi-ops`. Leave it empty: no README and no .gitignore.
2. In this folder, which is already a git repository with version v1.1.0 tagged, run:
   ```bash
   git remote add origin https://github.com/<you>/ohdelhi-ops.git
   git push -u origin main --tags
   ```
3. Open the repo's **Actions** tab. The `ci` workflow runs the tests and builds; a green tick means this version is good.

## 3. Deploy on AWS Lightsail (once)

1. **Create the server.** In Lightsail, choose **Create instance**:
   - Region: Mumbai
   - Blueprint: OS Only → Ubuntu 24.04
   - Plan: 2 GB RAM
   - Name: `ohdelhi-ops`
2. **Networking.** Create a **static IP** and attach it to the server. In the server's firewall, **add HTTPS (443)**.
3. **Backups.** Go to **Snapshots → Automatic snapshots → On**.
4. **Domain.** At your domain provider, add an **A record**: `ops` pointing at the static IP. For a trial without a domain, you can use `13-233-45-67.sslip.io` (your IP with dashes).
5. **Prepare the server.** Click **Connect using SSH** and run:
   ```bash
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker ubuntu
   ```
   Then close the terminal and click **Connect** again, so Docker works without `sudo`.
6. **Let the server read your private repo** using a read-only deploy key:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C ohdelhi-server
   printf 'Host github.com\n  IdentityFile ~/.ssh/github_deploy\n' >> ~/.ssh/config
   cat ~/.ssh/github_deploy.pub
   ```
   Copy the line it prints. On GitHub, go to the repo → **Settings → Deploy keys → Add deploy key**, paste it, and leave write access **off**.
7. **Clone and configure:**
   ```bash
   git clone git@github.com:<you>/ohdelhi-ops.git && cd ohdelhi-ops/deploy
   cp .env.example .env
   openssl rand -hex 32   # database password
   openssl rand -hex 32   # app secret
   nano .env              # DOMAIN=ops.ohdelhi.in, POSTGRES_PASSWORD=..., APP_SECRET=...
   ```
8. **Start, load data, and create your login:**
   ```bash
   docker compose up -d --build                 # first build ~5-10 min
   docker compose ps                            # db, api, web, backup all running
   docker compose exec api python -m app.seed.load --price-date 2026-10-01
   docker compose exec api python -m app.users create you@ohdelhi.in "Aneesh"
   ```
9. Open **https://ops.ohdelhi.in** and sign in.

## 4. Updating to a new version

On the server, run:
```bash
cd ~/ohdelhi-ops/deploy && ./update.sh          # latest version on main
./update.sh v1.1.0                              # a specific version (also how to roll back)
```
Database migrations run automatically. The version shows at the bottom of the app menu. See `CONTRIBUTING.md` for how versions are made.

## 5. Backups

- **Nightly, about 3 am IST:** a database dump and the bill photos go to `deploy/backups/` on the server, kept 14 days.
- **Daily:** Lightsail takes a snapshot of the whole server, stored by AWS separately from it.
- **Monthly:** copy `deploy/backups` to your laptop with `scp`.

To restore the database:
```bash
docker compose exec -T db pg_restore -U ohd -d ohd --clean --if-exists < backups/db-YYYYMMDD-HHMM.dump
```

## 6. Trial and go-live plan

| Date | What |
|---|---|
| By 19 Oct | Server live. In Setup: vendors and their **WhatsApp group names**, first-choice vendor per daily item, station logins, the 19 missing prices, and the *Eggs Tray* unit fixed (Tray → Piece, 30). |
| **20 Oct** | Do the physical audit as planned. In the app, go to **Audits → Opening count**, dated 20 Oct, and enter the counts. This is the app's starting stock. |
| 21–30 Oct | **Trial: run the app alongside the sheets.** Chefs enter orders, the store receives and gives, and you enter purchases, sales and wastage. Each evening, compare station costs and stock with the sheets. Report anything wrong as a GitHub Issue (template provided). |
| **31 Oct** | Month-end count in the app (**Audits → Month-end audit**). |
| **1 Nov** | **Go live**: stop the sheets. November's opening stock is the 31 Oct count. Keep October's P&L from the sheets, since the app only has 20–31 Oct. |

If the trial data is messy, you don't need to wipe anything. An **Opening count** on 31 Oct restarts the stock chain from that count, and earlier entries stay as history.

## 7. Daily routine

| When | Who | Where |
|---|---|---|
| Evening, until ~12 am | Each chef | Kitchen screen → **Order for tomorrow** |
| Night | Manager | **Daily orders → Plan and send.** Check totals vs stock, **Split** an item across vendors if needed, then **Send on WhatsApp (pick group)**. |
| Morning | Store | **Receive from vendors** (shortfalls flagged; this becomes the purchase bill), then **Give to stations** (this becomes station issues) |
| Any time | Manager / owner | **Pending** tab, dashboard, red count in the menu |

**Sending to groups.** WhatsApp links can't open a particular group. On a phone, the share sheet opens: tap WhatsApp, then the group. On a laptop, WhatsApp opens with the message ready: pick the group shown on the order card. The message is also copied, in case you need to paste it.

**Splitting.** Click **Split** on an item to order part of it from another vendor. Next time that item is ordered, the plan starts with the same vendors in the same proportion.

## 8. Development without Docker

You need Postgres running locally.
```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env    # DATABASE_URL to your local Postgres, COOKIE_SECURE=false, STORAGE_BACKEND=local
alembic upgrade head && python -m app.seed.load && python -m app.users create you@example.com "You"
uvicorn app.main:app --reload --port 8000
cd ../frontend && npm install && npm run dev        # http://localhost:5173
```
Run the tests with `TEST_DATABASE_URL=postgresql+psycopg://ohd:ohd@localhost:5432/ohd_test pytest -q` from `backend/`. They need a throwaway database.
