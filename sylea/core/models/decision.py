"""
Modèles de données pour les décisions et l'historique de Syléa.AI.

Ce module définit :
- OptionDilemme  : une option proposée lors d'un dilemme
- ActionAgent    : une tâche exécutée par l'agent ("Le Double")
- Decision       : l'ensemble d'un dilemme (question + options + choix)
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class OptionDilemme:
    """
    Représente une option dans un dilemme soumis par l'utilisateur.

    Attributs :
        description       : Texte de l'option (ex : "Aller courir")
        impact_score      : Impact en points de pourcentage (peut être négatif)
        explication_impact: Justification textuelle générée par le moteur
        est_delegable     : True si l'agent peut prendre en charge cette tâche
        temps_estime      : Durée estimée en heures
        id                : Identifiant unique de l'option
    """

    description: str
    impact_score: float = 0.0
    explication_impact: str = ""
    est_delegable: bool = False
    temps_estime: float = 0.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        """Sérialise l'option en dictionnaire."""
        return {
            "id": self.id,
            "description": self.description,
            "impact_score": self.impact_score,
            "explication_impact": self.explication_impact,
            "est_delegable": self.est_delegable,
            "temps_estime": self.temps_estime,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OptionDilemme":
        """Désérialise une option depuis un dictionnaire."""
        opt = cls(
            description=data["description"],
            impact_score=data.get("impact_score", 0.0),
            explication_impact=data.get("explication_impact", ""),
            est_delegable=data.get("est_delegable", False),
            temps_estime=data.get("temps_estime", 0.0),
        )
        opt.id = data["id"]
        return opt


@dataclass
class ActionAgent:
    """
    Représente une tâche déléguée à l'agent exécutant.

    Attributs :
        instruction  : Texte exact de l'instruction validée
        skill_utilise: Nom du skill qui a traité la tâche
        statut       : 'en_cours' | 'terminé' | 'échec'
        resultat     : Rapport textuel produit par le skill
        temps_passe  : Durée simulée en heures
        id           : Identifiant unique
        execute_le   : Horodatage de l'exécution
    """

    instruction: str
    skill_utilise: str
    statut: str
    resultat: str = ""
    temps_passe: float = 0.0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execute_le: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Sérialise l'action en dictionnaire."""
        return {
            "id": self.id,
            "instruction": self.instruction,
            "skill_utilise": self.skill_utilise,
            "statut": self.statut,
            "resultat": self.resultat,
            "temps_passe": self.temps_passe,
            "execute_le": self.execute_le.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActionAgent":
        """Désérialise une action depuis un dictionnaire."""
        action = cls(
            instruction=data["instruction"],
            skill_utilise=data["skill_utilise"],
            statut=data["statut"],
            resultat=data.get("resultat", ""),
            temps_passe=data.get("temps_passe", 0.0),
        )
        action.id = data["id"]
        action.execute_le = datetime.fromisoformat(data["execute_le"])
        return action


@dataclass
class Decision:
    """
    Représente un dilemme soumis et résolu par l'utilisateur.

    Attributs :
        user_id           : ID du profil utilisateur concerné
        question          : Texte de la question posée
        options           : Liste des options analysées
        probabilite_avant : Probabilité avant le choix
        option_choisie_id : ID de l'option retenue (None si pas encore choisi)
        probabilite_apres : Probabilité après le choix
        action_agent      : Action déléguée à l'agent (optionnelle)
        id                : Identifiant unique de la décision
        cree_le           : Horodatage de création
    """

    user_id: str
    question: str
    options: List[OptionDilemme]
    probabilite_avant: float
    option_choisie_id: Optional[str] = None
    probabilite_apres: Optional[float] = None
    action_agent: Optional[ActionAgent] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    impact_temporel_jours: Optional[int] = None
    cree_le: datetime = field(default_factory=datetime.now)

    def get_option_choisie(self) -> Optional[OptionDilemme]:
        """Retourne l'objet OptionDilemme correspondant au choix effectué."""
        if not self.option_choisie_id:
            return None
        return next(
            (o for o in self.options if o.id == self.option_choisie_id), None
        )

    def to_dict(self) -> dict:
        """Sérialise la décision pour la persistance."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "question": self.question,
            "options_json": json.dumps(
                [o.to_dict() for o in self.options], ensure_ascii=False
            ),
            "probabilite_avant": self.probabilite_avant,
            "option_choisie_id": self.option_choisie_id,
            "probabilite_apres": self.probabilite_apres,
            "action_agent_json": (
                json.dumps(self.action_agent.to_dict(), ensure_ascii=False)
                if self.action_agent
                else None
            ),
            "cree_le": self.cree_le.isoformat(),
            "impact_temporel_jours": self.impact_temporel_jours,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Decision":
        """Reconstruit une décision depuis un dictionnaire (lecture SQLite)."""
        options = [
            OptionDilemme.from_dict(o)
            for o in json.loads(data.get("options_json", "[]"))
        ]
        action_agent = None
        if data.get("action_agent_json"):
            action_agent = ActionAgent.from_dict(
                json.loads(data["action_agent_json"])
            )
        decision = cls(
            user_id=data["user_id"],
            question=data["question"],
            options=options,
            probabilite_avant=float(data["probabilite_avant"]),
            option_choisie_id=data.get("option_choisie_id"),
            probabilite_apres=(
                float(data["probabilite_apres"])
                if data.get("probabilite_apres") is not None
                else None
            ),
            action_agent=action_agent,
            impact_temporel_jours=data.get("impact_temporel_jours"),
        )
        decision.id = data["id"]
        decision.cree_le = datetime.fromisoformat(data["cree_le"])
        return decision
