"""
Modèles de données pour le profil utilisateur de Syléa.AI.

Ce module définit les structures :
- Objectif : l'objectif de vie principal de l'utilisateur
- ProfilUtilisateur : le profil complet ("Le Miroir")
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


CATEGORIES_OBJECTIF = [
    "carrière",
    "santé",
    "finance",
    "relation",
    "développement",
]

SITUATIONS_FAMILIALES = [
    "célibataire",
    "en couple",
    "marié(e)",
    "divorcé(e)",
    "veuf/veuve",
]


@dataclass
class Objectif:
    """
    Représente l'objectif principal de l'utilisateur.

    Attributs :
        description     : Texte libre décrivant l'objectif
        categorie       : Catégorie parmi CATEGORIES_OBJECTIF
        deadline        : Date limite (optionnelle)
        probabilite_base: Probabilité calculée initialement
    """

    description: str
    categorie: str
    deadline: Optional[datetime] = None
    probabilite_base: float = 0.0
    probabilite_calculee: float = 0.0  # resultat moteur (interne, pour calcul temps)

    def __post_init__(self) -> None:
        if self.categorie and self.categorie not in CATEGORIES_OBJECTIF:
            raise ValueError(
                f"Catégorie invalide '{self.categorie}'. "
                f"Choisir parmi : {CATEGORIES_OBJECTIF}"
            )

    def to_dict(self) -> dict:
        """Sérialise l'objectif en dictionnaire."""
        return {
            "description": self.description,
            "categorie": self.categorie,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "probabilite_base": self.probabilite_base,
            "probabilite_calculee": self.probabilite_calculee,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Objectif":
        """Désérialise un objectif depuis un dictionnaire."""
        deadline = None
        if data.get("deadline"):
            deadline = datetime.fromisoformat(data["deadline"])
        return cls(
            description=data["description"],
            categorie=data["categorie"],
            deadline=deadline,
            probabilite_base=data.get("probabilite_base", 0.0),
            probabilite_calculee=data.get("probabilite_calculee", 0.0),
        )


@dataclass
class ProfilUtilisateur:
    """
    Profil complet d'un utilisateur Syléa.AI ("Le Miroir").

    Regroupe toutes les données personnelles, financières, temporelles
    et les auto-évaluations qui alimentent le moteur de probabilité.
    """

    # ── Identité ────────────────────────────────────────────────────────────
    nom: str
    age: int
    profession: str
    ville: str
    situation_familiale: str

    # ── Données financières ─────────────────────────────────────────────────
    revenu_annuel: float
    patrimoine_estime: float
    charges_mensuelles: float
    objectif_financier: Optional[float] = None
    genre: str = ""

    # ── Temps quotidien (heures/jour) ───────────────────────────────────────
    heures_travail: float = 8.0
    heures_sommeil: float = 7.0
    heures_loisirs: float = 2.0
    heures_transport: float = 1.0
    heures_objectif: float = 1.0

    # ── Auto-évaluations (1-10) ─────────────────────────────────────────────
    niveau_sante: int = 7
    niveau_stress: int = 5
    niveau_energie: int = 7
    niveau_bonheur: int = 7

    # ── Compétences et ressources ───────────────────────────────────────────
    competences: List[str] = field(default_factory=list)
    diplomes: List[str] = field(default_factory=list)
    langues: List[str] = field(default_factory=list)

    # ── Objectif principal ──────────────────────────────────────────────────
    objectif: Optional[Objectif] = None
    probabilite_actuelle: float = 0.0

    # ── Métadonnées ─────────────────────────────────────────────────────────
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cree_le: datetime = field(default_factory=datetime.now)
    mis_a_jour_le: datetime = field(default_factory=datetime.now)
    objectif_modifie_le: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Valide les données saisies."""
        for nom_champ, valeur in [
            ("niveau_sante", self.niveau_sante),
            ("niveau_stress", self.niveau_stress),
            ("niveau_energie", self.niveau_energie),
            ("niveau_bonheur", self.niveau_bonheur),
        ]:
            if not (1 <= valeur <= 10):
                raise ValueError(
                    f"Le champ '{nom_champ}' doit être compris entre 1 et 10."
                )
        if self.age <= 0:
            raise ValueError("L'âge doit être un entier positif.")
        if self.revenu_annuel < 0:
            raise ValueError("Le revenu annuel ne peut pas être négatif.")

    # ── Méthodes utilitaires ────────────────────────────────────────────────

    def marquer_modification(self) -> None:
        """Met à jour l'horodatage de dernière modification."""
        self.mis_a_jour_le = datetime.now()

    def to_dict(self) -> dict:
        """Convertit le profil en dictionnaire pour la persistance SQLite."""
        return {
            "id": self.id,
            "nom": self.nom,
            "age": self.age,
            "genre": self.genre,
            "profession": self.profession,
            "ville": self.ville,
            "situation_familiale": self.situation_familiale,
            "revenu_annuel": self.revenu_annuel,
            "patrimoine_estime": self.patrimoine_estime,
            "charges_mensuelles": self.charges_mensuelles,
            "objectif_financier": self.objectif_financier,
            "heures_travail": self.heures_travail,
            "heures_sommeil": self.heures_sommeil,
            "heures_loisirs": self.heures_loisirs,
            "heures_transport": self.heures_transport,
            "heures_objectif": self.heures_objectif,
            "niveau_sante": self.niveau_sante,
            "niveau_stress": self.niveau_stress,
            "niveau_energie": self.niveau_energie,
            "niveau_bonheur": self.niveau_bonheur,
            "competences": ",".join(self.competences),
            "diplomes": ",".join(self.diplomes),
            "langues": ",".join(self.langues),
            # Objectif aplati
            "objectif_description": self.objectif.description if self.objectif else None,
            "objectif_categorie": self.objectif.categorie if self.objectif else None,
            "objectif_deadline": (
                self.objectif.deadline.isoformat()
                if self.objectif and self.objectif.deadline
                else None
            ),
            "objectif_probabilite_base": (
                self.objectif.probabilite_base if self.objectif else None
            ),
            "objectif_probabilite_calculee": (
                self.objectif.probabilite_calculee if self.objectif else None
            ),
            "probabilite_actuelle": self.probabilite_actuelle,
            "cree_le": self.cree_le.isoformat(),
            "mis_a_jour_le": self.mis_a_jour_le.isoformat(),
            "objectif_modifie_le": self.objectif_modifie_le.isoformat() if self.objectif_modifie_le else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProfilUtilisateur":
        """Reconstruit un profil depuis un dictionnaire (lecture SQLite)."""
        objectif = None
        if data.get("objectif_description"):
            deadline = None
            if data.get("objectif_deadline"):
                deadline = datetime.fromisoformat(data["objectif_deadline"])
            objectif = Objectif(
                description=data["objectif_description"],
                categorie=data["objectif_categorie"],
                deadline=deadline,
                probabilite_base=data.get("objectif_probabilite_base", 0.0),
                probabilite_calculee=data.get("objectif_probabilite_calculee", 0.0),
            )

        profil = cls(
            nom=data["nom"],
            age=int(data["age"]),
            genre=data.get("genre", ""),
            profession=data["profession"],
            ville=data["ville"],
            situation_familiale=data["situation_familiale"],
            revenu_annuel=float(data["revenu_annuel"]),
            patrimoine_estime=float(data["patrimoine_estime"]),
            charges_mensuelles=float(data["charges_mensuelles"]),
            objectif_financier=(
                float(data["objectif_financier"])
                if data.get("objectif_financier") is not None
                else None
            ),
            heures_travail=float(data.get("heures_travail", 8.0)),
            heures_sommeil=float(data.get("heures_sommeil", 7.0)),
            heures_loisirs=float(data.get("heures_loisirs", 2.0)),
            heures_transport=float(data.get("heures_transport", 1.0)),
            heures_objectif=float(data.get("heures_objectif", 1.0)),
            niveau_sante=int(data.get("niveau_sante", 7)),
            niveau_stress=int(data.get("niveau_stress", 5)),
            niveau_energie=int(data.get("niveau_energie", 7)),
            niveau_bonheur=int(data.get("niveau_bonheur", 7)),
            competences=[c for c in data.get("competences", "").split(",") if c],
            diplomes=[d for d in data.get("diplomes", "").split(",") if d],
            langues=[l for l in data.get("langues", "").split(",") if l],
            objectif=objectif,
            probabilite_actuelle=float(data.get("probabilite_actuelle", 0.0)),
        )
        profil.id = data["id"]
        profil.cree_le = datetime.fromisoformat(data["cree_le"])
        profil.mis_a_jour_le = datetime.fromisoformat(data["mis_a_jour_le"])
        oml = data.get("objectif_modifie_le")
        profil.objectif_modifie_le = datetime.fromisoformat(oml) if oml else None
        return profil
