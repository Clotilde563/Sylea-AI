"""Helper pour formater le contexte appareil et le contexte utilisateur complet."""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from api.schemas import DeviceContextIn
    from sylea.core.storage.database import DatabaseManager
    from sylea.core.models.user import ProfilUtilisateur


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


def build_full_user_context(
    db=None,
    user_id: str | None = None,
    profil=None,
    include_collected_info: bool = True,
    include_decisions: bool = True,
    include_sous_objectifs: bool = True,
    max_decisions: int = 10,
) -> str:
    """Build a comprehensive user context string for ANY AI feature.

    This is the SINGLE SOURCE OF TRUTH for user context.
    ALL AI features MUST use this function.

    Args:
        db: DatabaseManager instance (optional, needed for collected_info/decisions/sous_objectifs)
        user_id: auth_user_id for DB lookups (optional)
        profil: ProfilUtilisateur instance (optional, loaded from DB if not provided)
        include_collected_info: include agent_collected_info table data
        include_decisions: include recent decisions history
        include_sous_objectifs: include sub-objectives
        max_decisions: max number of recent decisions to include

    Returns:
        Formatted context string, or empty string if no profile found.
    """
    from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

    if profil is None and db is not None:
        repo = ProfilRepository(db)
        if not repo.existe(auth_user_id=user_id):
            return ""
        profil = repo.charger(auth_user_id=user_id)
    if profil is None:
        return ""

    lines = []

    # 1. Basic profile
    lines.append("PROFIL UTILISATEUR :")
    lines.append(f"  Nom : {profil.nom}")
    lines.append(f"  Age : {profil.age} ans")
    lines.append(f"  Genre : {getattr(profil, 'genre', '') or 'Non renseigne'}")
    lines.append(f"  Profession : {profil.profession}")
    lines.append(f"  Ville : {profil.ville or 'Non renseigne'}")
    lines.append(f"  Situation familiale : {profil.situation_familiale or 'Non renseigne'}")

    # 2. Objective
    if profil.objectif:
        obj = profil.objectif
        lines.append("\nOBJECTIF DE VIE :")
        desc = obj.description or ""
        if "--- Contexte personnalise ---" in desc:
            main_desc, qa_context = desc.split("--- Contexte personnalise ---", 1)
            lines.append(f"  Description : {main_desc.strip()}")
            lines.append(f"  Categorie : {obj.categorie}")
            if obj.deadline:
                lines.append(f"  Deadline : {obj.deadline}")
            lines.append("\nREPONSES PERSONNALISEES DE L'UTILISATEUR :")
            lines.append(f"  {qa_context.strip()}")
        else:
            lines.append(f"  Description : {desc}")
            lines.append(f"  Categorie : {obj.categorie}")
            if obj.deadline:
                lines.append(f"  Deadline : {obj.deadline}")

    # 3. Probability
    prob_calc = getattr(profil.objectif, 'probabilite_calculee', 0) if profil.objectif else 0
    prob_totale = profil.probabilite_actuelle + prob_calc
    lines.append("\nPROGRESSION :")
    lines.append(f"  Probabilite actuelle : {prob_totale:.1f}%")

    # 4. Financial info
    rev = getattr(profil, 'revenu_annuel', None)
    pat = getattr(profil, 'patrimoine_estime', None)
    charges = getattr(profil, 'charges_mensuelles', None)
    if rev or pat or charges:
        lines.append("\nFINANCES :")
        if rev:
            lines.append(f"  Revenu annuel : {rev}")
        if pat:
            lines.append(f"  Patrimoine estime : {pat}")
        if charges:
            lines.append(f"  Charges mensuelles : {charges}")

    # 5. Time allocations
    h_travail = getattr(profil, 'heures_travail', None)
    h_sommeil = getattr(profil, 'heures_sommeil', None)
    h_loisirs = getattr(profil, 'heures_loisirs', None)
    h_transport = getattr(profil, 'heures_transport', None)
    h_objectif = getattr(profil, 'heures_objectif', None)
    if any([h_travail, h_sommeil, h_loisirs, h_transport, h_objectif]):
        lines.append("\nALLOCATION DU TEMPS QUOTIDIEN :")
        if h_travail:
            lines.append(f"  Travail : {h_travail}h/jour")
        if h_sommeil:
            lines.append(f"  Sommeil : {h_sommeil}h/jour")
        if h_loisirs:
            lines.append(f"  Loisirs : {h_loisirs}h/jour")
        if h_transport:
            lines.append(f"  Transport : {h_transport}h/jour")
        if h_objectif:
            lines.append(f"  Temps pour l'objectif : {h_objectif}h/jour")

    # 6. Well-being scores
    sante = getattr(profil, 'niveau_sante', None)
    stress = getattr(profil, 'niveau_stress', None)
    energie = getattr(profil, 'niveau_energie', None)
    bonheur = getattr(profil, 'niveau_bonheur', None)
    if any([sante, stress, energie, bonheur]):
        lines.append("\nBIEN-ETRE (scores sur 10) :")
        if sante:
            lines.append(f"  Sante : {sante}/10")
        if stress:
            lines.append(f"  Stress : {stress}/10")
        if energie:
            lines.append(f"  Energie : {energie}/10")
        if bonheur:
            lines.append(f"  Bonheur : {bonheur}/10")

    # 7. Skills
    comp = getattr(profil, 'competences', None) or []
    dipl = getattr(profil, 'diplomes', None) or []
    lang = getattr(profil, 'langues', None) or []
    if comp or dipl or lang:
        lines.append("\nCOMPETENCES :")
        if comp:
            lines.append(f"  Competences : {', '.join(comp) if isinstance(comp, list) else comp}")
        if dipl:
            lines.append(f"  Diplomes : {', '.join(dipl) if isinstance(dipl, list) else dipl}")
        if lang:
            lines.append(f"  Langues : {', '.join(lang) if isinstance(lang, list) else lang}")

    # 8. agent_collected_info
    if include_collected_info and db is not None and user_id:
        try:
            rows = db.conn.execute(
                "SELECT field, value FROM agent_collected_info WHERE user_id = ? ORDER BY collected_at DESC LIMIT 30",
                (user_id,),
            ).fetchall()
            if rows:
                lines.append("\nINFORMATIONS COLLECTEES PAR L'AGENT :")
                for field, value in rows:
                    lines.append(f"  {field} : {value}")
        except Exception:
            pass

    # 9. Recent decisions
    if include_decisions and db is not None:
        try:
            dec_repo = DecisionRepository(db)
            if user_id:
                decisions = dec_repo.lister_pour_utilisateur(
                    profil.id, max_decisions, auth_user_id=user_id
                )
            else:
                decisions = dec_repo.lister_pour_utilisateur(profil.id, max_decisions)
            if decisions:
                lines.append(f"\nDERNIERES DECISIONS ({min(len(decisions), max_decisions)}) :")
                for d in decisions[:max_decisions]:
                    chosen = d.get_option_choisie()
                    choix_desc = chosen.description if chosen else "?"
                    impact = (
                        (d.probabilite_apres - d.probabilite_avant)
                        if d.probabilite_apres is not None
                        else 0
                    )
                    lines.append(f"  - {d.question} -> {choix_desc} (impact: {impact:+.2f}%)")
        except Exception:
            pass

    # 10. Sub-objectives
    if include_sous_objectifs and db is not None:
        try:
            profil_id_row = db.conn.execute(
                "SELECT id FROM profil_utilisateur WHERE id = ? LIMIT 1",
                (profil.id,),
            ).fetchone()
            if profil_id_row:
                so_rows = db.conn.execute(
                    "SELECT titre, progression FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
                    (profil.id,),
                ).fetchall()
                if so_rows:
                    lines.append("\nSOUS-OBJECTIFS :")
                    for so in so_rows:
                        lines.append(f"  - {so[0]} (progression: {so[1]:.0f}%)")
        except Exception:
            pass

    return "\n".join(lines)
