from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import CoinLedger, User
from app.auth_jwt import get_current_user

router = APIRouter(prefix="/wallet", tags=["Wallet"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/balance")
def balance(user: User = Depends(get_current_user)):
    return {"user_id": str(user.id), "coins_balance": user.coins_balance}


@router.get("/ledger")
def ledger(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(CoinLedger)
        .filter(CoinLedger.user_id == user.id)
        .order_by(CoinLedger.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )

    # ✅ Running balance compute (oldest -> newest), then attach balance_after
    # We start from current user.coins_balance and walk backwards.
    running = int(user.coins_balance or 0)

    items = []
    for r in rows:
        # current running is balance AFTER this row happened (from newest walking backwards)
        items.append(
            {
                "id": str(r.id),
                "delta": int(r.delta or 0),
                "reason": r.reason,
                "ref_type": r.ref_type,
                "ref_id": r.ref_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "balance_after": running,  # ✅ this fixes Android "Balance: -"
            }
        )
        # move back in time
        running = running - int(r.delta or 0)

    return items