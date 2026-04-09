"""
Semantic Memory — Recherche semantique par TF-IDF pour Sylea Agent 3.

Remplace le simple LIKE '%mot%' par une recherche par similarite textuelle.
Utilise TF-IDF (Term Frequency - Inverse Document Frequency) + cosine similarity
de scikit-learn pour trouver les souvenirs les plus proches d'une requete.

Architecture :
  [Agent 3] -> memory_search("revenus freelance")
            -> SemanticMemory.search()
            -> TF-IDF vectorize(tous les souvenirs + requete)
            -> cosine_similarity(requete_vec, souvenirs_vecs)
            -> Top K resultats tries par score

Avantages par rapport au LIKE :
  - "revenus freelance" trouve "tjm_objectif: 600EUR/jour"
  - "stress travail" trouve "niveau_energie: faible cette semaine"
  - Pas besoin de match exact sur les mots

Fallback : si scikit-learn n'est pas installe, retombe sur le LIKE classique.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("semantic_memory")

# ── Import conditionnel de scikit-learn ────────────────────────────────────────

_HAS_SKLEARN = False
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _HAS_SKLEARN = True
    logger.info("Semantic memory: scikit-learn disponible, TF-IDF actif")
except ImportError:
    logger.warning("Semantic memory: scikit-learn absent, fallback sur LIKE")


# ── Stopwords francais legers (pas besoin de NLTK) ───────────────────────────

_FR_STOPWORDS = {
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "est", "en",
    "que", "qui", "dans", "pour", "pas", "sur", "au", "aux", "ce", "se",
    "son", "sa", "ses", "avec", "il", "elle", "je", "tu", "nous", "vous",
    "ils", "elles", "on", "ne", "plus", "par", "mais", "ou", "donc",
    "ni", "car", "si", "mon", "ma", "mes", "ton", "ta", "tes", "notre",
    "votre", "leur", "leurs", "tout", "tous", "toute", "toutes",
    "etre", "avoir", "faire", "dire", "aller", "voir", "savoir",
    "pouvoir", "vouloir", "devoir", "falloir", "a", "y", "d", "l", "s",
    "c", "n", "j", "qu", "m", "t",
}


# ── Synonymes francais (expansion de requete) ────────────────────────────────
# Quand la requete contient un mot, on ajoute ses synonymes pour elargir le match.
# Cela compense la limite du TF-IDF qui ne comprend pas le "sens".

_FR_SYNONYMS: dict[str, list[str]] = {
    # Finance
    "revenus": ["salaire", "gains", "argent", "euros", "remuneration", "tjm", "chiffre"],
    "salaire": ["revenus", "gains", "remuneration", "paie"],
    "argent": ["revenus", "finances", "budget", "euros", "prix", "cout"],
    "prix": ["cout", "tarif", "euros", "montant", "budget"],
    "budget": ["argent", "finances", "depenses", "cout"],
    "gagne": ["revenus", "salaire", "gains", "euros", "remuneration"],
    "combien": ["montant", "nombre", "quantite", "total"],
    # Sante / bien-etre
    "stress": ["fatigue", "anxiete", "tension", "epuisement", "burnout"],
    "fatigue": ["stress", "epuisement", "energie", "sommeil"],
    "sport": ["exercice", "course", "musculation", "entrainement", "physique", "fitness"],
    "exercice": ["sport", "course", "entrainement", "physique", "activite"],
    "physique": ["sport", "exercice", "corps", "sante", "course"],
    "sante": ["stress", "bien-etre", "energie", "sommeil", "sport"],
    # Travail / freelance
    "client": ["prospect", "contact", "mission", "entreprise", "startup"],
    "trouver": ["chercher", "rechercher", "obtenir", "decrocher", "prospect", "contact"],
    "mission": ["projet", "contrat", "travail", "client"],
    "freelance": ["independant", "consultant", "tjm", "missions"],
    # Tech
    "apprendre": ["formation", "cours", "etudier", "progresser", "apprentissage"],
    "formation": ["cours", "apprendre", "apprentissage", "tutoriel", "udemy"],
    "code": ["developpement", "programmation", "script", "dev"],
    "developpeur": ["dev", "programmeur", "ingenieur", "developpement"],
    # Projet
    "idee": ["projet", "concept", "plan", "initiative"],
    "projet": ["idee", "plan", "initiative", "application", "saas"],
}


def _expand_query(query: str) -> str:
    """
    Enrichit la requete avec des synonymes pour elargir le match TF-IDF.
    Ex: "exercice physique" -> "exercice physique sport course entrainement corps sante"
    """
    words = re.findall(r'\w+', query.lower())
    expanded = list(words)  # Garder les mots originaux

    for word in words:
        if word in _FR_SYNONYMS:
            # Ajouter les synonymes (sans doublons)
            for syn in _FR_SYNONYMS[word]:
                if syn not in expanded:
                    expanded.append(syn)

    return " ".join(expanded)


@dataclass
class MemoryMatch:
    """Un resultat de recherche en memoire avec son score de pertinence."""
    key: str
    value: str
    category: str
    score: float  # 0.0 a 1.0
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "score": round(self.score, 4),
            "updated_at": self.updated_at,
        }


class SemanticMemory:
    """
    Moteur de recherche semantique sur les souvenirs de l'agent.

    Utilise TF-IDF pour vectoriser les documents (souvenirs) et la requete,
    puis calcule la similarite cosine pour trouver les meilleurs matches.
    """

    def __init__(self, min_score: float = 0.05):
        """
        Args:
            min_score: Score minimum pour inclure un resultat (0.0-1.0).
                       0.05 est permissif — on prefere trop de resultats que pas assez.
        """
        self.min_score = min_score

    def search(
        self,
        query: str,
        memories: list[dict],
        top_k: int = 10,
    ) -> list[MemoryMatch]:
        """
        Recherche semantique dans les souvenirs.

        Args:
            query: La requete de recherche (ex: "revenus freelance")
            memories: Liste de dicts avec {key, value, category, updated_at}
            top_k: Nombre max de resultats

        Returns:
            Liste de MemoryMatch triee par score decroissant
        """
        if not query or not memories:
            return []

        # Si sklearn absent, fallback sur recherche par mots-cles
        if not _HAS_SKLEARN:
            return self._fallback_search(query, memories, top_k)

        return self._tfidf_search(query, memories, top_k)

    def _tfidf_search(
        self,
        query: str,
        memories: list[dict],
        top_k: int,
    ) -> list[MemoryMatch]:
        """Recherche par TF-IDF + cosine similarity avec expansion de synonymes."""

        # Construire les documents : concatener key + value + category pour chaque souvenir
        documents = []
        for m in memories:
            doc = f"{m.get('key', '')} {m.get('value', '')} {m.get('category', '')}"
            documents.append(doc)

        # Expansion de la requete avec synonymes
        expanded_query = _expand_query(query)

        # Ajouter la requete enrichie en dernier
        documents.append(expanded_query)

        try:
            # Vectoriser avec TF-IDF
            vectorizer = TfidfVectorizer(
                lowercase=True,
                strip_accents="unicode",      # Gere les accents francais
                stop_words=list(_FR_STOPWORDS),
                ngram_range=(1, 2),           # Unigrammes + bigrammes
                max_features=5000,            # Limite le vocabulaire
                sublinear_tf=True,            # Meilleure gestion des frequences
                min_df=1,                     # Garder tous les termes (petits corpus)
            )

            tfidf_matrix = vectorizer.fit_transform(documents)

            # La requete est le dernier document
            query_vec = tfidf_matrix[-1:]
            memory_vecs = tfidf_matrix[:-1]

            # Calculer la similarite cosine
            similarities = cosine_similarity(query_vec, memory_vecs).flatten()

            # Trier par score decroissant et filtrer
            results = []
            ranked_indices = similarities.argsort()[::-1]

            for idx in ranked_indices[:top_k]:
                score = float(similarities[idx])
                if score < self.min_score:
                    break  # Les suivants seront encore plus bas

                m = memories[idx]
                results.append(MemoryMatch(
                    key=m.get("key", ""),
                    value=m.get("value", ""),
                    category=m.get("category", "general"),
                    score=score,
                    updated_at=m.get("updated_at", ""),
                ))

            return results

        except Exception as e:
            logger.warning(f"TF-IDF search failed, falling back: {e}")
            return self._fallback_search(query, memories, top_k)

    def _fallback_search(
        self,
        query: str,
        memories: list[dict],
        top_k: int,
    ) -> list[MemoryMatch]:
        """
        Recherche par mots-cles avec synonymes (fallback si sklearn absent).
        Compte le nombre de mots de la requete presents dans le souvenir.
        """
        # Expansion avec synonymes
        expanded = _expand_query(query)
        # Extraire les mots significatifs (> 2 chars, pas stopwords)
        query_words = [
            w for w in re.findall(r'\w+', expanded.lower())
            if len(w) > 2 and w not in _FR_STOPWORDS
        ]

        if not query_words:
            query_words = [query.lower()]

        results = []
        for m in memories:
            text = f"{m.get('key', '')} {m.get('value', '')} {m.get('category', '')}".lower()

            # Compter les mots matches
            matched = sum(1 for w in query_words if w in text)
            if matched == 0:
                continue

            # Score = proportion de mots trouves
            score = matched / len(query_words)

            results.append(MemoryMatch(
                key=m.get("key", ""),
                value=m.get("value", ""),
                category=m.get("category", "general"),
                score=score,
                updated_at=m.get("updated_at", ""),
            ))

        # Trier par score decroissant
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]


# ── Instance globale ──────────────────────────────────────────────────────────

_semantic_memory = SemanticMemory(min_score=0.05)


def semantic_search(
    query: str,
    memories: list[dict],
    top_k: int = 10,
) -> list[MemoryMatch]:
    """
    Point d'entree principal pour la recherche semantique en memoire.

    Args:
        query: Texte de recherche
        memories: Liste de souvenirs [{key, value, category, updated_at}]
        top_k: Max resultats

    Returns:
        Liste de MemoryMatch avec scores
    """
    return _semantic_memory.search(query, memories, top_k)


def is_semantic_available() -> bool:
    """Retourne True si le moteur TF-IDF est disponible."""
    return _HAS_SKLEARN
