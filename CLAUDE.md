# CLAUDE.md: context for Claude Code

## What this is
**Oh Delhi Ops**: the operations app for Oh Delhi (a fusion kitchen in Bangalore). It replaces a 27-sheet Excel workbook covering inventory, prices, purchases, station issues, wastage, audits, daily vendor ordering, sales/channel costs, expenses, P&L, and reviews.

- **Owner/maintainer:** Aneesh, a software engineer who runs ops and tech for the restaurant. Write for an engineer, but the app's users are chefs, store staff and managers: keep UI copy plain, short and non-technical.
- **Status:** v1.2.0. Trial from 20 Oct 2026 (opening count = the 20 Oct physical audit), running alongside the sheets until the 31 Oct month-end audit. **Go-live 1 Nov 2026.** Stability over features until then.
- **Future direction:** possibly a subscription product for other small restaurants (see Roadmap). Don't take shortcuts that make multi-restaurant support harder (always scope by `outlet_id`).

Read `PLAN.md` for the full calculation rules and the sheet → screen mapping. `README.md` covers running and deploying. `CONTRIBUTING.md` covers versions and releases.

## Stack and layout
- **Backend:** FastAPI + SQLAlchemy 2 + Alembic + Postgres 16 (psycopg 3), Python 3.12. `backend/app/`:
  - `models.py`: all tables.
  - `services/`: `pricing.py` (PriceBook: price rules), `stock.py` (audit chain, month-end, min/par, `estimated_stock`), `pnl.py` (costing, P&L, dashboard), `pdf.py` (ReportLab P&L).
  - `routers/`: setup, prices, purchases, issues (+wastage), audits (+stock), finance, reviews, reports, daily (requisitions → vendor orders → receive → distribute → pending), auth (+users).
  - `auth.py`: built-in login with scrypt hashes and an HS256 JWT in an httpOnly cookie. `token_version` bump = sign out everywhere.
  - `seed/`: `template.json` (extracted from the Oct 2026 workbook) and `load.py`.
  - `users.py`: CLI to create a user or reset a password.
- **Frontend:** Vite + React 18 (plain JSX, no TypeScript), react-router, recharts. `frontend/src/`:
  - `pages/`: one file per screen. `Kitchen.jsx` is the simplified screen for station logins (`user.station_id` set).
  - `components/ui.jsx`: shared pieces (MonthGrid, NumCell, ItemPicker, pickers, Modal, toast).
  - `lib/`: `api.js` (fetch wrapper, cookie auth), `hooks.js` (`useFetch`, `useUnsavedWarning`), `format.js` (₹ en-IN formatting, dates), `image.js` (bill photo compression).
  - `styles.css`: design tokens on `:root` (steel base, cardamom green action, turmeric = reorder/attention, chili = flags/shortage). Reuse existing classes; don't add a CSS framework.
- **Deploy:** `deploy/docker-compose.yml` runs db, api, web (Caddy serving the built frontend and proxying `/api`, automatic HTTPS) and backup (nightly `pg_dump` + photos tarball). Target: one AWS Lightsail server in Mumbai. `deploy/update.sh [tag]` updates or rolls back on the server.
- **Supabase is NOT used** (unreliable in India). The `STORAGE_BACKEND=supabase` code path in `storage.py` is legacy and off by default; don't build on it.

## Commands
```bash
# whole stack locally (Docker Desktop): deploy/.env needs DOMAIN=:80, COOKIE_SECURE=false, POSTGRES_PASSWORD, APP_SECRET
cd deploy && docker compose up -d --build && open http://localhost
docker compose exec api python -m app.seed.load --price-date 2026-10-01
docker compose exec api python -m app.users create you@example.com "Name"

# backend tests: need a local Postgres DB whose name ends in _test (conftest refuses anything else)
cd backend && TEST_DATABASE_URL=postgresql+psycopg://ohd:ohd@localhost:5432/ohd_test pytest -q

# frontend: must build cleanly
cd frontend && npm ci && npm run build

# new migration after changing models.py
cd backend && alembic revision --autogenerate -m "what changed"   # then READ the file
```
CI (`.github/workflows/ci.yml`) runs migrations on an empty DB, the backend tests, the frontend build, and both Docker builds on every push.

