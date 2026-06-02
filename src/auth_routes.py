"""Auth endpoints — mounted onto the main FastAPI app."""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from src.auth import (
    verify_password, create_access_token, create_refresh_token,
    decode_token, get_user, get_current_user, require_admin,
    list_users, create_user, delete_user, change_password, hash_password,
    ACCESS_TTL, REFRESH_TTL,
    check_rate_limit, record_failed_attempt, clear_failed_attempts,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class CreateUserBody(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
def login(body: LoginBody, response: Response, request: Request):
    ip = request.client.host
    check_rate_limit(ip)
    user = get_user(body.username)
    if not user or not verify_password(body.password, user.hashed_pw):
        record_failed_attempt(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    clear_failed_attempts(ip)
    access  = create_access_token(user.username, user.role)
    refresh = create_refresh_token(user.username)

    response.set_cookie("access_token",  access,  httponly=True, samesite="lax", path="/", max_age=int(ACCESS_TTL.total_seconds()))
    response.set_cookie("refresh_token", refresh, httponly=True, samesite="lax", path="/", max_age=int(REFRESH_TTL.total_seconds()))
    return {"ok": True, "username": user.username, "role": user.role}


@router.post("/refresh")
def refresh(response: Response, refresh_token: str = Cookie(default=None)):
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    user = get_user(payload["sub"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    access = create_access_token(user.username, user.role)
    response.set_cookie("access_token", access, httponly=True, samesite="lax", path="/", max_age=int(ACCESS_TTL.total_seconds()))
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"ok": True}


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user


# ── Admin-only user management ────────────────────────────────────────────
@router.get("/users")
def get_users(current_user: dict = Depends(require_admin)):
    return list_users()


@router.post("/users")
def add_user(body: CreateUserBody, current_user: dict = Depends(require_admin)):
    try:
        create_user(body.username, body.password, body.role)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/users/{username}")
def remove_user(username: str, current_user: dict = Depends(require_admin)):
    if username == current_user["username"]:
        raise HTTPException(400, "Cannot delete your own account")
    delete_user(username)
    return {"ok": True}


@router.post("/change-password")
def do_change_password(body: ChangePasswordBody, current_user: dict = Depends(get_current_user)):
    user = get_user(current_user["username"])
    if not verify_password(body.old_password, user.hashed_pw):
        raise HTTPException(400, "Old password incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    change_password(current_user["username"], body.new_password)
    return {"ok": True}
