"""Minimal API-key RBAC for plant-network deployments."""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException


ROLE_LEVEL = {"operator": 1, "engineer": 2, "admin": 3}


@dataclass(frozen=True)
class Identity:
    name: str
    role: str


def _enabled() -> bool:
    return os.environ.get("NEFTEKOD_AUTH_ENABLED", "false").lower() in {"1", "true", "yes"}


def _resolve(api_key: str | None) -> Identity:
    if not _enabled():
        return Identity(name="Локальный оператор", role="admin")
    configured = (
        ("operator", os.environ.get("NEFTEKOD_OPERATOR_API_KEY")),
        ("engineer", os.environ.get("NEFTEKOD_ENGINEER_API_KEY")),
        ("admin", os.environ.get("NEFTEKOD_ADMIN_API_KEY")),
    )
    for role, secret in configured:
        if secret and api_key and hmac.compare_digest(secret, api_key):
            return Identity(name=f"{role}@neftekod", role=role)
    raise HTTPException(status_code=401, detail="Требуется действующий API-ключ")


def require_role(minimum: str):
    def dependency(x_api_key: str | None = Header(default=None)) -> Identity:
        identity = _resolve(x_api_key)
        if ROLE_LEVEL[identity.role] < ROLE_LEVEL[minimum]:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return identity
    return dependency


operator_access = require_role("operator")
engineer_access = require_role("engineer")
admin_access = require_role("admin")
