# app/models.py
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    phone = Column(String, unique=True, index=True, nullable=False)

    name = Column(String, nullable=True)
    dob = Column(String, nullable=True)
    email = Column(String, nullable=True)

    otp_hash = Column(String, nullable=True)
    otp_expires_at = Column(DateTime(timezone=True), nullable=True)

    coins_balance = Column(Integer, nullable=False, server_default="0")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CoinLedger(Base):
    __tablename__ = "coin_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    delta = Column(Integer, nullable=False)  # +credit / -debit
    reason = Column(String, nullable=False)  # join_contest / contest_win / admin_topup etc.
    ref_type = Column(String, nullable=True) # contest/match
    ref_id = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Match(Base):
    __tablename__ = "matches"

    id = Column(String, primary_key=True, index=True)
    sportmonks_fixture_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    lock_time = Column(DateTime(timezone=True), nullable=True)

class MatchLiveState(Base):
    __tablename__ = "match_live_state"

    match_id = Column(String, primary_key=True, index=True)

    provider = Column(String, nullable=True)
    external_match_id = Column(String, nullable=True)


    # your added columns
    sportmonks_fixture_id = Column(Integer, nullable=True, index=True)
    raw = Column(JSONB, nullable=True)
    normalized = Column(JSONB, nullable=True)

    last_fetched_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class Contest(Base):
    __tablename__ = "contests"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    match_id = Column(String, index=True, nullable=False)

    entry_fee = Column(Integer, nullable=False, server_default="0")

    team_a_name = Column(String, nullable=False, server_default="TEAM_A")
    team_b_name = Column(String, nullable=False, server_default="TEAM_B")

    # stored as NUMERIC in DB (we'll handle as float/decimal in API)
    team_a_mult = Column(Text, nullable=True)  # keep Text to avoid type issues in SQLAlchemy
    team_b_mult = Column(Text, nullable=True)

    lock_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False, server_default="open")

    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class ContestEntry(Base):
    __tablename__ = "contest_entries"

    id = Column(String, primary_key=True, index=True)
    contest_id = Column(String, ForeignKey("contests.id", ondelete="CASCADE"), index=True, nullable=False)
    match_id = Column(String, index=True, nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    pick = Column(String, nullable=False)  # 'A' or 'B'
    stake = Column(Integer, nullable=False, server_default="0")
    locked_mult = Column(Text, nullable=False)  # NUMERIC snapshot

    result = Column(String, nullable=False, server_default="pending")
    coins_won = Column(Integer, nullable=False, server_default="0")

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    settled_at = Column(DateTime, nullable=True)


class ContestResult(Base):
    __tablename__ = "contest_results"

    id = Column(String, primary_key=True, index=True)
    contest_id = Column(String, ForeignKey("contests.id", ondelete="CASCADE"), unique=True, nullable=False)
    match_id = Column(String, nullable=False)

    winner_pick = Column(String, nullable=False)  # 'A' or 'B'
    status = Column(String, nullable=False, server_default="settled")
    settled_at = Column(DateTime, server_default=func.now(), nullable=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)