# app/routers/contests.py

import os
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import SessionLocal
from app.auth_jwt import get_current_user
from app.models import (
    User,
    CoinLedger,
    Contest,
    ContestEntry,
    ContestResult,
    MatchLiveState,
)

DEFAULT_CONTEST_SLABS = [
    {"title": "Mini ₹100", "entry_fee": 100, "team_a_mult": 1.5, "team_b_mult": 2.0},
    {"title": "Small ₹200", "entry_fee": 200, "team_a_mult": 1.5, "team_b_mult": 2.0},
    {"title": "Mega ₹500", "entry_fee": 500, "team_a_mult": 1.5, "team_b_mult": 2.0},
    {"title": "Pro ₹1000", "entry_fee": 1000, "team_a_mult": 1.5, "team_b_mult": 2.0},
    {"title": "Elite ₹5000", "entry_fee": 5000, "team_a_mult": 1.5, "team_b_mult": 2.0},
]

router = APIRouter(prefix="/contests", tags=["Contests"])


# -----------------------------
# Auto-create default contests for a match
# -----------------------------
def ensure_default_contests_for_match(db: Session, match_id: str):
    existing_contests: List[Contest] = (
        db.query(Contest)
        .filter(Contest.match_id == match_id)
        .all()
    )

    existing_fees = {int(c.entry_fee) for c in existing_contests if c.entry_fee is not None}

    # fallback team names
    team_a_name = "TEAM_A"
    team_b_name = "TEAM_B"

    # try reading names from MatchLiveState if present
    state = db.query(MatchLiveState).filter(MatchLiveState.match_id == match_id).first()
    if state:
        if getattr(state, "team_a_name", None):
            team_a_name = state.team_a_name
        if getattr(state, "team_b_name", None):
            team_b_name = state.team_b_name

    # keep contests open
    lock_at = datetime.now(timezone.utc) + timedelta(days=30)

    created_any = False

    for slab in DEFAULT_CONTEST_SLABS:
        fee = int(slab["entry_fee"])
        if fee in existing_fees:
            continue

        contest = Contest(
            id=f"contest_{uuid.uuid4().hex[:10]}",
            title=slab["title"],
            match_id=match_id,
            entry_fee=fee,
            team_a_name=team_a_name,
            team_b_name=team_b_name,
            team_a_mult=str(slab["team_a_mult"]),
            team_b_mult=str(slab["team_b_mult"]),
            lock_at=lock_at,
            status="open",
        )
        db.add(contest)
        created_any = True

    if created_any:
        db.commit()


# -----------------------------
# Helpers
# -----------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_admin(x_admin_key: Optional[str]):
    admin_key = (os.getenv("ADMIN_KEY") or os.getenv("ADMIN_API_KEY") or "").strip()
    if not admin_key:
        raise HTTPException(status_code=500, detail="ADMIN_KEY_not_set")
    if not x_admin_key or x_admin_key.strip() != admin_key:
        raise HTTPException(status_code=401, detail="invalid_admin_key")


def to_decimal(val: Optional[str]) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:
        return None


def contest_to_dict(c: Contest) -> Dict[str, Any]:
    lock_at = ensure_aware_utc(c.lock_at) if getattr(c, "lock_at", None) else None
    created_at = ensure_aware_utc(c.created_at) if getattr(c, "created_at", None) else None
    return {
        "id": c.id,
        "title": c.title,
        "match_id": c.match_id,
        "status": c.status,
        "entry_fee": c.entry_fee,
        "team_a_name": c.team_a_name,
        "team_b_name": c.team_b_name,
        "team_a_mult": float(to_decimal(c.team_a_mult)) if c.team_a_mult is not None else None,
        "team_b_mult": float(to_decimal(c.team_b_mult)) if c.team_b_mult is not None else None,
        "lock_at": lock_at.isoformat() if lock_at else None,
        "created_at": created_at.isoformat() if created_at else None,
    }


