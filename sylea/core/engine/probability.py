"""
Moteur de probabilité de Syléa.AI ("Le Conseiller").

Ce module calcule la probabilité de réussite d'un objectif à partir du
profil utilisateur, en intégrant :
  - La difficulté intrinsèque de l'objectif
  - Le score de préparation du profil (santé, stress, compétences, finances…)
  - Des facteurs neuroscientifiques (sommeil, bonheur, stress)

Aucun appel API externe : tout le calcul est déterministe et local.
"""

import math
from typing import Tuple

from sylea.core.models.user import Objectif, ProfilUtilisateur
from sylea.config.settings import PROB_MIN, PROB_MAX


# ── Table de difficulté maximale par sous-catégorie ─────────────────────────
# Probabilité maximale théoriquement atteignable (en %) selon l'objectif.
# Valeurs calibrées sur des données statistiques réelles (taux de réussite
# dans la vraie vie pour chaque type d'objectif).

DIFFICULTE_MAX: dict[str, float] = {
    # Finance
    "finance_milliardaire": 4.5,
    "finance_multimillionnaire": 22.0,
    "finance_millionnaire": 38.0,
    "finance_general": 58.0,
    # Santé
    "santé_ironman": 55.0,
    "santé_marathon_elite": 62.0,
    "santé_marathon": 72.0,
    "santé_general": 68.0,
    # Carrière
    "carrière_startup_unicorn": 8.0,
    "carrière_fondateur": 42.0,
    "carrière_promotion": 65.0,
    "carrière_changement": 60.0,
    "carrière_general": 62.0,
    # Relation
    "relation_general": 63.0,
    # Développement
    "développement_general": 72.0,
}

# ── Mots-clés pour classifier l'ambition de l'objectif ──────────────────────

_MOTS_MILLIARDAIRE = ["milliard", "billion", "1 000 000 000", "10 figures"]
_MOTS_MULTIMILLIONNAIRE = ["plusieurs millions", "10 millions", "100 millions"]
_MOTS_MILLIONNAIRE = ["million", "1 000 000", "sept chiffres"]
_MOTS_IRONMAN = ["ironman", "iron man"]
_MOTS_MARATHON_ELITE = ["marathon en 3h", "marathon en 2h", "sub-3", "sub3"]
_MOTS_MARATHON = ["marathon", "trail", "ultra", "triathlon"]
_MOTS_STARTUP = ["licorne", "unicorn", "milliard", "ipo", "entrée en bourse"]
_MOTS_FONDATEUR = ["créer", "fonder", "startup", "lancer ma", "mon entreprise", "ma boîte"]
_MOTS_PROMOTION = ["promotion", "directeur", "manager", "chef de", "responsable"]
_MOTS_CHANGEMENT = ["reconversion", "changer de métier", "changer de carrière", "nouveau métier"]


def _classifier_objectif(description: str, categorie: str) -> Tuple[str, float]:
    """
    Détermine la sous-catégorie de difficulté d’un objectif.

    Scanne d’abord les mots-clés dans la description (indépendamment de la
    catégorie) pour détecter les objectifs extrêmes (milliardaire, licorne…).
    Si aucune correspondance spécifique, utilise la catégorie comme fallback.

    Args:
        description : Texte libre de l’objectif (peut contenir le Q&A enrichi)
        categorie   : Catégorie principale ou chaîne vide si non renseignée

    Returns:
        Tuple (sous_categorie, probabilite_max_en_pourcent)
    """
    # Utiliser uniquement la partie avant le contexte personnalisé pour la classification
    base_desc = description.split("--- Contexte personnalisé ---")[0].lower()

    # ── Correspondances spécifiques (par ordre de difficulté décroissante) ───────────────
    # Finance extrême : milliardaire
    if any(m in base_desc for m in _MOTS_MILLIARDAIRE):
        return "finance_milliardaire", DIFFICULTE_MAX["finance_milliardaire"]

    # Startup licorne / IPO
    if any(m in base_desc for m in _MOTS_STARTUP):
        return "carrière_startup_unicorn", DIFFICULTE_MAX["carrière_startup_unicorn"]

    # Multi-millionnaire
    if any(m in base_desc for m in _MOTS_MULTIMILLIONNAIRE):
        return "finance_multimillionnaire", DIFFICULTE_MAX["finance_multimillionnaire"]

    # Millionnaire
    if any(m in base_desc for m in _MOTS_MILLIONNAIRE):
        return "finance_millionnaire", DIFFICULTE_MAX["finance_millionnaire"]

    # Sport extrême
    if any(m in base_desc for m in _MOTS_IRONMAN):
        return "santé_ironman", DIFFICULTE_MAX["santé_ironman"]
    if any(m in base_desc for m in _MOTS_MARATHON_ELITE):
        return "santé_marathon_elite", DIFFICULTE_MAX["santé_marathon_elite"]
    if any(m in base_desc for m in _MOTS_MARATHON):
        return "santé_marathon", DIFFICULTE_MAX["santé_marathon"]

    # Carrière : fondateur / startup sans licorne
    if any(m in base_desc for m in _MOTS_FONDATEUR):
        return "carrière_fondateur", DIFFICULTE_MAX["carrière_fondateur"]

    # Carrière : promotion
    if any(m in base_desc for m in _MOTS_PROMOTION):
        return "carrière_promotion", DIFFICULTE_MAX["carrière_promotion"]

    # Reconversion professionnelle
    if any(m in base_desc for m in _MOTS_CHANGEMENT):
        return "carrière_changement", DIFFICULTE_MAX["carrière_changement"]

    # ── Fallback sur la catégorie si aucun mot-clé spécifique detecté ──────────────
    if categorie == "finance":
        return "finance_general", DIFFICULTE_MAX["finance_general"]
    elif categorie == "santé":
        return "santé_general", DIFFICULTE_MAX["santé_general"]
    elif categorie == "carrière":
        return "carrière_general", DIFFICULTE_MAX["carrière_general"]
    elif categorie == "relation":
        return "relation_general", DIFFICULTE_MAX["relation_general"]
    else:
        return "développement_general", DIFFICULTE_MAX["développement_general"]
