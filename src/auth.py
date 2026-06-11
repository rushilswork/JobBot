"""
Authentication & Authorization for JobBot.

- Passwords hashed with bcrypt (cost factor 8)
- JWT access tokens (HS256, 30d expiry) + refresh tokens (90d expiry)
- Tokens stored in httpOnly, SameSite=Strict cookies (not localStorage)
- Roles: admin (full access), viewer (read-only, no purge/clear/scan)
- User store: SQLite via SQLAlchemy (same DB as jobs)
"""
from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import Cookie, Depends, HTTPException, Request, status

# ── Secret key ────────────────────────────────────────────────────────────
_KEY_FILE = Path(__file__).resolve().parent.parent / "data" / ".jwt_secret"

def _load_secret() -> str:
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        secret = _KEY_FILE.read_text().strip()
        _KEY_FILE.chmod(0o600)
        if len(secret) < 32:
            secret = secrets.token_hex(64)
            _KEY_FILE.write_text(secret)
            _KEY_FILE.chmod(0o600)
        return secret
    secret = secrets.token_hex(64)
    _KEY_FILE.write_text(secret)
    _KEY_FILE.chmod(0o600)
    return secret

SECRET_KEY = _load_secret()
ALGORITHM  = "HS256"
ACCESS_TTL  = timedelta(days=30)
REFRESH_TTL = timedelta(days=90)

# ── Login rate limiting ───────────────────────────────────────────────────
_failed_attempts: dict = {}
_LOCKOUT_SECONDS = 60
_MAX_ATTEMPTS = 5

def check_rate_limit(ip: str) -> None:
    entry = _failed_attempts.get(ip)
    if entry and entry["locked_until"] > time.time():
        raise HTTPException(429, "Too many failed attempts — try again in 60 seconds")

def record_failed_attempt(ip: str) -> None:
    entry = _failed_attempts.get(ip, {"count": 0, "locked_until": 0.0})
    entry["count"] += 1
    if entry["count"] >= _MAX_ATTEMPTS:
        entry["locked_until"] = time.time() + _LOCKOUT_SECONDS
    _failed_attempts[ip] = entry

def clear_failed_attempts(ip: str) -> None:
    _failed_attempts.pop(ip, None)


# ── Password hashing ──────────────────────────────────────────────────────
BCRYPT_ROUNDS = 8

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

# ── JWT ───────────────────────────────────────────────────────────────────
def create_access_token(username: str, role: str) -> str:
    exp = datetime.utcnow() + ACCESS_TTL
    return jwt.encode({"sub": username, "role": role, "iss": "jobbot", "exp": exp, "type": "access"}, SECRET_KEY, ALGORITHM)

def create_refresh_token(username: str) -> str:
    exp = datetime.utcnow() + REFRESH_TTL
    return jwt.encode({"sub": username, "exp": exp, "type": "refresh"}, SECRET_KEY, ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") == "access" and payload.get("iss") != "jobbot":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token issuer")
        return payload
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

# ── User store (SQLite) ───────────────────────────────────────────────────
from sqlalchemy import Column, String, DateTime, Boolean
from src.database import Base, engine, SessionLocal

class User(Base):
    __tablename__ = "users"
    username   = Column(String, primary_key=True)
    hashed_pw  = Column(String, nullable=False)
    role       = Column(String, default="viewer")
    created_at = Column(DateTime, default=datetime.utcnow)
    active     = Column(Boolean, default=True)

def init_users():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    if not session.query(User).first():
        admin = User(
            username  = os.environ.get("JOBBOT_ADMIN_USER", "admin"),
            hashed_pw = hash_password(os.environ.get("JOBBOT_ADMIN_PASS", "adminadmin")),
            role      = "admin",
        )
        session.add(admin)
        session.commit()
    session.close()

_user_cache: dict = {}

def get_user(username: str, bust_cache: bool = False) -> Optional[User]:
    if not bust_cache and username in _user_cache:
        return _user_cache[username]
    session = SessionLocal()
    try:
        user = session.query(User).filter_by(username=username, active=True).first()
        if user:
            # Cache a plain-dict snapshot — avoids DetachedInstanceError after session close
            _user_cache[username] = User(
                username=user.username,
                hashed_pw=user.hashed_pw,
                role=user.role,
                active=user.active,
                created_at=user.created_at,
            )
            _user_cache[username].__dict__.update({k: v for k, v in user.__dict__.items() if not k.startswith('_')})
        return _user_cache.get(username) if user else None
    finally:
        session.close()

def list_users() -> list[dict]:
    session = SessionLocal()
    users = session.query(User).filter_by(active=True).all()
    result = [{"username": u.username, "role": u.role, "active": u.active, "created_at": u.created_at.isoformat()} for u in users]
    session.close()
    return result

def create_user(username: str, password: str, role: str = "viewer") -> User:
    session = SessionLocal()
    if session.query(User).filter_by(username=username).first():
        session.close()
        raise ValueError(f"User '{username}' already exists")
    u = User(username=username, hashed_pw=hash_password(password), role=role)
    session.add(u)
    session.commit()
    session.close()
    return u

def delete_user(username: str):
    from src.database import Job, get_session as get_job_session
    job_session = get_job_session()
    job_session.query(Job).filter(Job.discovered_by == username).delete()
    job_session.commit()
    job_session.close()
    session = SessionLocal()
    u = session.query(User).filter_by(username=username).first()
    if u:
        session.delete(u)
        session.commit()
    session.close()
    _user_cache.pop(username, None)

def change_password(username: str, new_password: str):
    session = SessionLocal()
    u = session.query(User).filter_by(username=username).first()
    if not u:
        raise ValueError("User not found")
    u.hashed_pw = hash_password(new_password)
    session.commit()
    session.close()
    _user_cache.pop(username, None)

# ── FastAPI dependency ────────────────────────────────────────────────────
def get_current_user(access_token: str = Cookie(default=None)) -> dict:
    if not access_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_token(access_token)
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    username = payload["sub"]
    user = get_user(username, bust_cache=True)
    if not user:
        _user_cache.pop(username, None)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return {"username": username, "role": payload.get("role", "viewer")}

def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return current_user
