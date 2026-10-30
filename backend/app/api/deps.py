"""Request context. The demo has no production auth: the console sends the
chosen role and user id as headers and the API scopes data from them."""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Tenant, User

ROLES = ("head_of_collections", "branch_manager", "credit_officer", "leadership")


@dataclass
class Ctx:
    session: Session
    tenant: Tenant
    user: User | None
    role: str

    @property
    def actor(self) -> str:
        return f"user:{self.user.id}" if self.user else "user:demo"

    @property
    def branch_id(self) -> int | None:
        return self.user.branch_id if self.user and self.role == "branch_manager" else None

    @property
    def officer_id(self) -> int | None:
        return self.user.officer_id if self.user and self.role == "credit_officer" else None

    def require(self, *roles: str):
        if self.role not in roles:
            raise HTTPException(403, f"{self.role} cannot do this")


def ctx(
    tenant_id: str,
    session: Session = Depends(get_session),
    x_role: str | None = Header(default=None),
    x_user_id: int | None = Header(default=None),
) -> Ctx:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    role = x_role if x_role in ROLES else "head_of_collections"
    user = session.get(User, x_user_id) if x_user_id else None
    if user is not None and user.tenant_id != tenant.id:
        user = None
    if user is None:
        user = session.scalars(select(User).where(User.tenant_id == tenant.id, User.role == role)
                               .order_by(User.id).limit(1)).first()
    return Ctx(session=session, tenant=tenant, user=user, role=role)
