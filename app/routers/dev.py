# app/routers/dev.py
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import User, CoinLedger

router = APIRouter(prefix="/dev", tags=["dev"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class TopupBody(BaseModel):
    user_id: str
    amount: int = Field(..., gt=0)

@router.post("/topup")
def topup(
    body: TopupBody,
    db: Session = Depends(get_db),
):
    # dev guard
    if os.getenv("DEV_MODE", "0") != "1":
        raise HTTPException(status_code=403, detail="DEV_MODE disabled")

    u = db.query(User).filter(User.id == body.user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="user_not_found")

    # balance update
    u.coins_balance += body.amount
    db.add(u)

    # ledger entry
    db.add(
        CoinLedger(
            user_id=body.user_id,
            delta=body.amount,
            reason="dev_topup",
            ref_type="dev",
            ref_id=None,
            created_at=datetime.now(timezone.utc),
        )
    )

    db.commit()
    return {"ok": True, "user_id": str(u.id), "credited": body.amount, "new_balance": u.coins_balance}