# -----------------------------
# INTERNAL: settle_contest_internal
# -----------------------------
def settle_contest_internal(
    db: Session,
    contest_id: str,
    winner_pick: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    winner_pick = (winner_pick or "").strip().upper()
    if winner_pick not in ("A", "B"):
        raise HTTPException(status_code=400, detail="invalid_winner_pick")

    c: Contest = db.query(Contest).filter(Contest.id == contest_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="contest_not_found")

    existing = db.query(ContestResult).filter(ContestResult.contest_id == contest_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="already_settled")

    entries: List[ContestEntry] = (
        db.query(ContestEntry).filter(ContestEntry.contest_id == contest_id).all()
    )

    settled_count = 0
    winners = 0
    n = now_utc()

    for e in entries:
        if e.result != "pending":
            continue

        if (e.pick or "").upper() == winner_pick:
            mult = to_decimal(e.locked_mult) or Decimal("0")
            payout = int(Decimal(int(e.stake)) * mult)

            u: Optional[User] = db.query(User).filter(User.id == e.user_id).first()
            if u:
                u.coins_balance = (u.coins_balance or 0) + payout
                db.add(u)
                db.add(
                    CoinLedger(
                        user_id=u.id,
                        delta=payout,
                        reason="contest_win",
                        ref_type="contest",
                        ref_id=contest_id,
                    )
                )

            e.result = "won"
            e.coins_won = payout
            e.settled_at = n
            winners += 1
        else:
            e.result = "lost"
            e.coins_won = 0
            e.settled_at = n

        db.add(e)
        settled_count += 1

    result_kwargs = dict(
        id=f"result_{uuid.uuid4().hex[:12]}",
        contest_id=contest_id,
        match_id=c.match_id,
        winner_pick=winner_pick,
        status="settled",
        settled_at=n,
    )

    try:
        if hasattr(ContestResult, "notes"):
            result_kwargs["notes"] = notes
    except Exception:
        pass

    r = ContestResult(**result_kwargs)

    c.status = "settled"
    db.add(r)
    db.add(c)

    db.commit()

    return {
        "contest_id": contest_id,
        "winner": winner_pick,
        "settled_count": settled_count,
        "winners": winners,
    }


# -----------------------------
# DB dependency
# -----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------------
# Schemas
# -----------------------------
class PredictBody(BaseModel):
    pick: str = Field(..., pattern="^[AB]$")
    stake: int = Field(..., ge=1)


class CreateContestBody(BaseModel):
    title: str
    match_id: str
    entry_fee: int = Field(..., ge=0)
    team_a_name: str = "TEAM_A"
    team_b_name: str = "TEAM_B"
    team_a_mult: float = 1.5
    team_b_mult: float = 2.0
    lock_at: str


class SettleBody(BaseModel):
    winner: str = Field(..., pattern="^[AB]$")


# -----------------------------
# Debug: DB time
# -----------------------------
@router.get("/debug/db-time")
def debug_db_time(db: Session = Depends(get_db)):
    db_now = db.execute(func.now()).scalar()
    return {"app_now_utc": now_utc().isoformat(), "db_now": str(db_now)}


# -----------------------------
# Public: list contests by match_id
# -----------------------------
@router.get("")
def list_contests(match_id: str, db: Session = Depends(get_db)):
    ensure_default_contests_for_match(db, match_id)

    contests: List[Contest] = (
        db.query(Contest)
        .filter(Contest.match_id == match_id)
        .order_by(Contest.entry_fee.asc())
        .all()
    )
    return [contest_to_dict(c) for c in contests]


# -----------------------------
# Admin: create contest
# -----------------------------
@router.post("/admin/create")
def admin_create_contest(
    body: CreateContestBody,
    x_admin_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    require_admin(x_admin_key)

    try:
        lock_at = datetime.fromisoformat(body.lock_at.replace("Z", "+00:00"))
        if lock_at.tzinfo is None:
            lock_at = lock_at.replace(tzinfo=timezone.utc)
        else:
            lock_at = lock_at.astimezone(timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_lock_at")

    contest_id = f"contest_{uuid.uuid4().hex[:10]}"

    c = Contest(
        id=contest_id,
        title=body.title,
        match_id=body.match_id,
        entry_fee=body.entry_fee,
        team_a_name=body.team_a_name,
        team_b_name=body.team_b_name,
        team_a_mult=str(body.team_a_mult),
        team_b_mult=str(body.team_b_mult),
        lock_at=lock_at,
        status="open",
    )
    db.add(c)
    db.commit()

    return {"message": "contest_created", "contest_id": contest_id}


# -----------------------------
# Protected: predict (join/update pick)
# -----------------------------
@router.post("/{contest_id}/predict")
def predict_contest(
    contest_id: str,
    body: PredictBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c: Contest = db.query(Contest).filter(Contest.id == contest_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="contest_not_found")

    n = now_utc()
    lock_at = ensure_aware_utc(c.lock_at) if getattr(c, "lock_at", None) else None
    if c.status != "open" or (lock_at and lock_at <= n):
        raise HTTPException(status_code=403, detail="contest_is_locked")

    u: User = user
    user_id = str(u.id)

    if c.entry_fee > 0 and body.stake != c.entry_fee:
        raise HTTPException(status_code=400, detail="stake_must_equal_entry_fee")

    e: Optional[ContestEntry] = (
        db.query(ContestEntry)
        .filter(ContestEntry.contest_id == contest_id, ContestEntry.user_id == user_id)
        .first()
    )

    mult = to_decimal(c.team_a_mult) if body.pick == "A" else to_decimal(c.team_b_mult)
    if mult is None:
        raise HTTPException(status_code=400, detail="multiplier_not_set")

    if e is None:
        if (u.coins_balance or 0) < body.stake:
            raise HTTPException(status_code=400, detail="insufficient_coins")

        entry_id = f"entry_{uuid.uuid4().hex[:12]}"
        e = ContestEntry(
            id=entry_id,
            contest_id=contest_id,
            match_id=c.match_id,
            user_id=user_id,
            pick=body.pick,
            stake=body.stake,
            locked_mult=str(mult),
            result="pending",
            coins_won=0,
        )

        u.coins_balance = (u.coins_balance or 0) - body.stake
        db.add(e)
        db.add(
            CoinLedger(
                user_id=u.id,
                delta=-body.stake,
                reason="join_contest",
                ref_type="contest",
                ref_id=contest_id,
            )
        )
        db.commit()

        return {
            "message": "entry_created",
            "contest_id": contest_id,
            "entry_id": entry_id,
            "coins_left": u.coins_balance,
        }

    e.pick = body.pick
    e.locked_mult = str(mult)
    db.add(e)
    db.commit()

    return {
        "message": "updated_pick",
        "contest_id": contest_id,
        "entry_id": e.id,
        "coins_left": u.coins_balance,
    }


# -----------------------------
# Protected: my entry in a contest
# -----------------------------
@router.get("/{contest_id}/my-entry")
def my_entry(
    contest_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    e: Optional[ContestEntry] = (
        db.query(ContestEntry)
        .filter(
            ContestEntry.contest_id == contest_id,
            ContestEntry.user_id == str(current_user.id),
        )
        .first()
    )

    if not e:
        return {"contest_id": contest_id, "has_entry": False, "entry": None}

    return {
        "contest_id": contest_id,
        "has_entry": True,
        "entry": {
            "entry_id": e.id,
            "user_id": e.user_id,
            "match_id": e.match_id,
            "pick": e.pick,
            "stake": e.stake,
            "locked_mult": e.locked_mult,
            "result": e.result,
            "coins_won": e.coins_won,
            "settled_at": e.settled_at.isoformat() if e.settled_at else None,
            "created_at": e.created_at.isoformat() if getattr(e, "created_at", None) else None,
        },
    }


# -----------------------------
# Protected: my contests list
# -----------------------------
@router.get("/my")
def my_contests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
):
    limit = min(max(limit, 1), 200)

    entries: List[ContestEntry] = (
        db.query(ContestEntry)
        .filter(ContestEntry.user_id == str(current_user.id))
        .order_by(ContestEntry.created_at.desc())
        .limit(limit)
        .all()
    )

    if not entries:
        return []

    contest_ids = [e.contest_id for e in entries]
    contests: List[Contest] = db.query(Contest).filter(Contest.id.in_(contest_ids)).all()
    contest_map = {c.id: c for c in contests}

    out = []
    for e in entries:
        c = contest_map.get(e.contest_id)
        out.append(
            {
                "contest_id": e.contest_id,
                "entry_id": e.id,
                "match_id": e.match_id,
                "pick": e.pick,
                "stake": e.stake,
                "result": e.result,
                "coins_won": e.coins_won,
                "locked_mult": e.locked_mult,
                "settled_at": e.settled_at.isoformat() if e.settled_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "contest": contest_to_dict(c) if c else None,
            }
        )

    return out


# -----------------------------
# INTERNAL: lock due contests
# -----------------------------
def lock_due_internal(db: Session) -> int:
    n = now_utc()

    rows: List[Contest] = (
        db.query(Contest)
        .filter(Contest.status == "open")
        .filter(Contest.lock_at.isnot(None))
        .filter(Contest.lock_at <= n)
        .all()
    )

    locked = 0
    for c in rows:
        c.status = "locked"
        db.add(c)
        locked += 1

    if locked:
        db.commit()

    return locked


# -----------------------------
# Admin: lock due contests
# -----------------------------
@router.post("/admin/lock-due")
def admin_lock_due(
    x_admin_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    require_admin(x_admin_key)
    locked = lock_due_internal(db)
    return {"message": "ok", "locked_count": locked}


# -----------------------------
# Admin: settle contest
# -----------------------------
@router.post("/admin/{contest_id}/settle")
def admin_settle(
    contest_id: str,
    body: SettleBody,
    x_admin_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    require_admin(x_admin_key)
    res = settle_contest_internal(db, contest_id, body.winner, notes="admin_settle")
    return {"message": "settled", **res}


# -----------------------------
# Admin: refund contest
# -----------------------------
@router.post("/admin/{contest_id}/refund")
def admin_refund(
    contest_id: str,
    x_admin_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    require_admin(x_admin_key)

    c: Contest = db.query(Contest).filter(Contest.id == contest_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="contest_not_found")

    if c.status in ("settled", "refunded"):
        raise HTTPException(status_code=400, detail="cannot_refund_in_this_state")

    entries: List[ContestEntry] = (
        db.query(ContestEntry).filter(ContestEntry.contest_id == contest_id).all()
    )

    refunded = 0
    n = now_utc()

    for e in entries:
        if e.result != "pending":
            continue

        u: Optional[User] = db.query(User).filter(User.id == e.user_id).first()
        if u:
            amt = int(e.stake)
            u.coins_balance = (u.coins_balance or 0) + amt
            db.add(u)
            db.add(
                CoinLedger(
                    user_id=u.id,
                    delta=amt,
                    reason="contest_refund",
                    ref_type="contest",
                    ref_id=contest_id,
                )
            )

        e.result = "refunded"
        e.coins_won = 0
        e.settled_at = n
        db.add(e)
        refunded += 1

    c.status = "refunded"
    db.add(c)
    db.commit()

    return {"message": "refunded", "contest_id": contest_id, "refunded_count": refunded}


# -----------------------------
# INTERNAL: auto settle locked contests
# -----------------------------
def auto_settle_due_internal(db: Session) -> int:
    from app.providers.sportmonks import (
        get_fixture,
        is_fixture_finished,
        get_fixture_winner_pick,
    )

    locked_contests: List[Contest] = (
        db.query(Contest)
        .filter(Contest.status == "locked")
        .limit(50)
        .all()
    )

    print(f"[auto_settle] locked_contests_found={len(locked_contests)}")

    settled = 0

    for c in locked_contests:
        try:
            print(f"[auto_settle] checking contest={c.id} match_id={c.match_id}")

            existing = (
                db.query(ContestResult)
                .filter(ContestResult.contest_id == c.id)
                .first()
            )
            if existing:
                print(f"[auto_settle] skip already settled contest={c.id}")
                continue

            state: Optional[MatchLiveState] = (
                db.query(MatchLiveState)
                .filter(MatchLiveState.match_id == c.match_id)
                .first()
            )

            if not state:
                print(f"[auto_settle] skip no MatchLiveState for match_id={c.match_id}")
                continue

            if not state.sportmonks_fixture_id:
                print(f"[auto_settle] skip no fixture_id mapped for match_id={c.match_id}")
                continue

            payload = get_fixture(state.sportmonks_fixture_id)

            if not is_fixture_finished(payload):
                print(
                    f"[auto_settle] fixture not finished "
                    f"contest={c.id} fixture_id={state.sportmonks_fixture_id}"
                )
                continue

            winner = get_fixture_winner_pick(payload)
            print(
                f"[auto_settle] finished contest={c.id} "
                f"fixture_id={state.sportmonks_fixture_id} winner={winner}"
            )

            if winner not in ("A", "B"):
                print(f"[auto_settle] skip invalid winner contest={c.id}")
                continue

            settle_contest_internal(db, c.id, winner, notes="auto_settle")
            settled += 1
            print(f"[auto_settle] settled contest={c.id}")

        except Exception as e:
            db.rollback()
            print(f"[auto_settle] error contest={c.id}: {e}")

    return settled