"""Email accounts and opaque cookie sessions for the web app."""
import hashlib
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

class AccountRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validate(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, detail="invalid_account_input") from None

        return validate


router = APIRouter(prefix="/auth", route_class=AccountRoute)
log = logging.getLogger(__name__)
COOKIE = "insurance_session"
SESSION_AGE = 7 * 24 * 60 * 60
EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    email TEXT PRIMARY KEY NOT NULL,
    salt BLOB NOT NULL,
    password_hash BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash BLOB PRIMARY KEY NOT NULL,
    email TEXT NOT NULL REFERENCES accounts(email),
    expires_at INTEGER NOT NULL
);
"""


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        if not isinstance(value, str):
            raise ValueError("invalid_email")
        value = value.strip().lower()
        if not EMAIL.fullmatch(value):
            raise ValueError("invalid_email")
        return value


class Registration(Credentials):
    password: str = Field(min_length=8, max_length=128)


def database():
    path = Path(os.environ.get("INSURANCE_ACCOUNTS_DB", "var/accounts.sqlite3"))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(SCHEMA)
    except BaseException:
        db.close()
        raise
    return closing(db)


def digest(password, salt):
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024**2)


def session(db, request, response, email):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    previous = request.cookies.get(COOKIE)
    if previous:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(previous.encode()).digest(),))
    db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (hashlib.sha256(token.encode()).digest(), email, now + SESSION_AGE))
    db.commit()
    response.set_cookie(
        COOKIE, token, max_age=SESSION_AGE, httponly=True, samesite="lax",
        secure=request.url.scheme == "https" or os.environ.get("INSURANCE_SECURE_COOKIE") == "1",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"email": email}


def storage_error(exc):
    log.error("Account storage failure (%s)", type(exc).__name__)
    return HTTPException(500, detail="account_storage_error")


@router.post("/register", status_code=201)
def register(body: Registration, request: Request, response: Response):
    salt = secrets.token_bytes(16)
    try:
        with database() as db:
            inserted = db.execute(
                "INSERT INTO accounts VALUES (?, ?, ?) ON CONFLICT(email) DO NOTHING",
                (body.email, salt, digest(body.password, salt)),
            )
            if inserted.rowcount == 0:
                raise HTTPException(409, detail="duplicate_email")
            return session(db, request, response, body.email)
    except (sqlite3.Error, OSError) as exc:
        raise storage_error(exc) from None


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    try:
        with database() as db:
            account = db.execute(
                "SELECT salt, password_hash FROM accounts WHERE email = ?", (body.email,),
            ).fetchone()
            salt, expected = account or (bytes(16), bytes(64))
            if not secrets.compare_digest(digest(body.password, salt), expected) or account is None:
                raise HTTPException(401, detail="invalid_credentials")
            return session(db, request, response, body.email)
    except (sqlite3.Error, OSError) as exc:
        raise storage_error(exc) from None


@router.get("/session")
def current_session(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, detail="session_required")
    try:
        with database() as db:
            row = db.execute(
                "SELECT email FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (hashlib.sha256(token.encode()).digest(), int(time.time())),
            ).fetchone()
    except (sqlite3.Error, OSError) as exc:
        raise storage_error(exc) from None
    if row is None:
        raise HTTPException(401, detail="session_required")
    response.headers["Cache-Control"] = "no-store"
    return {"email": row[0]}
