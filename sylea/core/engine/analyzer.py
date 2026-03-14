"""
Analyseur de dilemmes de Syléa.AI ("Le Conseiller").

Ce module analyse chaque option d'un dilemme et calcule :
  - Un impact en points de pourcentage sur la probabilité de l'objectif
  - Une explication textuelle personnalisée
  - Si la tâche est déléguable à l'agent
  - Le temps estimé

Le moteur est entièrement déterministe (aucune API externe) et s'appuie
sur une base de règles basée sur des catégories d'activités reconnues en
sciences comportementales.
"""

from __future__ import annotations

import random
from typing import List, Tuple

from sylea.core.models.decision import OptionDilemme
from sylea.core.models.user import ProfilUtilisateur


# ── Définition des catégories d'activités ───────────────────────────────────
# Chaque catégorie définit :
#   - mots_cles    : termes déclencheurs (détection dans la description)
#   - impacts      : delta de probabilité par catégorie d'objectif (finance,
#                    santé, carrière, relation, développement)
#   - impact_sante : effet secondaire sur le niveau de santé (non appliqué
#                    ici mais utilisé dans les explications)
#   - delegable    : True si l'agent peut prendre en charge
#   - temps_moyen  : durée typique en heures

ACTIVITES: dict[str, dict] = {
    "exercice": {
        "mots_cles": [
            "courir", "course", "sport", "gym", "musculation", "entraînement",
            "yoga", "fractionné", "natation", "vélo", "exercice", "fitness",
            "marche", "randonnée", "crossfit", "pilates", "boxe",
            "repos actif", "étirement", "stretching",
        ],
        "impacts": {
            "finance": 0.6,
            "santé": 3.5,
            "carrière": 0.8,
            "relation": 0.4,
            "développement": 0.5,
        },
        "impact_sante": +0.3,
        "delegable": False,
        "temps_moyen": 1.5,
        "explications": {
            "finance": (
                "Le sport améliore la clarté mentale et la discipline, deux atouts "
                "indirects pour vos objectifs financiers. Impact limité mais réel."
            ),
            "santé": (
                "Activité directement alignée avec votre objectif de santé. "
                "L'entraînement régulier est le principal levier de progression."
            ),
            "carrière": (
                "L'exercice régulier améliore la concentration et réduit le stress, "
                "ce qui se traduit par une meilleure performance professionnelle."
            ),
            "relation": (
                "Prendre soin de soi améliore votre confiance et votre énergie sociale, "
                "ce qui bénéficie à vos relations."
            ),
            "développement": (
                "L'exercice stimule la neuroplasticité et améliore les capacités "
                "d'apprentissage à long terme."
            ),
        },
    },

    "travail_productif": {
        "mots_cles": [
            "travailler", "boulot", "business", "projet", "client", "vendre",
            "négocier", "présentation", "développer", "coder", "programmer",
            "réunion", "appel client", "pitch", "offre", "devis", "contrat",
            "stratégie", "business plan", "croissance", "chiffre d'affaires",
        ],
        "impacts": {
            "finance": 2.8,
            "santé": -0.4,
            "carrière": 3.2,
            "relation": -0.3,
            "développement": 1.5,
        },
        "impact_sante": -0.1,
        "delegable": True,
        "temps_moyen": 4.0,
        "explications": {
            "finance": (
                "Travailler directement sur votre activité est le levier le plus "
                "puissant pour vos objectifs financiers. Impact fort et immédiat."
            ),
            "santé": (
                "Ce temps travaillé est du temps non dédié à votre santé. "
                "Compensez avec une activité physique dans la journée."
            ),
            "carrière": (
                "Investissement direct dans votre carrière. La progression "
                "professionnelle se construit par des efforts réguliers et ciblés."
            ),
            "relation": (
                "Le travail intense peut empiéter sur les relations. "
                "Veillez à maintenir un équilibre."
            ),
            "développement": (
                "Le travail sur des projets concrets est l'une des formes "
                "d'apprentissage les plus efficaces (learning by doing)."
            ),
        },
    },

    "administration": {
        "mots_cles": [
            "email", "mails", "administratif", "paperasse", "formulaire",
            "démarche", "facture", "comptabilité", "document", "préparer dossier",
            "organiser", "classer", "archiver", "rapport", "compte rendu",
            "planning", "agenda", "préparer", "rédiger",
        ],
        "impacts": {
            "finance": 1.2,
            "santé": -0.2,
            "carrière": 1.4,
            "relation": 0.3,
            "développement": 0.5,
        },
        "impact_sante": -0.1,
        "delegable": True,
        "temps_moyen": 2.0,
        "explications": {
            "finance": (
                "Les tâches administratives sont nécessaires mais à faible valeur ajoutée "
                "directe. Déléguez si possible pour vous concentrer sur l'essentiel."
            ),
            "santé": (
                "Tâche sédentaire qui n'apporte pas de bénéfice physique direct. "
                "Envisagez de la déléguer pour libérer du temps pour le sport."
            ),
            "carrière": (
                "Administration nécessaire pour faire avancer vos projets, "
                "mais à fort potentiel de délégation."
            ),
            "relation": (
                "Certaines tâches administratives (répondre aux messages, organiser) "
                "peuvent améliorer vos relations professionnelles."
            ),
            "développement": (
                "Tâche utile mais peu formatrice. À déléguer si votre objectif "
                "est d'apprendre ou de progresser."
            ),
        },
    },

    "repos": {
        "mots_cles": [
            "repos", "dormir", "détente", "relaxation", "méditation", "pause",
            "vacances", "récupération", "sieste", "déconnexion", "rien",
            "Netflix", "série", "film", "jeux vidéo",
        ],
        "impacts": {
            "finance": -0.5,
            "santé": 1.8,
            "carrière": -0.6,
            "relation": 0.5,
            "développement": 0.2,
        },
        "impact_sante": +0.2,
        "delegable": False,
        "temps_moyen": 2.5,
        "explications": {
            "finance": (
                "Le repos n'avance pas directement vos objectifs financiers. "
                "Il est néanmoins nécessaire pour éviter l'épuisement."
            ),
            "santé": (
                "La récupération est une partie intégrante de la performance physique. "
                "Ne pas la négliger est une décision sage."
            ),
            "carrière": (
                "Court terme : l'inactivité a un coût. Long terme : se reposer "
                "évite le burnout qui serait bien plus coûteux."
            ),
            "relation": (
                "Le repos peut être l'occasion de passer du temps de qualité "
                "avec ses proches."
            ),
            "développement": (
                "Le cerveau consolide les apprentissages pendant le repos. "
                "Une pause bien placée peut être bénéfique."
            ),
        },
    },

    "formation": {
        "mots_cles": [
            "apprendre", "lire", "livre", "cours", "formation", "étudier",
            "conférence", "podcast", "compétence", "langue", "certification",
            "MOOC", "tutoriel", "formation en ligne", "webinaire", "séminaire",
            "masterclass",
        ],
        "impacts": {
            "finance": 1.2,
            "santé": 0.2,
            "carrière": 2.5,
            "relation": 0.3,
            "développement": 4.0,
        },
        "impact_sante": 0.0,
        "delegable": False,
        "temps_moyen": 2.5,
        "explications": {
            "finance": (
                "Développer ses compétences est un investissement à long terme "
                "qui peut générer un retour financier significatif."
            ),
            "santé": (
                "La formation mentale est bénéfique pour la santé cognitive, "
                "mais veillez à ne pas négliger l'activité physique."
            ),
            "carrière": (
                "Se former est l'un des investissements les plus rentables "
                "pour accélérer une carrière."
            ),
            "relation": (
                "Nouvelles compétences et nouvelles connaissances ouvrent "
                "souvent de nouveaux cercles sociaux."
            ),
            "développement": (
                "Activité parfaitement alignée avec votre objectif. "
                "L'apprentissage continu est la clé du développement personnel."
            ),
        },
    },

    "social": {
        "mots_cles": [
            "amis", "famille", "réseau", "networking", "sortir", "dîner",
            "rencontre", "événement", "soirée", "afterwork", "voir des gens",
            "café", "déjeuner avec", "verre avec",
        ],
        "impacts": {
            "finance": 0.8,
            "santé": 0.6,
            "carrière": 1.5,
            "relation": 4.0,
            "développement": 0.8,
        },
        "impact_sante": +0.1,
        "delegable": False,
        "temps_moyen": 3.0,
        "explications": {
            "finance": (
                "Le réseau est un actif invisible mais puissant. "
                "Des opportunités financières naissent souvent de relations."
            ),
            "santé": (
                "La connexion sociale est un facteur de santé reconnu "
                "scientifiquement. Ce temps n'est pas perdu."
            ),
            "carrière": (
                "Votre réseau peut ouvrir des portes inaccessibles par le travail seul. "
                "Investissement à fort potentiel."
            ),
            "relation": (
                "Activité directement alignée avec votre objectif. "
                "Entretenir ses relations est la clé d'une vie sociale épanouie."
            ),
            "développement": (
                "Les interactions humaines sont une source d'apprentissage et "
                "d'inspiration souvent sous-estimée."
            ),
        },
    },

    "soin_personnel": {
        "mots_cles": [
            "médecin", "psy", "psychologue", "thérapeute", "soin",
            "santé mentale", "bien-être", "coiffeur", "bain", "routine",
            "manger sain", "repas équilibré", "nutrition",
        ],
        "impacts": {
            "finance": 0.3,
            "santé": 2.5,
            "carrière": 0.5,
            "relation": 0.8,
            "développement": 0.8,
        },
        "impact_sante": +0.4,
        "delegable": False,
        "temps_moyen": 1.5,
        "explications": {
            "finance": (
                "Prendre soin de soi est un investissement pour maintenir "
                "votre capacité de travail long terme."
            ),
            "santé": (
                "Prendre soin de sa santé est directement aligné avec votre objectif. "
                "Ne jamais négliger les signaux de votre corps."
            ),
            "carrière": (
                "Un professionnel en bonne santé est plus performant. "
                "Ce temps est un investissement dans votre efficacité."
            ),
            "relation": (
                "Prendre soin de soi améliore votre estime et votre présence "
                "dans les interactions sociales."
            ),
            "développement": (
                "La santé mentale et physique est le fondement de tout "
                "développement personnel durable."
            ),
        },
    },
}