## Rules for changes
1. **Scope everything by outlet.** Every query on an operational table filters `outlet_id == oid` (from `Depends(outlet_id)`), and lookups by id check the row's outlet. New tables get `outlet_id = outlet_fk()`.
2. **Units matter.** Purchases and vendor orders are in **purchase units**. Issues, requisitions, wastage quantities and audit counts are in **consumption units**. Stock moved = purchase qty × `conversion_ratio`. Prices are stored **per purchase unit**; consumption price = price ÷ ratio. Mixing these is the most likely bug.
3. **Calculation changes need a hand-worked test.** `tests/test_calculations.py` and `tests/test_daily_orders.py` assert numbers worked out by hand. Change a rule → update `PLAN.md`, add or adjust a test with the expected numbers computed by hand, and note it in `CHANGELOG.md`.
4. **Migrations only go forward.** Never edit a migration that may have run on the server. Autogenerate creates FK constraints with `name=None`; give them names (see `0003_daily_ordering.py`). Check `alembic upgrade head` on an empty DB.
5. **API errors are user-facing.** `HTTPException` details are shown in the UI toast, so write them as plain instructions ("Choose a vendor for every item."), not technical errors.
6. **Keep the frontend dependency-light.** Use `useFetch` and `api` from `lib/`. Prefer extending `components/ui.jsx` over adding packages. Any list/grid screen should keep the sticky headers and the `table-wrap` pattern.
7. **Releases.** Bump `VERSION`, add a `CHANGELOG.md` entry, commit, `git tag vX.Y.Z`, `git push origin main --tags`. On the server run `./update.sh vX.Y.Z`. PATCH = fixes, MINOR = features, MAJOR = workflow or data-model changes.
8. **Never commit secrets.** `.env` files are gitignored. Don't log passwords or tokens.

## Domain rules (quick reference; full detail in PLAN.md)
- **Prices.**
  - *weekly_avg items:* the month splits into periods 1–10 / 11–20 / 21–end. Each period uses the manual price, else the average purchase rate, else the price carried forward. The month price is the mean of the three, and leading empty periods are backfilled.
  - *daily items:* manual price that day > that day's purchase average > last known price.
  - Purchases write `PriceEntry(source="purchase")` automatically.
- **Audits.** Any date. Expected = opening + purchases − issued since the previous audit. **Variance % = (expected − counted) ÷ expected**; flagged if over the threshold (default 2%, in Settings). A blank count = not counted, and expected carries forward. An `opening` audit resets the chain. A `month_end` audit can't close while other audits that month are open.
- **Wastage** is cooked food entered in ₹. It does **not** move raw stock; the full amount is added to COGS.
- **Issues are the source of truth for what a station took.** "Give to stations" writes `Issue` rows, the same rows as the station issues screen.
- **Daily ordering.**
  - *Requisitions:* in consumption units, per station per delivery date. Only `Item.daily_order` items go into vendor plans; dry store items are handed over from store stock.
  - *Vendor orders:* one `DailyOrder` per vendor per date. An item can be split across vendors, and the last split proportion is pre-filled.
  - *Receiving:* creates or updates a `PurchaseBill`.
  - *Pending:* asked > given, date ≤ today, within 7 days, not dismissed. The reason is vendor short / not received / not ordered / only X in store / not handed over.
- **WhatsApp:** messages open via `wa.me` links. Vendors usually have a **WhatsApp group**, and links can't target groups, so the UI opens the share screen and names the group to pick. Automatic sending would need the WhatsApp Business API (not built).
- **Users:** no roles yet. A user with `station_id` lands on the kitchen screen; that's a convenience, not a permission.

## Gotchas already hit
- Pydantic models with a field named `date` and a default: `date: date | None = None` breaks (`NoneType | NoneType`). Use `import datetime as dt` and `date: dt.date | None = None`.
- The API Docker image builds from the **repo root** (`backend/Dockerfile` copies `backend/` and `VERSION`). The root `.dockerignore` applies.
- Locally over http, `COOKIE_SECURE=false` is required, or sign-in loops back to the login screen.
- In-memory login throttle and `--workers 2` mean the throttle is per worker. Fine for now; use Redis or the DB if this becomes a public SaaS.
- Seed data quirks from the workbook: *Eggs Tray* has purchase unit = consumption unit = Piece (should be Tray → Piece × 30), and 19 items have no price.
- Generated `PriceEntry` rows cascade-delete with their purchase line (DB-level `ON DELETE CASCADE`).

## Roadmap and backlog
- **Next (after go-live):** fixes from the trial. Log them as GitHub Issues using the "Bug or wrong number" template.
- **Station balance of cooked items:** see the questions at the end of `PLAN.md`. Settle them with Aneesh before building.
- **Phase 4:** Petpooja sales import, recipes (dish → ingredients), theoretical vs actual consumption, recipe-based wastage valuation.
- **Productising for other restaurants (v2.x), if pursued:**
  1. Multi-restaurant tenancy: org/outlet per account, every query scoped, cross-tenant leakage tests.
  2. Roles: owner / manager / store / kitchen.
  3. Self-serve signup with a generic template and Excel item import.
  4. Password reset by email.
  5. Billing (Razorpay, GST invoices).
  6. Per-tenant data export, monitoring, terms/privacy (DPDP Act).
- **Nice to have:** WhatsApp Business API sending, Excel export of any screen, per-item min/par overrides, audit locking.
