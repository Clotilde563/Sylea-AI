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


def format_device_context(ctx: Optional["DeviceContextIn"]) -> str:
    """Formate le contexte appareil pour injection dans les prompts Claude.

    Retourne une chaine vide si le contexte est None.
    """
    if ctx is None:
        return ""
    moment = _moment_du_jour(ctx.heure)
    parts = [
        "\nCONTEXTE ACTUEL DE L'UTILISATEUR :",
        f"- Heure locale : {ctx.heure:02d}:{ctx.minute:02d} ({moment})"
        + (f", fuseau {ctx.fuseau_horaire}" if ctx.fuseau_horaire else ""),
    ]
    if ctx.ville:
        parts.append(
            f"- Localisation : {ctx.ville}"
            + (f" ({ctx.latitude:.4f}, {ctx.longitude:.4f})" if ctx.latitude else "")
        )
    if ctx.meteo and ctx.meteo != "Inconnu":
        parts.append(f"- Meteo : {ctx.temperature:.0f} degres C, {ctx.meteo}")
    parts.append(
        "IMPORTANT : Utilise ces informations pour contextualiser ton analyse. "
        "Par exemple, recommande des activites exterieures si le temps est favorable, "
        "ou adapte tes conseils a l'heure de la journee.\n"
    )
    return "\n".join(parts)
