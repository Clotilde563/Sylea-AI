"""
SAML 2.0 SSO — Syléa.AI (stub + abstraction).

Interface unifiée pour intégration future de :
  - Okta
  - Microsoft Azure AD / Entra ID
  - Google Workspace (SAML)
  - OneLogin
  - Auth0 SAML
  - JumpCloud
  - Generic IdP via metadata XML

Workflow SP-initiated (Service Provider = Syléa.AI) :

  1. Client clique "Sign in with SSO" → POST /api/auth/saml/login
  2. Backend redirige vers IdP URL avec SAMLRequest signé
  3. IdP authentifie l'utilisateur (sur SON portail)
  4. IdP redirige client vers /api/auth/saml/acs avec SAMLResponse signé
  5. Backend valide signature, extrait email + attributs, crée/lie le compte
  6. Backend émet un JWT Syléa standard + redirige vers /

Configuration (par workspace/entreprise) :
  - sp_entity_id        : "https://api.sylea.ai" (notre URN)
  - sp_acs_url          : "https://api.sylea.ai/api/auth/saml/acs"
  - idp_entity_id       : URN fourni par le client (ex. "okta-abc123")
  - idp_sso_url         : URL de redirection IdP
  - idp_x509_cert       : certificat public du IdP (pour valider signatures)
  - attribute_mapping   : {email: "EmailAddress", name: "FullName", groups: "Groups"}

Sécurité :
  - Toutes les SAMLResponse DOIVENT être signées (`WantAssertionsSigned=true`)
  - `IssueInstant` ne doit pas dépasser ±5 min
  - `InResponseTo` doit correspondre à un SAMLRequest émis < 10 min
  - `Audience` doit matcher sp_entity_id
  - `NotBefore`/`NotOnOrAfter` respectés

Implémentation effective : nécessite `python3-saml` ou `pysaml2`. Ce module
expose juste l'interface ; l'implé concrète sera activée quand on installera
le SDK et qu'on aura un IdP à tester contre.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger("sylea.auth.saml")


# ─────────────────────────────────────────────────────────────────────────────
# Modèles
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SamlConfig:
    """Configuration SAML d'un Identity Provider (un par workspace enterprise)."""
    workspace_id: str          # workspace Syléa propriétaire de cette config
    idp_entity_id: str         # URN du IdP
    idp_sso_url: str           # URL de redirection (POST/Redirect binding)
    idp_x509_cert: str         # cert public IdP (PEM)
    sp_entity_id: str          # notre URN (ex. "https://api.sylea.ai")
    sp_acs_url: str            # ACS URL (notre callback)
    attribute_mapping: dict[str, str] = field(default_factory=lambda: {
        "email": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
        "name":  "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        "groups": "http://schemas.xmlsoap.org/claims/Group",
    })
    require_signed_assertions: bool = True
    require_signed_response: bool = True
    enforce_email_domain: str | None = None  # ex. "acme.com" pour limiter aux emails @acme.com


@dataclass
class SamlAuthnRequest:
    """SAMLRequest généré → à envoyer vers idp_sso_url."""
    saml_request_b64: str
    relay_state: str
    redirect_url: str  # URL complète avec query params (HTTP-Redirect binding)


@dataclass
class SamlAssertion:
    """Résultat de validation d'une SAMLResponse."""
    valid: bool
    email: str | None = None
    name: str | None = None
    groups: list[str] = field(default_factory=list)
    raw_attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Backend Protocol (Okta/Azure/etc.)
# ─────────────────────────────────────────────────────────────────────────────

class SamlBackend(Protocol):
    """Interface unifiée pour les implémentations SAML."""

    def build_authn_request(
        self,
        config: SamlConfig,
        relay_state: str | None = None,
    ) -> SamlAuthnRequest: ...

    def validate_response(
        self,
        config: SamlConfig,
        saml_response_b64: str,
        relay_state: str | None = None,
    ) -> SamlAssertion: ...


# ─────────────────────────────────────────────────────────────────────────────
# Stub backend (à remplacer par python3-saml en prod)
# ─────────────────────────────────────────────────────────────────────────────

