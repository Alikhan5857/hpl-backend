from pydantic import BaseModel, Field

class SendOtpIn(BaseModel):
    phone: str = Field(min_length=10, max_length=15)

class VerifyOtpIn(BaseModel):
    phone: str = Field(min_length=10, max_length=15)
    otp: str = Field(min_length=4, max_length=6)

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"