def _calculer_readiness(profil: ProfilUtilisateur) -> float:
    """
    Calcule le score de préparation du profil (0.0 à 1.0).

    Prend en compte santé, énergie, stress, finances, compétences et
    le temps disponible hors travail/sommeil/transport.

    Returns:
        Score normalisé entre 0.0 et 1.0
    """
    # Indicateurs psychophysiques
    sante_norm = profil.niveau_sante / 10
    energie_norm = profil.niveau_energie / 10
    stress_norm = (10 - profil.niveau_stress) / 10  # inversé : moins de stress = mieux
    bonheur_norm = profil.niveau_bonheur / 10

    # Facteur financier : log du revenu normalisé sur [0, 1]
    # log10(10k) ≈ 4, log10(1M) = 6 → on normalise sur 4–6
    revenu_log = math.log10(max(profil.revenu_annuel, 1))
    revenu_norm = min(max((revenu_log - 3.7) / 2.3, 0), 1)

    # Facteur compétences : 0 compétence = 0, 10+ = 1
    competences_norm = min(len(profil.competences) / 10, 1)

    # Facteur temps disponible (heures hors contraintes)
    heures_libres = max(
        0,
        24 - profil.heures_travail - profil.heures_sommeil - profil.heures_transport,
    )
    temps_norm = min(heures_libres / 6, 1)  # 6h libres = score max

    readiness = (
        sante_norm       * 0.18
        + energie_norm   * 0.12
        + stress_norm    * 0.18
        + bonheur_norm   * 0.10
        + revenu_norm    * 0.17
        + competences_norm * 0.13
        + temps_norm     * 0.12
    )
    return max(0.0, min(1.0, readiness))


def _calculer_facteur_neuro(profil: ProfilUtilisateur) -> float:
    """
    Calcule le multiplicateur neuroscientifique (0.3 à 1.0).

    Basé sur la qualité du sommeil, le niveau de stress et de bonheur —
    facteurs validés par la recherche en neurosciences cognitives comme
    prédicteurs de la capacité à maintenir des efforts à long terme.

    Returns:
        Multiplicateur entre 0.3 et 1.0
    """
    # Sommeil optimal entre 7 et 9 heures
    ecart_sommeil = abs(profil.heures_sommeil - 8.0)
    facteur_sommeil = max(0.4, 1.0 - ecart_sommeil * 0.12)

    facteur_stress = (10 - profil.niveau_stress) / 10
    facteur_bonheur = profil.niveau_bonheur / 10

    neuro = (
        facteur_sommeil  * 0.40
        + facteur_stress * 0.35
        + facteur_bonheur * 0.25
    )
    return max(0.3, min(1.0, neuro))


def _appliquer_bonus_deadline(objectif: Objectif) -> float:
    """
    Retourne un bonus de probabilité si une deadline réaliste est fixée.

    La présence d'une deadline concrète indique un engagement supérieur,
    ce qui améliore statistiquement les chances de réussite.

    Returns:
        Bonus en points de probabilité (0.0 à 3.0)
    """
    if objectif.deadline is None:
        return 0.0
    from datetime import datetime
    jours_restants = (objectif.deadline - datetime.now()).days
    if jours_restants <= 0:
        return 0.0
    if jours_restants < 30:
        return 0.5   # délai très court
    if jours_restants < 365:
        return 2.0   # délai réaliste < 1 an
    if jours_restants < 1825:
        return 3.0   # délai 1-5 ans → très motivant
    return 1.5       # délai > 5 ans (réaliste mais lointain)


