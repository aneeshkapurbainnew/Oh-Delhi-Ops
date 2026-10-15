from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path

from .auth import require_user
from .config import get_settings
from .routers import audits, auth, daily, finance, issues, prices, purchases, reports, reviews, setup

settings = get_settings()
if not settings.auth_disabled and settings.app_secret == "change-me-in-production":
    raise RuntimeError("Set APP_SECRET in the environment before starting the API.")

def _version() -> str:
    for p in (Path(__file__).resolve().parents[1] / "VERSION", Path(__file__).resolve().parents[2] / "VERSION"):
        if p.exists():
            return p.read_text().strip()
    return "dev"


VERSION = _version()
app = FastAPI(title="Oh Delhi Ops API", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")  # login / logout / me handle their own auth
protected = [Depends(require_user)]
for r in (
    auth.users_router, setup.router, prices.router, purchases.router, issues.router,
    audits.router, finance.router, reviews.router, reports.router, daily.router,
):
    app.include_router(r, prefix="/api", dependencies=protected)


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION}
