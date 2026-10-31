import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = ROOT / "sample_data"

def _driver(url: str) -> str:
    """Hosts hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg driver named."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _driver(os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://tenpai:tenpai@localhost:5432/tenpai"
))
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://tenpai:tenpai@localhost:5432/tenpai_test"
)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or None
# Signs per-borrower Mini App links and Telegram start tokens.
LINK_SIGNING_SECRET = os.environ.get("LINK_SIGNING_SECRET", "dev-only-change-me")
# Where the lender's data is hosted. A note for now; per-lender in production.
DATA_HOSTING_REGION = os.environ.get("DATA_HOSTING_REGION", "Singapore (ap-southeast-1)")
# Optional password for the console on a public URL. Borrower Mini App links stay open.
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD") or None
# Seed the demo tenants on first boot when the database is empty.
SEED_ON_START = os.environ.get("SEED_ON_START", "").lower() in ("1", "true", "yes")
# Demo "today" for seeding (YYYY-MM-DD); default is today in Yangon.
DEMO_AS_OF = os.environ.get("DEMO_AS_OF") or None
FRONTEND_DIST = ROOT / "frontend" / "dist"
