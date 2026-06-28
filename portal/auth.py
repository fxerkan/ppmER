from datetime import datetime, timedelta, timezone
from fastapi import Request
from fastapi.responses import RedirectResponse
import jwt

from config import SECRET_KEY, USERS

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


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
        user = USERS[username]
        return {"username": username, "role": user["role"], "name": user["name"]}
    except jwt.PyJWTError:
        return None


def get_current_user(request: Request) -> dict:
    token = request.cookies.get("session")
    if not token:
        raise _redirect_to_login()
    user = verify_token(token)
    if not user:
        raise _redirect_to_login()
    return user


def _redirect_to_login():
    from fastapi import HTTPException
    # Use a custom exception that main.py catches and converts to redirect
    return LoginRequired()


class LoginRequired(Exception):
    pass
