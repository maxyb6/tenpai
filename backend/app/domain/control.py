"""Control-group assignment.

Stratified by (bucket at open, branch) with permuted blocks: within every
stratum, each consecutive block of `block_size` cases holds exactly
round(share x block_size) control cases, in an order fixed by a hash of the
tenant, stratum and block number. That makes the split exact per stratum,
reproducible from the inputs, and independent of import order across strata.

The arm is written once, at case open, as a `control_assigned` event, and the
case projection never changes it.
"""
import hashlib
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Case


def stratum_key(bucket: str, branch_name: str) -> str:
    """Keyed by branch name, not id, so a reseed reproduces the same arms."""
    return f"{bucket}|{branch_name}"


def block_layout(tenant_id: str, stratum: str, block_no: int, share: float, block_size: int) -> list[str]:
    n_control = round(share * block_size)
    arms = ["control"] * n_control + ["treatment"] * (block_size - n_control)
    seed = int.from_bytes(hashlib.sha256(f"{tenant_id}|{stratum}|{block_no}".encode()).digest()[:8], "big")
    random.Random(seed).shuffle(arms)
    return arms


def assign_arm(session: Session, tenant_id: str, stratum: str, share: float, block_size: int) -> tuple[str, int]:
    """Returns (arm, position in stratum). Position is the count of cases already
    opened in this stratum, so assignment depends only on stratum history."""
    position = session.scalar(
        select(func.count(Case.id)).where(Case.tenant_id == tenant_id, Case.stratum == stratum)
    ) or 0
    block_no, offset = divmod(position, block_size)
    return block_layout(tenant_id, stratum, block_no, share, block_size)[offset], position
