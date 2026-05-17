"""
Modeles SQLAlchemy ORM — mirror exact du schema actuel SQLite.

Permet de :
  1. Generer la schema PostgreSQL via Alembic (autogenerate)
  2. Migrer progressivement les routers vers SQLAlchemy (au lieu de raw SQL)
  3. Garder une API typee (Python type hints sur les champs)

NOTE : tant que la migration vers SQLAlchemy n'est pas complete, ces modeles
servent uniquement de SOURCE OF TRUTH pour le schema. Les routers continuent
d'utiliser db.conn.execute() raw — qui marche aussi bien sur SQLite que sur
PostgreSQL (modulo quelques ajustements de syntax).
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from api.database.engine import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=True)
    provider = Column(String, default='local')
    provider_id = Column(String, nullable=True)
    created_at = Column(String, nullable=False)


class ProfilUtilisateur(Base):
    __tablename__ = "profil_utilisateur"

    id = Column(String, primary_key=True)
    nom = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    profession = Column(String, nullable=False)
    ville = Column(String, nullable=False)
    situation_familiale = Column(String, nullable=False)
    revenu_annuel = Column(Float, nullable=False)
    patrimoine_estime = Column(Float, nullable=False)
    charges_mensuelles = Column(Float, nullable=False)
    objectif_financier = Column(Float, nullable=True)
    heures_travail = Column(Float, default=8.0)
    heures_sommeil = Column(Float, default=7.0)
    heures_loisirs = Column(Float, default=2.0)
    heures_transport = Column(Float, default=1.0)
    heures_objectif = Column(Float, default=1.0)
    niveau_sante = Column(Integer, default=7)
    niveau_stress = Column(Integer, default=5)
    niveau_energie = Column(Integer, default=7)
    niveau_bonheur = Column(Integer, default=7)
    competences = Column(Text, default='')
    diplomes = Column(Text, default='')
    langues = Column(Text, default='')
    objectif_description = Column(Text, nullable=True)
    objectif_categorie = Column(String, nullable=True)
    objectif_deadline = Column(String, nullable=True)
    objectif_probabilite_base = Column(Float, default=0.0)
    objectif_probabilite_calculee = Column(Float, default=0)
    probabilite_actuelle = Column(Float, default=0.0)
    auth_user_id = Column(String, ForeignKey("users.id"), index=True, nullable=True)
    genre = Column(String, default='')
    objectif_modifie_le = Column(String, nullable=True)
    phrase_personnalite = Column(Text, nullable=True)
    temps_initial_jours = Column(Integer, default=0)
    temps_gagne_jours = Column(Float, default=0.0)
    photo_url = Column(String, nullable=True)
    cree_le = Column(String, nullable=False)
    mis_a_jour_le = Column(String, nullable=False)


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("profil_utilisateur.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    options_json = Column(Text, nullable=False)
    probabilite_avant = Column(Float, nullable=False)
    option_choisie_id = Column(String, nullable=True)
    probabilite_apres = Column(Float, nullable=True)
    action_agent_json = Column(Text, nullable=True)
    temps_gagne_avant = Column(Float, default=0.0)
    temps_gagne_apres = Column(Float, default=0.0)
    sous_objectif_id = Column(String, nullable=True, index=True)
    sous_objectif_impacte = Column(String, nullable=True)
    impact_sous_objectif = Column(Float, nullable=True)
    cree_le = Column(String, nullable=False)

    __table_args__ = (
        Index('idx_decisions_user_cree', 'user_id', 'cree_le'),
    )


class BilanQuotidien(Base):
    __tablename__ = "bilans_quotidiens"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("profil_utilisateur.id"), nullable=False)
    date = Column(String, nullable=False)
    niveau_sante = Column(Integer, default=7)
    niveau_stress = Column(Integer, default=5)
    niveau_energie = Column(Integer, default=7)
    niveau_bonheur = Column(Integer, default=7)
    heures_travail = Column(Float, default=8.0)
    heures_sommeil = Column(Float, default=7.0)
    heures_loisirs = Column(Float, default=2.0)
    heures_transport = Column(Float, default=1.0)
    heures_objectif = Column(Float, default=1.0)
    description = Column(Text, default='')
    cree_le = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_bilan_user_date'),
        Index('idx_bilans_user_date', 'user_id', 'date'),
    )


class SousObjectif(Base):
    __tablename__ = "sous_objectifs"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("profil_utilisateur.id"), nullable=False)
    titre = Column(Text, nullable=False)
    description = Column(Text, default='')
    progression = Column(Float, default=0.0)
    ordre = Column(Integer, default=0)
    temps_estime = Column(Float, nullable=True)
    cree_le = Column(String, nullable=False)

    __table_args__ = (
        Index('idx_so_user_ordre', 'user_id', 'ordre'),
    )


class TacheQuotidienne(Base):
    __tablename__ = "taches_quotidiennes"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("profil_utilisateur.id"), nullable=False)
    date = Column(String, nullable=False)
    taches_json = Column(Text, nullable=False)
    deadline = Column(String, nullable=False)
    statut = Column(String, default='en_cours')
    cree_le = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_taches_user_date'),
        Index('idx_taches_user_date', 'user_id', 'date'),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(String, primary_key=True)
    auth_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String, default='text')
    created_at = Column(String, nullable=False)
    audio_data = Column(Text, default='')

    __table_args__ = (
        Index('idx_agent_msg_user_created', 'auth_user_id', 'created_at'),
        Index('idx_agent_msg_user_role', 'auth_user_id', 'role'),
    )


class Agent2Message(Base):
    __tablename__ = "agent2_messages"

    id = Column(String, primary_key=True)
    auth_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    type = Column(String, default='text')
    created_at = Column(String, nullable=False)
    audio_data = Column(Text, default='')

    __table_args__ = (
        Index('idx_agent2_msg_user_created', 'auth_user_id', 'created_at'),
        Index('idx_agent2_msg_user_role', 'auth_user_id', 'role'),
    )


class AgentCollectedInfo(Base):
    __tablename__ = "agent_collected_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    field = Column(String, nullable=False)
    value = Column(Text, nullable=False)
    collected_at = Column(String, nullable=False)

    __table_args__ = (
        Index('idx_collected_user', 'user_id', 'collected_at'),
    )


class AgentProposal(Base):
    __tablename__ = "agent_proposals"

    id = Column(String, primary_key=True)
    auth_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    agent_label = Column(String, nullable=False)
    type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    impact_jours = Column(Float, default=0)
    resume = Column(Text, default='')
    rationale = Column(Text, default='')
    target_so_hint = Column(Text, default='')
    statut = Column(String, default='pending')
    created_at = Column(String, nullable=False)
    responded_at = Column(String, nullable=True)
    decision_id = Column(String, nullable=True)

    __table_args__ = (
        Index('idx_agent_proposals_user', 'auth_user_id', 'statut'),
    )
