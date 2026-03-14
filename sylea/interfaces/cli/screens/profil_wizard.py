"""
Assistant de création/modification du profil utilisateur.

Guide l'utilisateur à travers un questionnaire structuré pour remplir
son ProfilUtilisateur complet.
"""

from datetime import datetime
from typing import Optional

from sylea.core.models.user import (
    ProfilUtilisateur,
    Objectif,
    CATEGORIES_OBJECTIF,
    SITUATIONS_FAMILIALES,
)
from sylea.interfaces.cli.components.ui import (
    console,
    afficher_titre_section,
    afficher_succes,
    afficher_info,
    demander,
    demander_nombre,
    demander_entier,
    choisir_dans_liste,
    C_PRIMAIRE,
    C_MUTED,
)


def lancer_wizard(profil_existant: Optional[ProfilUtilisateur] = None) -> ProfilUtilisateur:
    """
    Lance le questionnaire de profil complet.

    Args:
        profil_existant: Si fourni, pré-rempli les valeurs par défaut.

    Returns:
        ProfilUtilisateur complet et validé.
    """
    p = profil_existant  # alias court pour les valeurs par défaut
    est_modification = p is not None

    if est_modification:
        console.print(f"\n[{C_PRIMAIRE}]Modification du profil[/] — Appuyez sur Entrée pour garder la valeur actuelle.\n")
    else:
        console.print(f"\n[{C_PRIMAIRE}]Bienvenue ! Configurons votre profil.[/]\n")
        console.print(
            f"[{C_MUTED}]Plus vous êtes précis, plus les analyses seront pertinentes.[/]\n"
        )

    # ── 1. Identité ──────────────────────────────────────────────────────────
    afficher_titre_section("Identité")

    nom = demander("Votre prénom / nom", defaut=p.nom if p else "")
    while not nom:
        from sylea.interfaces.cli.components.ui import afficher_erreur
        afficher_erreur("Le nom est obligatoire.")
        nom = demander("Votre prénom / nom")

    age = demander_entier(
        "Votre âge", min_val=13, max_val=120,
        defaut=p.age if p else 30,
    )
    ville = demander("Votre ville / pays", defaut=p.ville if p else "")
    ville = ville or "Non renseigné"

    console.print(f"\n[{C_MUTED}]Situation familiale :[/]")
    situation = choisir_dans_liste(
        "Choisissez", SITUATIONS_FAMILIALES,
    )

    # ── 2. Profession & finances ─────────────────────────────────────────────
    afficher_titre_section("Profession & Finances")

    profession = demander(
        "Votre profession", defaut=p.profession if p else ""
    )
    profession = profession or "Non renseigné"

    revenu_annuel = demander_nombre(
        "Revenu annuel net (€)", min_val=0,
        defaut=p.revenu_annuel if p else 30000,
    )
    patrimoine = demander_nombre(
        "Patrimoine estimé (épargne + biens, €)", min_val=0,
        defaut=p.patrimoine_estime if p else 0,
    )
    charges = demander_nombre(
        "Charges mensuelles (loyer, crédits, etc., €)", min_val=0,
        defaut=p.charges_mensuelles if p else 1000,
    )
    objectif_financier_raw = demander(
        "Objectif financier cible (€, facultatif)",
        defaut=str(int(p.objectif_financier)) if (p and p.objectif_financier) else "",
    )
    objectif_financier = (
        float(objectif_financier_raw.replace(",", ".").replace(" ", ""))
        if objectif_financier_raw else None
    )

    # ── 3. Temps quotidien ───────────────────────────────────────────────────
    afficher_titre_section("Organisation du temps (heures/jour)")
    afficher_info("Total idéal : 24h. Soyez honnête.")

    h_travail   = demander_nombre("Travail", min_val=0, max_val=20, defaut=p.heures_travail if p else 8)
    h_sommeil   = demander_nombre("Sommeil", min_val=3, max_val=12, defaut=p.heures_sommeil if p else 7)
    h_loisirs   = demander_nombre("Loisirs / famille", min_val=0, max_val=12, defaut=p.heures_loisirs if p else 2)
    h_transport = demander_nombre("Transports", min_val=0, max_val=6, defaut=p.heures_transport if p else 1)

    # ── 4. Auto-évaluations ──────────────────────────────────────────────────
    afficher_titre_section("Auto-évaluation (1 = très mauvais · 10 = excellent)")

    niv_sante   = demander_entier("Santé physique (/10)", 1, 10, p.niveau_sante if p else 7)
    niv_stress  = demander_entier("Niveau de stress (/10, 10 = très stressé)", 1, 10, p.niveau_stress if p else 5)
    niv_energie = demander_entier("Niveau d'énergie (/10)", 1, 10, p.niveau_energie if p else 7)
    niv_bonheur = demander_entier("Satisfaction de vie (/10)", 1, 10, p.niveau_bonheur if p else 7)

    # ── 5. Compétences & formation ───────────────────────────────────────────
    afficher_titre_section("Compétences & Formation")

    afficher_info("Listez vos compétences clés séparées par des virgules.")
    afficher_info("Ex : négociation, Python, leadership, finance, marketing")
    competences_raw = demander(
        "Vos compétences",
        defaut=", ".join(p.competences) if p else "",
    )
    competences = [c.strip() for c in competences_raw.split(",") if c.strip()] if competences_raw else []

    diplomes_raw = demander(
        "Vos diplômes (séparés par des virgules)",
        defaut=", ".join(p.diplomes) if p else "",
    )
    diplomes = [d.strip() for d in diplomes_raw.split(",") if d.strip()] if diplomes_raw else []

    langues_raw = demander(
        "Langues maîtrisées (séparées par des virgules)",
        defaut=", ".join(p.langues) if (p and p.langues) else "Français",
    )
    langues = [l.strip() for l in langues_raw.split(",") if l.strip()] if langues_raw else ["Français"]

    # ── 6. Objectif principal ────────────────────────────────────────────────
    afficher_titre_section("Objectif de vie principal")
    afficher_info("C'est l'objectif autour duquel Syléa va tout analyser.")

    objectif_description = demander(
        "Décrivez votre objectif en une phrase",
        defaut=p.objectif.description if (p and p.objectif) else "",
    )
    while not objectif_description:
        from sylea.interfaces.cli.components.ui import afficher_erreur
        afficher_erreur("L'objectif est obligatoire.")
        objectif_description = demander("Décrivez votre objectif en une phrase")

    console.print(f"\n[{C_MUTED}]Catégorie de l'objectif :[/]")
    categorie = choisir_dans_liste(
        "Choisissez",
        CATEGORIES_OBJECTIF,
    )

    deadline_raw = demander(
        "Date limite (JJ/MM/AAAA, facultatif)",
        defaut="",
    )
    deadline = None
    if deadline_raw:
        try:
            deadline = datetime.strptime(deadline_raw, "%d/%m/%Y")
        except ValueError:
            from sylea.interfaces.cli.components.ui import afficher_avertissement
            afficher_avertissement("Format de date invalide, deadline ignorée.")

    objectif = Objectif(
        description=objectif_description,
        categorie=categorie,
        deadline=deadline,
    )

    # ── Construction du profil ───────────────────────────────────────────────
    kwargs = dict(
        nom=nom,
        age=age,
        profession=profession,
        ville=ville,
        situation_familiale=situation,
        revenu_annuel=revenu_annuel,
        patrimoine_estime=patrimoine,
        charges_mensuelles=charges,
        objectif_financier=objectif_financier,
        heures_travail=h_travail,
        heures_sommeil=h_sommeil,
        heures_loisirs=h_loisirs,
        heures_transport=h_transport,
        niveau_sante=niv_sante,
        niveau_stress=niv_stress,
        niveau_energie=niv_energie,
        niveau_bonheur=niv_bonheur,
        competences=competences,
        diplomes=diplomes,
        langues=langues,
        objectif=objectif,
    )

    if est_modification:
        # Conserver l'ID et les métadonnées d'origine
        nouveau_profil = ProfilUtilisateur(**kwargs)
        nouveau_profil.id = p.id
        nouveau_profil.cree_le = p.cree_le
        nouveau_profil.probabilite_actuelle = p.probabilite_actuelle
    else:
        nouveau_profil = ProfilUtilisateur(**kwargs)

    afficher_succes("Profil enregistré !")
    return nouveau_profil
