# Making changes and releasing versions

## Branches
- `main` is what runs at the restaurant. It should always pass CI.
- For every change, make a branch (`feature/whatsapp-api`, `fix/audit-rounding`), open a pull request into `main`, wait for the green CI tick, then merge.
- Small fixes during the trial can go straight to `main` if CI is green.

## Versions (MAJOR.MINOR.PATCH)
- **PATCH** (1.1.0 → 1.1.1): fixes; no change to how anyone works.
- **MINOR** (1.1.x → 1.2.0): new features or screens; staff may need a quick walkthrough.
- **MAJOR** (1.x → 2.0.0): changes to how the restaurant works or to the data model that need planning, e.g. multi-outlet.

## Releasing
1. Update `VERSION` and add an entry at the top of `CHANGELOG.md`.
2. Commit, then tag and push:
   ```bash
   git commit -am "Release v1.2.0"
   git tag v1.2.0
   git push origin main --tags
   ```
3. Wait for CI to pass on GitHub.
4. On the server: `cd ~/ohdelhi-ops/deploy && ./update.sh v1.2.0`.
5. Check the version at the bottom of the app menu.

## Database changes
- Change `backend/app/models.py`, then from `backend/` run `alembic revision --autogenerate -m "short description"`. Read the generated file and name any `None` constraint names.
- Never edit a migration that has already run on the server; add a new one instead.
- Migrations only go forward. Rolling the code back with `./update.sh v<older>` after a migration may not work. If a release with a migration goes wrong, restore the previous night's backup (README §5) and then roll back.

## Tests
- Backend: `pytest -q` in `backend/`, with `TEST_DATABASE_URL` pointing at a throwaway database. Add a test for any calculation you change.
- Frontend: `npm run build` in `frontend/` must pass.
- CI runs both, plus migrations on an empty database and the Docker builds, on every push.

## Reporting problems during the trial
Use GitHub **Issues → New issue → Bug or wrong number**. Include the screen, the date, what you expected and what the app showed. A screenshot helps most.