class StubSamlBackend:
    """Stub no-op : retourne `valid=False`.

    Activé en l'absence de SDK SAML installé. Permet aux routes SSO d'exister
    sans crasher au boot. En prod, installer `python3-saml` et instancier
    `Python3SamlBackend` (voir TODOs).
    """

    def build_authn_request(
        self,
        config: SamlConfig,
        relay_state: str | None = None,
    ) -> SamlAuthnRequest:
        logger.warning(
            "[saml] backend STUB actif — pas de vraie implémentation. "
            "Installer python3-saml + activer Python3SamlBackend en prod."
        )
        return SamlAuthnRequest(
            saml_request_b64="",
            relay_state=relay_state or "",
            redirect_url=config.idp_sso_url + "?stub=true",
        )

    def validate_response(
        self,
        config: SamlConfig,
        saml_response_b64: str,
        relay_state: str | None = None,
    ) -> SamlAssertion:
        return SamlAssertion(
            valid=False,
            error="SAML backend STUB — pas de validation active. "
                  "Installer python3-saml en production.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Implémentation python3-saml (skeleton — activé quand SDK installé)
# ─────────────────────────────────────────────────────────────────────────────

class Python3SamlBackend:
    """Implémentation production via la lib `python3-saml` (OneLogin).

    Nécessite : `pip install python3-saml xmlsec`
    Sur Linux/macOS, xmlsec a des dépendances système (libxml2, libxmlsec1).

    Le flot complet est documenté ici ; chaque méthode importe la lib seulement
    si appelée pour ne pas crasher au boot si elle n'est pas installée.
    """

    def build_authn_request(
        self,
        config: SamlConfig,
        relay_state: str | None = None,
    ) -> SamlAuthnRequest:
        try:
            from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "python3-saml absent — installer via `pip install python3-saml`."
            ) from e

        # TODO : construire le settings dict OneLogin à partir de SamlConfig,
        # appeler OneLogin_Saml2_Auth(req).login(return_to=relay_state) pour
        # obtenir l'URL de redirection signée.
        raise NotImplementedError(
            "Python3SamlBackend.build_authn_request : à implémenter quand un "
            "client enterprise réel sera testé."
        )

    def validate_response(
        self,
        config: SamlConfig,
        saml_response_b64: str,
        relay_state: str | None = None,
    ) -> SamlAssertion:
        try:
            from onelogin.saml2.auth import OneLogin_Saml2_Auth  # type: ignore  # noqa
        except ImportError as e:
            raise RuntimeError(
                "python3-saml absent — installer via `pip install python3-saml`."
            ) from e

        # TODO : OneLogin_Saml2_Auth(req).process_response()
        # Vérifier auth.is_authenticated() + auth.get_errors()
        # Extraire auth.get_attributes() + auth.get_nameid()
        # Mapper via config.attribute_mapping
        raise NotImplementedError(
            "Python3SamlBackend.validate_response : à implémenter."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Factory + API publique
# ─────────────────────────────────────────────────────────────────────────────

_backend: SamlBackend | None = None


def get_backend() -> SamlBackend:
    """Retourne le backend SAML actif (stub par défaut, python3-saml si dispo)."""
    global _backend
    if _backend is not None:
        return _backend

    use_real = os.environ.get("SYLEA_SAML_BACKEND", "").strip().lower() in (
        "python3-saml", "production", "real"
    )

    if use_real:
        try:
            import onelogin.saml2  # type: ignore  # noqa
            _backend = Python3SamlBackend()
            logger.info("[saml] backend = python3-saml (production)")
            return _backend
        except ImportError:
            logger.warning(
                "[saml] SYLEA_SAML_BACKEND=python3-saml demandé mais SDK absent. "
                "Fallback STUB. Installer `pip install python3-saml`."
            )

    _backend = StubSamlBackend()
    logger.info("[saml] backend = STUB (no real SAML)")
    return _backend


def reset_backend() -> None:
    """Force la reconstruction (utile pour tests)."""
    global _backend
    _backend = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers d'extraction (post-validation)
# ─────────────────────────────────────────────────────────────────────────────

def extract_email(assertion: SamlAssertion, config: SamlConfig) -> str | None:
    """Retourne l'email de l'utilisateur SSO, en vérifiant la contrainte de domaine.

    Si `config.enforce_email_domain` est défini, on rejette les emails hors domaine
    (ex. évite qu'un user d'un autre tenant Okta partage le même IdP).
    """
    if not assertion.valid or not assertion.email:
        return None
    email = assertion.email.lower().strip()
    if config.enforce_email_domain:
        domain = config.enforce_email_domain.lower().lstrip("@")
        if not email.endswith(f"@{domain}"):
            logger.warning(
                "[saml] email %s rejeté : domaine attendu @%s",
                email, domain,
            )
            return None
    return email


def get_diagnostic_info() -> dict[str, Any]:
    """Diagnostic /api/health/saml — backend actif + flags."""
    backend = get_backend()
    return {
        "backend": type(backend).__name__,
        "production_mode": isinstance(backend, Python3SamlBackend),
        "env_backend": os.environ.get("SYLEA_SAML_BACKEND", "stub"),
    }