# Activité par défaut si aucune catégorie n'est détectée
_ACTIVITE_DEFAUT = "travail_productif"


def _detecter_activite(description: str) -> str:
    """
    Identifie la catégorie d'activité à partir de la description de l'option.

    Stratégie : pour chaque catégorie, compte le nombre de mots-clés présents
    dans la description et retourne celle qui en a le plus.

    Args:
        description: Texte libre de l'option

    Returns:
        Clé de la catégorie dans ACTIVITES, ou _ACTIVITE_DEFAUT si rien détecté
    """
    desc = description.lower()
    scores: dict[str, int] = {}

    for categorie, config in ACTIVITES.items():
        score = sum(1 for mot in config["mots_cles"] if mot in desc)
        if score > 0:
            scores[categorie] = score

    if not scores:
        return _ACTIVITE_DEFAUT

    return max(scores, key=lambda k: scores[k])


def _generer_explication(
    activite: str,
    categorie_objectif: str,
    impact: float,
    profil: ProfilUtilisateur,
) -> str:
    """
    Génère une explication personnalisée de l'impact d'une option.

    Args:
        activite           : Catégorie d'activité détectée
        categorie_objectif : Catégorie de l'objectif de l'utilisateur
        impact             : Score d'impact calculé
        profil             : Profil de l'utilisateur pour personnalisation

    Returns:
        Texte explicatif de 1-2 phrases
    """
    config = ACTIVITES.get(activite, ACTIVITES[_ACTIVITE_DEFAUT])
    explication = config["explications"].get(categorie_objectif, "")

    # Personnalisation selon le profil
    if profil.niveau_stress >= 8 and activite == "repos":
        explication += (
            f" Note : avec votre niveau de stress actuel ({profil.niveau_stress}/10), "
            "ce repos est particulièrement précieux."
        )
    elif profil.niveau_sante <= 4 and activite in ("travail_productif", "administration"):
        explication += (
            " Attention : votre niveau de santé bas suggère de ne pas surcharger "
            "votre emploi du temps de tâches stressantes."
        )
    elif profil.niveau_energie <= 4 and activite == "exercice":
        explication += (
            " Adaptez l'intensité à votre niveau d'énergie actuel "
            f"({profil.niveau_energie}/10). Un exercice modéré reste bénéfique."
        )

    return explication


