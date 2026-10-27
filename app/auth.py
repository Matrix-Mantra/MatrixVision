"""Sign-in: Firebase ID tokens from the same Firebase project as Matrix, verified on the server."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Header, HTTPException

from . import config
from .store import get_store

log = logging.getLogger("vision.auth")


@dataclass(frozen=True)
class User:
    uid: str
    name: str = ""
    email: str = ""


@lru_cache(maxsize=1)
def firebase_app():
    import firebase_admin

    try:
        return firebase_admin.get_app()
    except ValueError:
        # On Cloud Run the service account's default credentials are used.
        return firebase_admin.initialize_app(options={"projectId": config.FIREBASE_PROJECT_ID})


def _verify(token: str) -> User:
    if config.AUTH_MODE == "dev":
        if not token.startswith("dev:") or len(token) < 5:
            raise HTTPException(401, "Please sign in again.")
        uid = token[4:][:64]
        return User(uid=uid, name=uid)
    from firebase_admin import auth as fb_auth

    try:
        claims = fb_auth.verify_id_token(token, app=firebase_app(), clock_skew_seconds=10)
    except Exception as exc:
        log.info("token rejected: %s", type(exc).__name__)
        raise HTTPException(401, "Please sign in again.") from exc
    return User(uid=claims["uid"], name=claims.get("name", ""), email=claims.get("email", ""))


def current_user(authorization: str = Header(default="")) -> User:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Please sign in to scan a document.")
    return _verify(token.strip())


def check_limit(user: User, kind: str, limit: int) -> None:
    if get_store().increment(user.uid, kind, limit) is None:
        raise HTTPException(429, "You have reached today's limit. Please try again tomorrow.")


def refund(user: User, kind: str) -> None:
    """Give a use back when the failure was ours (e.g. the AI service was down)."""
    try:
        get_store().refund(user.uid, kind)
    except Exception:
        log.exception("refund failed")
