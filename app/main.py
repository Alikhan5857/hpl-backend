# app/main.py

from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from .database import SessionLocal, Base, engine
from .models import User, MatchLiveState
from .auth_jwt import create_access_token

from .routers import contests as contests_mod
from .routers.contests import router as contests_router
from .routers.dev import router as dev_router
from app.routers.wallet import router as wallet_router

from .providers.sportmonks import (
    list_fixtures,
    get_fixture,
    normalize_scoreboard,
    sportmonks_get,
)

# Create tables (dev only)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="HPL - Hamara Premier League API", version="0.2")


# ---------------- AUTO LOOPS CONFIG ----------------
AUTO_LOCK_ENABLED = True
AUTO_LOCK_INTERVAL_SEC = 10  # har 10 sec me check

AUTO_SETTLE_ENABLED = True
AUTO_SETTLE_INTERVAL_SEC = 20  # 20 sec me check


async def auto_lock_loop():
    while True:
        try:
            if AUTO_LOCK_ENABLED:
                db = SessionLocal()
                try:
                    locked = contests_mod.lock_due_internal(db)
                    if locked:
                        print(f"[auto_lock] locked_count={locked}")
                finally:
                    db.close()
        except Exception as e:
            print("[auto_lock] error:", e)

        await asyncio.sleep(AUTO_LOCK_INTERVAL_SEC)


async def auto_settle_loop():
    """
    Background loop:
    - locked contests check
    - their match finished? -> settle
    Logic should stay in contests_mod.auto_settle_due_internal(db)
    """
    while True:
        try:
            if AUTO_SETTLE_ENABLED:
                db = SessionLocal()
                try:
                    fn = getattr(contests_mod, "auto_settle_due_internal", None)
                    if callable(fn):
                        settled = fn(db)
                        if settled:
                            print(f"[auto_settle] settled_count={settled}")
                    else:
                        print("[auto_settle] auto_settle_due_internal not found in contests.py")
                finally:
                    db.close()
        except Exception as e:
            print("[auto_settle] error:", e)

        await asyncio.sleep(AUTO_SETTLE_INTERVAL_SEC)


@app.on_event("startup")
async def start_loops():
    # Stable mode: auto lock on, auto settle off
    asyncio.create_task(auto_lock_loop())
    asyncio.create_task(auto_settle_loop())


# routers
app.include_router(dev_router)
app.include_router(contests_router)
app.include_router(wallet_router)


