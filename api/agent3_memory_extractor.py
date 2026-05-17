"""
Agent 3 — Memory Extractor.

Extension du systeme de memoire existant : extraction AUTOMATIQUE de faits
durables depuis les conversations. Complete semantic_memory.py (recherche)
et les fonctions _save_memory / _load_memories (stockage) deja en place.

Strategie :
  1. Apres chaque N tours de conversation (ou declenche manuellement),
     on passe la transcription recente a Haiku avec un system prompt
     qui demande d'extraire les FAITS DURABLES (preferences, habitudes,
     entites, dates, infos pro).
  2. On deduplique contre les memories existantes (via semantic_search).
  3. On stocke via _save_memory avec une confidence score.

Categories de faits (inspire de memdir/ de Claude Code) :
  - preference : "user prefere Pine Script v5", "pas de sucre"
  - habitude   : "trade BTC en 1h", "yoga matin"
  - entite     : noms de personnes, lieux, projets
  - date       : anniversaires, deadlines, rendez-vous recurrents
  - pro        : metier, competences, outils utilises
  - sante      : allergies, regime, medicaments
  - famille    : conjoint, enfants (prenom + age)
  - financier  : banque, courtier, budget mensuel
  - tech       : langages preferes, frameworks, conventions de code

Reimplementation Python from scratch pour Sylea. Pas de code proprietaire.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("sylea.agent3.memory_extractor")


VALID_CATEGORIES = (
    "preference", "habitude", "entite", "date", "pro",
    "sante", "famille", "financier", "tech", "general",
)


EXTRACTION_SYSTEM_PROMPT = """Tu es un extracteur de faits personnels. On te donne un extrait de
conversation entre un utilisateur et son assistant IA. Tu dois identifier les FAITS DURABLES
qui meritent d'etre memorises pour enrichir le profil de l'utilisateur.

REGLES STRICTES :
1. Extrait UNIQUEMENT des faits durables (preferences, habitudes, entites importantes,
   dates recurrentes, infos pro/sante/famille/financiere/tech).
2. N'extrait PAS : le contexte de la tache en cours, les demandes ponctuelles,
   les salutations, les questions, les emotions passageres.
3. Chaque fait doit etre une phrase courte (max 120 chars), factuelle, en francais.
4. Chaque fait a une confidence 0.0-1.0 :
   - >= 0.9 : l'utilisateur l'a affirme explicitement
   - 0.7-0.9 : inference claire a partir du contexte
   - < 0.7 : ne l'extrait PAS (trop speculatif)
5. Deduplique : si le fait est deja dans "memoires existantes", ne l'extrait pas.
6. Maximum 5 faits par extraction.

CATEGORIES VALIDES :
preference, habitude, entite, date, pro, sante, famille, financier, tech, general

KEYS : snake_case, courts, descriptifs. Exemples :
  "pine_script_version", "trading_timeframe", "enfant_nom_prenom", "budget_mensuel"

REPONDS UNIQUEMENT en JSON de cette forme :
{
  "facts": [
    {
      "key": "snake_case_key",
      "value": "Phrase courte factuelle",
      "category": "preference|habitude|...",
      "confidence": 0.0-1.0
    }
  ]
}

