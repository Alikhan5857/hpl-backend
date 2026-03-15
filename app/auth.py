import os
import time
import random
from jose import jwt
from passlib.context import CryptContext

# ===== JWT settings =====
JWT_SECRET = os.getenv("JWT_SECRET", "dev_secret_change_me")
JWT_ALGO = "HS256"
JWT_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "2592000"))  # 30 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def make_otp() -> str:
    return str(random.randint(100000, 999999))

def hash_otp(otp: str) -> str:
    return pwd_context.hash(otp)

def verify_otp(otp: str, hashed: str) -> bool:
    return pwd_context.verify(otp, hashed)

def create_access_token(user_id: str, phone: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "phone": phone,
        "iat": now,
        "exp": now + JWT_EXPIRE_SECONDS
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)