# ---------------- DB ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- Basic ----------------
@app.get("/")
def root():
    return {"app": "HPL Backend", "status": "running"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT 1")).scalar()
    return {"db": "ok", "result": result}


# ---------------- DEV create user ----------------
class DevCreateUserIn(BaseModel):
    phone: str
    name: Optional[str] = None


@app.post("/dev/create_user")
def dev_create_user(payload: DevCreateUserIn, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.phone == payload.phone).first()
    if u:
        return {"message": "exists", "user_id": u.id}

    u = User(phone=payload.phone, name=payload.name, coins_balance=0)
    db.add(u)
    db.commit()
    db.refresh(u)

    return {"message": "created", "user_id": u.id}


# ---------------- OTP Auth ----------------
SECRET_KEY = os.getenv("APP_SECRET", "dev_secret_change_me")


def _hash_otp(phone: str, otp: str) -> str:
    s = f"{SECRET_KEY}:{phone}:{otp}".encode("utf-8")
    return hashlib.sha256(s).hexdigest()


class SendOtpIn(BaseModel):
    phone: str


class VerifyOtpIn(BaseModel):
    phone: str
    otp: str


@app.post("/auth/send-otp")
def send_otp(payload: SendOtpIn, db: Session = Depends(get_db)):
    phone = payload.phone.strip()

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        user = User(phone=phone, role="user", coins_balance=0)
        db.add(user)
        db.commit()
        db.refresh(user)

    otp = f"{random.randint(100000, 999999)}"
    user.otp_hash = _hash_otp(phone, otp)
    user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    db.add(user)
    db.commit()

    return {
        "message": "otp_generated",
        "otp": otp,  # DEV only
        "expires_in_sec": 300,
    }


@app.post("/auth/verify-otp")
def verify_otp(payload: VerifyOtpIn, db: Session = Depends(get_db)):
    phone = payload.phone.strip()
    otp = payload.otp.strip()

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")

    if not user.otp_hash or not user.otp_expires_at:
        raise HTTPException(status_code=400, detail="otp_not_requested")

    if datetime.now(timezone.utc) > user.otp_expires_at:
        raise HTTPException(status_code=400, detail="otp_expired")

    if user.otp_hash != _hash_otp(phone, otp):
        raise HTTPException(status_code=400, detail="otp_invalid")

    # Clear OTP
    user.otp_hash = None
    user.otp_expires_at = None
    db.add(user)
    db.commit()

    token = create_access_token(str(user.id))

    return {
        "message": "verified",
        "user_id": str(user.id),
        "token": token,
    }


# ---------------- SportMonks ----------------
@app.get("/fixtures/live")
def fixtures_live(page: int = 1, per_page: int = 25):
    try:
        return sportmonks_get(
            "/fixtures",
            params={
                "page": page,
                "per_page": per_page,
                "filter[live]": "true",
                "include": "localteam,visitorteam",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/fixtures/upcoming")
def fixtures_upcoming(page: int = 1, per_page: int = 25):
    try:
        return sportmonks_get(
            "/fixtures",
            params={
                "page": page,
                "per_page": per_page,
                "filter[status]": "NS",
                "include": "localteam,visitorteam",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/internal/poll/sportmonks/{match_id}")
def poll_sportmonks(match_id: str, db: Session = Depends(get_db)):
    state = db.query(MatchLiveState).filter(
        MatchLiveState.match_id == match_id
    ).first()

    if not state or not state.sportmonks_fixture_id:
        raise HTTPException(status_code=400, detail="match_not_bound")

    res = get_fixture(state.sportmonks_fixture_id)
    normalized = normalize_scoreboard(res)

    state.raw = res
    state.normalized = normalized
    state.last_fetched_at = datetime.now(timezone.utc)

    db.add(state)
    db.commit()

    return {
        "message": "polled",
        "match_id": match_id,
        "fixture_id": state.sportmonks_fixture_id,
    }


@app.get("/matches/{match_id}/scoreboard")
def get_scoreboard(match_id: str, force_refresh: bool = False, db: Session = Depends(get_db)):
    state = db.query(MatchLiveState).filter(
        MatchLiveState.match_id == match_id
    ).first()

    if not state or not state.sportmonks_fixture_id:
        raise HTTPException(status_code=404, detail="match_not_bound")

    if force_refresh or state.normalized is None:
        res = get_fixture(state.sportmonks_fixture_id)
        normalized = normalize_scoreboard(res)
        state.raw = res
        state.normalized = normalized
        state.last_fetched_at = datetime.now(timezone.utc)
        db.add(state)
        db.commit()

    return {
        "match_id": match_id,
        "fixture_id": state.sportmonks_fixture_id,
        "scoreboard": state.normalized,
    }

class BindMatchIn(BaseModel):
    match_id: str
    fixture_id: int


@app.post("/internal/bind-match")
def bind_match(payload: BindMatchIn, db: Session = Depends(get_db)):
    state = db.query(MatchLiveState).filter(
        MatchLiveState.match_id == payload.match_id
    ).first()

    if not state:
        state = MatchLiveState(
            match_id=payload.match_id,
            sportmonks_fixture_id=payload.fixture_id
        )
    else:
        state.sportmonks_fixture_id = payload.fixture_id

    db.add(state)
    db.commit()

    return {
        "message": "bound",
        "match_id": payload.match_id,
        "fixture_id": payload.fixture_id
    }