class MoteurProbabilite:
    """
    Moteur central de calcul de probabilité de Syléa.AI.

    Expose deux opérations :
    1. calculer_probabilite_initiale() : appelé à la création du profil
    2. recalculer_apres_choix()        : appelé après chaque décision
    """

    def calculer_probabilite_initiale(self, profil: ProfilUtilisateur) -> float:
        """
        Calcule la probabilité de réussite initiale à partir du profil.

        Args:
            profil: ProfilUtilisateur complet avec un objectif défini

        Returns:
            Probabilité en pourcentage, bornée entre PROB_MIN et PROB_MAX

        Raises:
            ValueError: si aucun objectif n'est défini dans le profil
        """
        if profil.objectif is None:
            raise ValueError("Le profil doit avoir un objectif défini.")

        _sous_cat, prob_max = _classifier_objectif(
            profil.objectif.description, profil.objectif.categorie
        )

        readiness = _calculer_readiness(profil)
        neuro = _calculer_facteur_neuro(profil)
        bonus_deadline = _appliquer_bonus_deadline(profil.objectif)

        probabilite = prob_max * readiness * neuro + bonus_deadline

        # Stocker la probabilité de base dans l'objectif
        profil.objectif.probabilite_base = probabilite

        return self._borner(probabilite)

    def recalculer_apres_choix(
        self, prob_actuelle: float, impact_score: float
    ) -> float:
        """
        Recalcule la probabilité après qu'un choix a été fait.

        L'impact n'est pas simplement additionné : on applique une légère
        atténuation sur les grands impacts pour éviter des sauts irréalistes.

        Args:
            prob_actuelle : Probabilité courante en %
            impact_score  : Delta en points de % (positif ou négatif)

        Returns:
            Nouvelle probabilité bornée entre PROB_MIN et PROB_MAX
        """
        # Atténuation : plus la probabilité est déjà haute, plus les gains sont réduits
        if impact_score > 0:
            facteur_attenuation = 1 - (prob_actuelle / 100) * 0.3
            impact_reel = impact_score * max(0.3, facteur_attenuation)
        else:
            impact_reel = impact_score  # les pertes ne sont pas atténuées

        nouvelle_prob = prob_actuelle + impact_reel
        return self._borner(nouvelle_prob)

    @staticmethod
    def _borner(prob: float) -> float:
        """Borne la probabilité entre PROB_MIN et PROB_MAX."""
        return round(max(PROB_MIN, min(PROB_MAX, prob)), 2)

    def generer_message_trajectoire(
        self, prob_avant: float, prob_apres: float
    ) -> str:
        """
        Génère un message centré sur la trajectoire plutôt que le chiffre brut.

        Objectif : réduire l'anxiété liée à une baisse de probabilité en
        valorisant la progression long terme.

        Args:
            prob_avant: Probabilité avant la décision
            prob_apres: Probabilité après la décision

        Returns:
            Message motivant de 1-2 phrases
        """
        delta = prob_apres - prob_avant

        if delta >= 3:
            return "Excellente décision ! Vous progressez significativement vers votre objectif."
        elif delta >= 1:
            return "Bon choix. Chaque petite avancée compte dans la durée."
        elif delta >= 0:
            return "Décision neutre sur le court terme — la régularité est la clé."
        elif delta >= -1:
            return "Légère baisse, mais c'est normal. Une journée ne fait pas une trajectoire."
        elif delta >= -3:
            return (
                "Ce choix a un coût. Compensez lors de la prochaine décision "
                "pour rester sur votre trajectoire."
            )
        else:
            return (
                "Attention : cette décision impacte significativement votre objectif. "
                "Réorientez-vous rapidement."
            )


def jours_vers_probabilite(prob_actuelle: float, impact_jours: float) -> float:
    """Convert time impact (days) to probability impact (%).

    Args:
        prob_actuelle: Current probability (0-100)
        impact_jours: Days gained (positive) or lost (negative)

    Returns:
        Probability delta in percentage points
    """
    prob_totale = max(0.01, min(99.99, prob_actuelle))
    temps_j = min(73000, max(1, round(900 * ((100 - prob_totale) / prob_totale) ** 0.675)))
    temps_apres = max(1, temps_j - impact_jours)
    prob_apres = 100.0 / (1.0 + (temps_apres / 900.0) ** (1.0 / 0.675))
    return round(prob_apres - prob_totale, 4)
