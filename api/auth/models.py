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


class AppleOAuthIn(BaseModel):
    """Apple Sign-In : variante d'OAuthIn avec données utilisateur optionnelles.

    Apple ne renvoie le `name` qu'au PREMIER login (et uniquement si le scope
    "name" était demandé). Le frontend doit alors transmettre ces données au
    backend pour les stocker — au 2e login, on a juste le code + id_token.
    """
    code: str
    redirect_uri: str = ""
    # Données fournies par Apple au premier login uniquement, via form POST.
    # Le frontend les capture dans le callback et les envoie ici.
    first_name: str | None = None
    last_name: str | None = None
    # Optionnel : id_token reçu côté frontend (mobile/desktop natif) — évite
    # un aller-retour serveur supplémentaire si la lib native nous l'a déjà donné.
    id_token: str | None = None