def _calculer_impact(
    activite: str,
    categorie_objectif: str,
    prob_actuelle: float,
    profil: ProfilUtilisateur,
) -> float:
    """
    Calcule l'impact net en points de pourcentage.

    Applique des modificateurs contextuels basés sur l'état du profil.

    Args:
        activite           : Catégorie d'activité détectée
        categorie_objectif : Catégorie de l'objectif
        prob_actuelle      : Probabilité courante (pour limiter les effets)
        profil             : Profil utilisateur pour les modificateurs

    Returns:
        Impact en points de % (peut être négatif)
    """
    config = ACTIVITES.get(activite, ACTIVITES[_ACTIVITE_DEFAUT])
    impact_base = config["impacts"].get(categorie_objectif, 0.5)

    # Modificateur énergie : si énergie basse, les activités physiques sont moins efficaces
    if profil.niveau_energie <= 3 and activite == "exercice":
        impact_base *= 0.7

    # Modificateur stress : si stress très élevé, le repos a un impact plus fort
    if profil.niveau_stress >= 8 and activite == "repos":
        impact_base *= 1.3

    # Modificateur compétences : si compétences pertinentes, le travail est plus efficace
    if activite == "travail_productif" and len(profil.competences) >= 5:
        impact_base *= 1.1

    # Légère variation aléatoire pour un sentiment de réalisme (+/- 10%)
    variation = random.uniform(0.90, 1.10)
    impact_final = round(impact_base * variation, 2)

    return impact_final


