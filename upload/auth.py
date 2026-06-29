"""Shared auth: reads the same JWT cookie the portal sets."""
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Request

SECRET_KEY = os.getenv("PORTAL_SECRET_KEY", "ppm-portal-secret-change-in-prod")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

USERS = {
    "admin":     {"password": os.getenv("PORTAL_ADMIN_PASS",   "Jppm@min123"), "role": "admin",      "name": "Admin"},
    "developer": {"password": os.getenv("PORTAL_DEV_PASS",     "Jppm@min123"), "role": "developer",  "name": "Developer"},
    "analyst":   {"password": os.getenv("PORTAL_ANALYST_PASS", "Jppm@min123"), "role": "power_user", "name": "Power User"},
    "user":      {"password": os.getenv("PORTAL_USER_PASS",    "Jppm@min123"), "role": "end_user",   "name": "End User"},
}


class LoginRequired(Exception):
    pass


def create_token(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict | None:
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = data.get("sub")
        if username not in USERS:
            return None
        u = USERS[username]
        return {"username": username, "role": u["role"], "name": u["name"]}
    except jwt.PyJWTError:
        return None


def get_current_user(request: Request) -> dict:
    token = request.cookies.get("session")
    if not token:
        raise LoginRequired()
    user = verify_token(token)
    if not user:
        raise LoginRequired()
    return user
