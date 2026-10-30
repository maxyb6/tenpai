import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = ROOT / "sample_data"

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://tenpai:tenpai@localhost:5432/tenpai"
)
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://tenpai:tenpai@localhost:5432/tenpai_test"
)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or None
# Signs per-borrower Mini App links and Telegram start tokens.
LINK_SIGNING_SECRET = os.environ.get("LINK_SIGNING_SECRET", "dev-only-change-me")
# Where the lender's data is hosted. A note for now; per-lender in production.
DATA_HOSTING_REGION = os.environ.get("DATA_HOSTING_REGION", "Singapore (ap-southeast-1)")
