"""Helper pour formater le contexte appareil dans les prompts Claude."""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from api.schemas import DeviceContextIn


def _moment_du_jour(heure: int) -> str:
    if 5 <= heure < 12:
        return "matin"
    elif 12 <= heure < 18:
        return "apres-midi"
    elif 18 <= heure < 22:
        return "soir"
    else:
        return "nuit"


def format_device_context(ctx) -> str:
    """Formate le contexte appareil pour injection dans les prompts Claude.

    Accepte un objet Pydantic (DeviceContextIn) ou un dict brut.
    Retourne une chaine vide si le contexte est None.
    """
    if ctx is None:
        return ""
    # Support both Pydantic objects and raw dicts
    def _get(key, default=None):
        if isinstance(ctx, dict):
            return ctx.get(key, default)
        return getattr(ctx, key, default)
    moment = _moment_du_jour(_get('heure', 12))
    heure = _get('heure', 12)
    minute = _get('minute', 0)
    fuseau = _get('fuseau_horaire', '')
    ville = _get('ville', '')
    latitude = _get('latitude', None)
    longitude = _get('longitude', None)
    meteo = _get('meteo', '')
    temperature = _get('temperature', 0)
    parts = [
        "\nCONTEXTE ACTUEL DE L'UTILISATEUR :",
        f"- Heure locale : {heure:02d}:{minute:02d} ({moment})"
        + (f", fuseau {fuseau}" if fuseau else ""),
    ]
    if ville:
        parts.append(
            f"- Localisation : {ville}"
            + (f" ({latitude:.4f}, {longitude:.4f})" if latitude else "")
        )
    if meteo and meteo != "Inconnu":
        parts.append(f"- Meteo : {temperature:.0f} degres C, {meteo}")
    parts.append(
        "IMPORTANT : Utilise ces informations pour contextualiser ton analyse. "
        "Par exemple, recommande des activites exterieures si le temps est favorable, "
        "ou adapte tes conseils a l'heure de la journee.\n"
    )
    return "\n".join(parts)
