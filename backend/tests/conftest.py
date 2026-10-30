import os
from datetime import date

from app.config import TEST_DATABASE_URL

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from pathlib import Path  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402

AS_OF = date(2026, 11, 5)


@pytest.fixture(scope="session", autouse=True)
def migrated():
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(scope="session")
def seeded_mm(migrated):
    from app.seed.loader import seed_tenant

    with SessionLocal() as s:
        out = seed_tenant(s, "MM", AS_OF, write_sample=False)
        s.commit()
    return out


@pytest.fixture
def session():
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()