Si aucun fait durable ne se degage : retourne { "facts": [] }.
"""


@dataclass
class ExtractedFact:
    key: str
    value: str
    category: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "confidence": round(self.confidence, 3),
        }


class MemoryExtractor:
    """Extracteur de faits durables via Haiku.

    Usage :
        extractor = MemoryExtractor(anthropic_client)
        facts = await extractor.extract(conversation_turns, existing_memories)
        for fact in facts:
            await _save_memory_async(user_id, fact.key, fact.value, fact.category)
    """

    def __init__(
        self,
        anthropic_client,
        model: str = "claude-haiku-4-5-20251001",
        min_confidence: float = 0.7,
        max_facts_per_run: int = 5,
    ):
        self.client = anthropic_client
        self.model = model
        self.min_confidence = min_confidence
        self.max_facts_per_run = max_facts_per_run

    async def extract(
        self,
        conversation_turns: list[dict],
        existing_memories: Optional[list[dict]] = None,
    ) -> list[ExtractedFact]:
        """Extrait les faits durables d'une liste de tours.

        conversation_turns : [{role: 'user'|'agent', content: str}, ...]
        existing_memories  : liste de memoires deja stockees (pour dedup)

        Retourne la liste des faits a stocker.
        """
        transcript = self._format_transcript(conversation_turns)
        if not transcript.strip():
            return []

        existing_block = self._format_existing(existing_memories or [])
        user_prompt = (
            f"=== MEMOIRES EXISTANTES ===\n{existing_block}\n\n"
            f"=== CONVERSATION A ANALYSER ===\n{transcript}\n\n"
            "Extrait les faits durables nouveaux (pas deja dans les memoires existantes)."
        )

        try:
            # Support des deux types de clients : AsyncAnthropic (natif async)
            # et Anthropic (sync, wrappe dans to_thread).
            create_kwargs = dict(
                model=self.model,
                max_tokens=800,
                system=[{
                    "type": "text",
                    "text": EXTRACTION_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_prompt}],
            )
            # Detection : AsyncAnthropic a une classe qui contient "Async" dans son nom
            client_cls_name = type(self.client).__name__
            if "Async" in client_cls_name:
                resp = await self.client.messages.create(**create_kwargs)
            else:
                resp = await asyncio.to_thread(
                    self.client.messages.create, **create_kwargs
                )
            raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
        except Exception as e:
            logger.warning(f"MemoryExtractor LLM call failed: {e}")
            return []

        return self._parse_and_filter(raw, existing_memories or [])

    # ── Formatage ──

    @staticmethod
    def _format_transcript(turns: list[dict]) -> str:
        """Formate la conversation pour le LLM. Tronque les tours trop longs."""
        lines = []
        for t in turns[-20:]:  # Max 20 derniers tours
            role = t.get("role", "?")
            content = t.get("content", "")
            if isinstance(content, list):
                # Extraire le texte des blocs
                content = " ".join(
                    c.get("text", "") for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
            content = str(content)[:600]
            if content.strip():
                role_label = "USER" if role == "user" else "AGENT"
                lines.append(f"[{role_label}] {content}")
        return "\n".join(lines)

    @staticmethod
    def _format_existing(memories: list[dict]) -> str:
        """Formate les memoires existantes (pour dedup)."""
        if not memories:
            return "(aucune)"
        lines = []
        for m in memories[:30]:  # Limite pour ne pas exploser le prompt
            key = m.get("key", "?")
            value = str(m.get("value", ""))[:120]
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    # ── Parsing ──

    def _parse_and_filter(
        self,
        raw: str,
        existing_memories: list[dict],
    ) -> list[ExtractedFact]:
        """Parse le JSON du LLM et filtre (confidence + dedup)."""
        data = self._parse_json(raw)
        if not data:
            logger.warning(f"MemoryExtractor could not parse JSON: {raw[:200]}")
            return []

        raw_facts = data.get("facts", [])
        if not isinstance(raw_facts, list):
            return []

        existing_keys = {m.get("key", "").lower() for m in existing_memories}
        existing_values = {str(m.get("value", "")).lower() for m in existing_memories}

        out: list[ExtractedFact] = []
        for f in raw_facts[: self.max_facts_per_run * 2]:  # marge pour filtrer
            try:
                key = str(f.get("key", "")).strip().lower()[:80]
                value = str(f.get("value", "")).strip()[:240]
                category = str(f.get("category", "general")).strip().lower()
                confidence = float(f.get("confidence", 0.0))
            except Exception:
                continue

            if not key or not value:
                continue
            if confidence < self.min_confidence:
                continue
            if category not in VALID_CATEGORIES:
                category = "general"
            # Dedup : meme key ou meme value deja present
            if key in existing_keys:
                continue
            if value.lower() in existing_values:
                continue
            # Sanity check sur le key (pas d'espaces, pas de caracteres exotiques)
            if not re.match(r"^[a-z0-9_\-]+$", key):
                # Essayer de normaliser
                key_norm = re.sub(r"[^a-z0-9_\-]", "_", key)[:80]
                if not key_norm:
                    continue
                key = key_norm

            out.append(ExtractedFact(
                key=key, value=value, category=category, confidence=confidence,
            ))
            if len(out) >= self.max_facts_per_run:
                break

        return out

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        if not raw:
            return None
        try:
            return json.loads(raw.strip())
        except Exception:
            pass
        try:
            start = raw.find("{")
            if start >= 0:
                decoder = json.JSONDecoder()
                data, _ = decoder.raw_decode(raw[start:])
                return data
        except Exception:
            pass
        blocks = re.findall(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
        for b in blocks:
            try:
                return json.loads(b.strip())
            except Exception:
                continue
        return None


# ── Strategie de declenchement ──

class ExtractionScheduler:
    """Decide quand lancer l'extraction : apres N tours, ou sur deltas significatifs.

    State per-user : nb de tours depuis la derniere extraction.

    Strategie equilibree cost <-> qualite :
      - Skip uniquement les messages triviaux (< 50 chars : "ok", "merci")
      - Trigger tous les 3 turns (latence mem 2x meilleure que 6)
      - Override "fact-rich" : trigger immediat si keywords indicateurs detectes
        meme sur message court (ex: "ma chatte s'appelle Mochi" = 30 chars
        mais contient "ma" + nom propre majuscule).

    Cost estime : ~$0.05/mois/user actif (vs ~$0.02 avec ancien seuil 300/6t).
    """

    # Keywords FR/EN indiquant qu'un fact est probablement enonce
    _FACT_HINTS = (
        # Possessifs
        " mon ", " ma ", " mes ", " my ", " our ",
        # Identite
        "je m'appelle", "je suis ", "i am ", "i'm ",
        # Possession / preference
        "j'ai ", "i have ", "j'aime ", "i like ", "je deteste ", "je hais ",
        # Profession / lieu
        "je travaille", "j'habite", "je vis ", "i work", "i live",
        # Anniversaire / age
        "anniversaire", "birthday", "j'ai ans", " ans ",
    )

    def __init__(self, trigger_every_n_turns: int = 3, min_chars: int = 50):
        self.trigger_every_n_turns = trigger_every_n_turns
        self.min_chars = min_chars
        self._turn_counters: dict[str, int] = {}
        self._last_text: dict[str, str] = {}

    def _is_fact_rich(self, text: str) -> bool:
        """Heuristique : message court mais probablement porteur de facts."""
        if not text:
            return False
        low = text.lower()
        # 1) Hint keywords
        for hint in self._FACT_HINTS:
            if hint in low:
                return True
        # 2) Nom propre (mot capitalise hors debut + len > 2)
        import re
        if re.search(r"\s[A-ZÉÀÈÙÂÊÎÔÛ][a-zéàèùâêîôû]{2,}", text):
            return True
        # 3) Annee 19xx / 20xx (= date de naissance, evenement)
        if re.search(r"\b(19|20)\d{2}\b", text):
            return True
        return False

    def should_extract(
        self,
        user_id: str,
        turns_since_last: Optional[int] = None,
        conversation_chars: int = 0,
        last_text: str = "",
    ) -> bool:
        # 1) Skip messages triviaux
        if conversation_chars < self.min_chars and not self._is_fact_rich(last_text):
            return False

        # 2) Override fact-rich : trigger immediat
        if last_text and self._is_fact_rich(last_text):
            self._turn_counters[user_id] = 0
            return True

        # 3) Logique standard : trigger tous les N turns
        if turns_since_last is not None:
            return turns_since_last >= self.trigger_every_n_turns
        self._turn_counters[user_id] = self._turn_counters.get(user_id, 0) + 1
        if self._turn_counters[user_id] >= self.trigger_every_n_turns:
            self._turn_counters[user_id] = 0
            return True
        return False

    def force_reset(self, user_id: str):
        self._turn_counters[user_id] = 0


# ── Singleton ──

_scheduler: Optional[ExtractionScheduler] = None


def get_extraction_scheduler() -> ExtractionScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ExtractionScheduler()
    return _scheduler
