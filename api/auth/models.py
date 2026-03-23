"""Pydantic schemas for authentication."""

from pydantic import BaseModel, EmailStr


class RegisterIn(BaseModel):
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    email: str
    provider: str = "local"


class OAuthIn(BaseModel):
    code: str
    redirect_uri: str = ""
