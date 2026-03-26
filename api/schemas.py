"""
Schémas Pydantic pour l'API Syléa.AI.

Miroir des dataclasses Python existantes (ProfilUtilisateur, Decision, etc.)
adaptés pour la sérialisation/désérialisation JSON via FastAPI.
"""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ── Contexte appareil (heure, geoloc, meteo) ─────────────────────────────────

class DeviceContextIn(BaseModel):
    heure: int = Field(0, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    fuseau_horaire: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    ville: str = ""
    temperature: float = 0.0
    meteo: str = ""


# ── Objectif ──────────────────────────────────────────────────────────────────

class ObjectifIn(BaseModel):
    description: str
    categorie: str = ''
    deadline: Optional[str] = None          # ISO date string "YYYY-MM-DD"
    probabilite_base: float = 0.0


class ObjectifOut(BaseModel):
    description: str
    categorie: str
    deadline: Optional[str] = None
    probabilite_base: float
    probabilite_calculee: float = 0.0


# ── Profil ────────────────────────────────────────────────────────────────────

class ProfilIn(BaseModel):
    nom: str
    age: int = Field(ge=1)
    genre: str = ""
    profession: str
    ville: str
    situation_familiale: str

    # Financier
    revenu_annuel: float = Field(ge=0)
    patrimoine_estime: float = Field(ge=0)
    charges_mensuelles: float = Field(ge=0)
    objectif_financier: Optional[float] = None

    # Temps quotidien
    heures_travail: float = 8.0
    heures_sommeil: float = 7.0
    heures_loisirs: float = 2.0
    heures_transport: float = 1.0
    heures_objectif: float = 1.0

    # Auto-évaluations (1-10)
    niveau_sante: int = Field(default=7, ge=1, le=10)
    niveau_stress: int = Field(default=5, ge=1, le=10)
    niveau_energie: int = Field(default=7, ge=1, le=10)
    niveau_bonheur: int = Field(default=7, ge=1, le=10)

    # Compétences
    competences: List[str] = []
    diplomes: List[str] = []
    langues: List[str] = []

    # Objectif
    objectif: Optional[ObjectifIn] = None

    # Réinitialisation de l’historique (nouvel objectif de vie)
    reset_historique: bool = False


class ProfilOut(BaseModel):
    id: str
    nom: str
    age: int
    genre: str = ""
    profession: str
    ville: str
    situation_familiale: str

    revenu_annuel: float
    patrimoine_estime: float
    charges_mensuelles: float
    objectif_financier: Optional[float]

    heures_travail: float
    heures_sommeil: float
    heures_loisirs: float
    heures_transport: float
    heures_objectif: float

    niveau_sante: int
    niveau_stress: int
    niveau_energie: int
    niveau_bonheur: int

    competences: List[str]
    diplomes: List[str]
    langues: List[str]

    objectif: Optional[ObjectifOut]
    probabilite_actuelle: float

    cree_le: str
    mis_a_jour_le: str
    objectif_modifie_le: Optional[str] = None


# ── Dilemme ───────────────────────────────────────────────────────────────────

class DilemmeIn(BaseModel):
    question: str
    options: List[str] = []
    # Retrocompat : si option_a/option_b sont fournis, les convertir en options
    option_a: Optional[str] = None
    option_b: Optional[str] = None
    impact_temporel_jours: Optional[int] = None
    contexte_appareil: Optional[DeviceContextIn] = None


class AnalyseOptionOut(BaseModel):
    lettre: str = ""  # "A", "B", "C"...
    description: str
    pros: List[str]
    cons: List[str]
    impact_probabilite: float
    resume: str
    impact_jours_brut: float = 0.0


class AnalyseDilemmeOut(BaseModel):
    question: str
    options: List[AnalyseOptionOut] = []
    verdict: str
    option_recommandee: str  # "A", "B", "C"...
    etude_scientifique: str = ""


class ChoixIn(BaseModel):
    question: str
    options: List[AnalyseOptionOut] = []
    choix: str
    impact_temporel_jours: Optional[int] = None  # "A", "B", "C"...
    contexte_appareil: Optional[DeviceContextIn] = None


# ── Decision (historique) ─────────────────────────────────────────────────────

class OptionDilemmeOut(BaseModel):
    id: str
    description: str
    impact_score: float
    explication_impact: str
    est_delegable: bool
    temps_estime: float


class ActionAgentOut(BaseModel):
    id: str
    instruction: str
    skill_utilise: str
    statut: str
    resultat: str
    temps_passe: float
    execute_le: str


class DecisionOut(BaseModel):
    id: str
    user_id: str
    question: str
    options: List[OptionDilemmeOut]
    probabilite_avant: float
    option_choisie_id: Optional[str]
    probabilite_apres: Optional[float]
    action_agent: Optional[ActionAgentOut]
    cree_le: str

    # Champs calculés (pour l'affichage)
    option_choisie_description: Optional[str] = None
    impact_net: Optional[float] = None
    sous_objectif_impacte: Optional[str] = None


# ── Probabilité ───────────────────────────────────────────────────────────────

class ProbabiliteOut(BaseModel):
    probabilite: float
    resume: str
    points_forts: List[str]
    points_faibles: List[str]
    facteurs_cles: List[str]
    conseil_prioritaire: str


# ── Agent rapport ─────────────────────────────────────────────────────────────

class AgentRapportOut(BaseModel):
    total_actions: int
    actions: List[ActionAgentOut]




# ── Journée (analyse bien-être) ───────────────────────────────────────────────

class JourneeIn(BaseModel):
    description: str
    contexte_appareil: Optional[DeviceContextIn] = None


class BienEtreScoresOut(BaseModel):
    niveau_sante:   int = Field(ge=1, le=10)
    niveau_stress:  int = Field(ge=1, le=10)
    niveau_energie: int = Field(ge=1, le=10)
    niveau_bonheur: int = Field(ge=1, le=10)



# ── Questions objectif ────────────────────────────────────────────────────────

class QuestionsObjectifIn(BaseModel):
    description: str
    contexte_appareil: Optional[DeviceContextIn] = None


# ── Health ────────────────────────────────────────────────────────────────────

class HealthOut(BaseModel):
    status: str
    version: str

# -- Evenement (enregistrement) ------------------------------------------------

class EvenementIn(BaseModel):
    description: str = Field(min_length=5)
    contexte_appareil: Optional[DeviceContextIn] = None


class AnalyseEvenementOut(BaseModel):
    resume: str
    impact_probabilite: float
    explication: str
    conseil: str


class ConfirmerEvenementIn(BaseModel):
    description: str
    impact_probabilite: float
    resume: str
    contexte_appareil: Optional[DeviceContextIn] = None


# -- Bilan quotidien -----------------------------------------------------------

class BilanIn(BaseModel):
    niveau_sante: int = Field(default=7, ge=1, le=10)
    niveau_stress: int = Field(default=5, ge=1, le=10)
    niveau_energie: int = Field(default=7, ge=1, le=10)
    niveau_bonheur: int = Field(default=7, ge=1, le=10)
    heures_travail: float = 8.0
    heures_sommeil: float = 7.0
    heures_loisirs: float = 2.0
    heures_transport: float = 1.0
    heures_objectif: float = 1.0
    description: str = ""


class BilanOut(BaseModel):
    id: str
    date: str
    niveau_sante: int
    niveau_stress: int
    niveau_energie: int
    niveau_bonheur: int
    heures_travail: float
    heures_sommeil: float
    heures_loisirs: float
    heures_transport: float
    heures_objectif: float
    description: str
    cree_le: str


class BilanCheckOut(BaseModel):
    exists: bool
    bilan: Optional[BilanOut] = None


# -- Sous-objectifs --------------------------------------------------------

class SousObjectifOut(BaseModel):
    id: str
    titre: str
    description: str
    progression: float
    ordre: int
    temps_estime: float = 0.0

class SousObjectifUpdateIn(BaseModel):
    id: str
    progression: float = Field(ge=0, le=100)


# -- Taches quotidiennes --------------------------------------------------

class TacheItem(BaseModel):
    id: str
    description: str
    completee: bool = False
    titre: str = ""
    duree: str = ""
    type: str = "action"
    lien: str = ""
    icone: str = ""

class TachesOut(BaseModel):
    id: str
    date: str
    taches: List[TacheItem]
    deadline: str
    statut: str
    cree_le: str

class TachesCheckOut(BaseModel):
    exists: bool
    taches: Optional[TachesOut] = None

class CompleterTacheIn(BaseModel):
    tache_id: str

class CompleterTacheOut(BaseModel):
    tache: TacheItem
    impact_principal: float
    impacts_sous_objectifs: List[SousObjectifUpdateIn] = []
    sous_objectif_impacte: Optional[str] = None

# -- Personnalite IA ------------------------------------------------------

class PersonnaliteOut(BaseModel):
    phrase: str


# -- Service Client (chatbot) ------------------------------------------------

class ServiceClientMessageIn(BaseModel):
    role: str  # 'user' ou 'assistant'
    content: str

class ServiceClientChatIn(BaseModel):
    messages: list[ServiceClientMessageIn]
    contexte_appareil: Optional[DeviceContextIn] = None


class VerifyCodeIn(BaseModel):
    email: str
    code: str


class ProbabiliteIn(BaseModel):
    contexte_appareil: Optional[DeviceContextIn] = None


class GenererSousObjectifsIn(BaseModel):
    contexte_appareil: Optional[DeviceContextIn] = None


class GenererTachesIn(BaseModel):
    contexte_appareil: Optional[DeviceContextIn] = None

class ServiceClientChatOut(BaseModel):
    message: str


# -- Historique pagine -------------------------------------------------------

class HistoriquePagineOut(BaseModel):
    decisions: List[DecisionOut]
    total: int
    page: int
    par_page: int
    pages_total: int
