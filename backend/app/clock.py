"""Business clock. Every time-dependent decision asks the tenant's clock, so the
demo can advance a day and the scheduler, send gate and SLAs all move with it."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Tenant


def now(tenant: Tenant) -> datetime:
    if tenant.demo_now is not None:
        return tenant.demo_now
    return datetime.now(timezone.utc)


def local_now(tenant: Tenant) -> datetime:
    return now(tenant).astimezone(ZoneInfo(tenant.timezone))


def today(tenant: Tenant) -> date:
    return local_now(tenant).date()


def local_datetime(tenant: Tenant, d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(tenant.timezone))


def advance(session: Session, tenant: Tenant, delta: timedelta) -> datetime:
    """Demo only."""
    if tenant.demo_now is None:
        tenant.demo_now = datetime.now(timezone.utc)
    tenant.demo_now = tenant.demo_now + delta
    session.flush()
    return tenant.demo_now
