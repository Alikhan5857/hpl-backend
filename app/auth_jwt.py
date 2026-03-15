# app/auth_jwt.py
import os
from .database import get_db
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .models import User

bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    s = os.getenv("JWT_SECRET")
    if not s:
        raise RuntimeError("JWT_SECRET missing in .env")
    return s


def create_access_token(user_id: str) -> str:
    minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "43200"))  # 30 days default
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }

    return jwt.encode(payload, _secret(), algorithm="HS256")


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = creds.credentials

    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user