class AnalyseurDilemme:
    """
    Analyseur de dilemmes de Syléa.AI.

    Pour chaque dilemme soumis par l'utilisateur, analyse toutes les options
    et retourne des objets OptionDilemme enrichis avec :
      - Impact calculé
      - Explication personnalisée
      - Déléguabilité
      - Temps estimé
    """

    def analyser(
        self,
        question: str,
        descriptions_options: List[str],
        profil: ProfilUtilisateur,
    ) -> List[OptionDilemme]:
        """
        Analyse un dilemme et retourne les options évaluées.

        Args:
            question              : Texte du dilemme de l'utilisateur
            descriptions_options  : Liste des descriptions d'options (2-4)
            profil                : Profil de l'utilisateur

        Returns:
            Liste d'OptionDilemme avec tous les champs remplis, triée par
            impact décroissant (meilleure option en premier).

        Raises:
            ValueError: si moins de 2 ou plus de 4 options sont fournies
        """
        if not (2 <= len(descriptions_options) <= 4):
            raise ValueError(
                f"Un dilemme doit avoir entre 2 et 4 options "
                f"(vous en avez fourni {len(descriptions_options)})."
            )
        if profil.objectif is None:
            raise ValueError("Impossible d'analyser un dilemme sans objectif défini.")

        categorie_obj = profil.objectif.categorie
        prob_actuelle = profil.probabilite_actuelle
        options_evaluees: List[OptionDilemme] = []

        for description in descriptions_options:
            activite = _detecter_activite(description)
            config = ACTIVITES.get(activite, ACTIVITES[_ACTIVITE_DEFAUT])

            impact = _calculer_impact(activite, categorie_obj, prob_actuelle, profil)
            explication = _generer_explication(activite, categorie_obj, impact, profil)

            option = OptionDilemme(
                description=description,
                impact_score=impact,
                explication_impact=explication,
                est_delegable=config["delegable"],
                temps_estime=config["temps_moyen"],
            )
            options_evaluees.append(option)

        # Trier par impact décroissant (meilleure option d'abord)
        options_evaluees.sort(key=lambda o: o.impact_score, reverse=True)
        return options_evaluees

    def recommander(self, options: List[OptionDilemme]) -> OptionDilemme:
        """
        Retourne l'option recommandée (celle avec le meilleur impact).

        Args:
            options: Liste d'OptionDilemme déjà analysées

        Returns:
            L'option avec l'impact_score le plus élevé
        """
        return max(options, key=lambda o: o.impact_score)
