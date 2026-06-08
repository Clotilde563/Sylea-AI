"""Pydantic schemas for authentication."""

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    # P3 (2026-06) : EmailStr valide le format RFC a l'inscription (avant,
    # l'import EmailStr etait mort et `email: str` acceptait n'importe quoi).
    # Requiert le package `email-validator` (ajoute a requirements.txt).
    email: EmailStr
    # Borne la longueur (anti-DoS paste) ; min 4 conserve (compat existant).
    password: str = Field(min_length=4, max_length=256)


class LoginIn(BaseModel):
    # Login : on garde `str` (pas EmailStr) pour renvoyer un 401 generique
    # plutot qu'un 422 revelateur sur email malforme (anti-enumeration).
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


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
