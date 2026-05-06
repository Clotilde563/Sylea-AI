"""
Export Anki .apkg pour les fiches generees (Sprint 3 Ecoute active).

Strategie : on parse la fiche markdown produite par fiche_generator pour
en extraire des paires Q/R logiques, puis on les serialise en Anki deck
package via genanki.

Heuristique d'extraction de cards :
  - Definitions ("**terme** : definition")    -> Q: "Definition de TERME"
                                                 R: definition
  - Theoremes / Lois (blockquote)              -> Q: "Enonce du theoreme N"
                                                 R: contenu blockquote
  - "A retenir" ou "To remember" bullets       -> Q: question reconstruite
                                                 R: bullet
  - Fallback (si aucune Q/R detectee)          -> 1 card par section H2,
                                                 Q="Resume de SECTION"
                                                 R=contenu de la section.

genanki utilise un model_id stable (1st prep -> reproductible) et
deck_id base sur un hash deterministe du titre, pour permettre les
re-imports sans dupliquer.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Tuple


# Anki deterministic model & deck IDs (entiers stables 31-bit signe)
_MODEL_ID = 1735471234  # arbitrary fixed
_MODEL_NAME = "Sylea Cours - Basic"


def _stable_int_id(seed: str) -> int:
    """Hash deterministe -> int 31-bit pour Anki deck_id."""
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFFFFFF


def _is_garbage_card(term: str, definition: str) -> bool:
    """Filtre les paires Q/R semantiquement faibles ou nuisibles."""
    t = term.strip().lower()
    d = definition.strip()
    d_lower = d.lower()
    # Definition trop courte ou trop longue
    if len(d) < 12 or len(d) > 600:
        return True
    if len(t) > 80 or len(t) < 3:
        return True
    # Definition est un autre terme en gras seul, sans contenu
    # (ex: "**Faute du salarie** : Fait non-fautif du salarie")
    # -> on detecte que la definition est essentiellement un AUTRE terme.
    if re.fullmatch(r"\*\*[^*]+\*\*\.?", d):
        return True
    if re.fullmatch(r"[A-Za-z][^.!?]{2,80}", d) and "**" not in d:
        # Definition = phrase courte sans verbe -> probablement un titre
        # detache, pas une vraie definition.
        verbs = ["est ", "sont ", "designe", "désigne", "consiste",
                 "represente", "représente", "permet", "fait", "concerne",
                 "correspond", "renvoie", "definit", "définit", "vise",
                 "regroupe", "implique"]
        if not any(v in d_lower for v in verbs):
            return True
    # Anti-paradoxe : terme et definition partagent l'inverse semantique
    # (ex: "faute" / "non-fautif", "fini" / "infini").
    # Heuristique simple : meme racine + prefixe negatif dans la def.
    neg_prefixes = ["non-", "non ", "in", "il", "im", "ir", "an", "a"]
    for p in neg_prefixes:
        if p in d_lower and t.split()[0] in d_lower:
            # Le terme apparait dans la def avec un prefixe de negation
            if re.search(rf"\b{p}{re.escape(t.split()[0])}", d_lower):
                return True
    # Skip "Theoreme 1" / "Loi 3" — labels SEULS avec numero (deja en blockquote
    # ailleurs). On accepte "Loi" tout court parce que c'est un terme valide
    # avec une vraie definition derriere.
    if re.match(r"^(theoreme|loi|proposition|lemme|corollaire)\s+\d+$", t):
        return True
    return False


def extract_cards(fiche_markdown: str) -> list[tuple[str, str]]:
    """Renvoie une liste de (question, reponse) extraites de la fiche.

    L'heuristique privilegie :
      1. Definitions formatees "**terme** : ..." ou "- **terme** — ..."
      2. Blockquotes contenant > **Theoreme N** ou > Loi/Citation
      3. Items dans la section "A retenir" / "To remember"

    Filtre les cards "antinomiques" : si la definition est juste un
    terme en gras seul (ex: "**Faute du salarie** : **Fait non-fautif
    du salarie**" -> rien d'utile), on rejette.

    Si aucune card n'est extraite, fallback : 1 card par section H2.
    """
    cards: list[tuple[str, str]] = []

    # 1. Definitions : "- **terme** : definition" OU "- **terme** — def"
    #    On accepte aussi sans le tiret en debut.
    def_pattern = re.compile(
        r"(?:^|\n)\s*[-*]?\s*\*\*([^*\n]+?)\*\*\s*[:—–-]\s*([^\n]+)",
        re.M,
    )
    for m in def_pattern.finditer(fiche_markdown):
        term, definition = m.group(1).strip(), m.group(2).strip()
        if _is_garbage_card(term, definition):
            continue
        # Skip labels "Theoreme N" / "Loi N" — leur enonce vit en blockquote
        if re.match(r"^(theoreme|loi|proposition|lemme|corollaire)\s+\d+$", term.lower()):
            continue
        cards.append((f"Definition de **{term}**", definition))

    # 2. Blockquotes "> **Theoreme N** (Nom) — Enonce."
    quote_pattern = re.compile(
        r"^>\s*\*\*([^*\n]+?)\*\*\s*(?:\(([^)]+)\))?\s*[—–-]?\s*(.+?)$",
        re.M,
    )
    for m in quote_pattern.finditer(fiche_markdown):
        kind, name, body = m.group(1).strip(), (m.group(2) or "").strip(), m.group(3).strip()
        label = f"{kind}" + (f" ({name})" if name else "")
        if len(body) >= 5:
            cards.append((f"Enonce de **{label}**", body))

    # 3. Section "A retenir" / "To remember"
    retenir_pattern = re.compile(
        r"##\s+(?:A retenir|To remember)\s*\n(.+?)(?=\n##|\Z)",
        re.S | re.I,
    )
    m = retenir_pattern.search(fiche_markdown)
    if m:
        section = m.group(1)
        for bullet in re.finditer(r"^\s*[-*]\s+(.+)$", section, re.M):
            content = bullet.group(1).strip()
            if len(content) < 8:
                continue
            # Reconstruit une question naïve a partir du bullet
            # ex: "**Theoreme de Pythagore** est essentiel" -> "Que retenir ? -> ..."
            cards.append(("Point cle a retenir", content))

    # 4. Fallback : 1 card par section H2 si rien extrait
    if not cards:
        section_pattern = re.compile(
            r"^##\s+(.+?)\s*\n(.+?)(?=\n##|\Z)", re.M | re.S,
        )
        for m in section_pattern.finditer(fiche_markdown):
            title, body = m.group(1).strip(), m.group(2).strip()
            # Tronque pour ne pas avoir des cards de 3 pages
            short = body[:500]
            if len(body) > 500:
                short += "…"
            if short:
                cards.append((f"Resume : {title}", short))

    # Dedupe en preservant l'ordre
    seen = set()
    unique = []
    for q, a in cards:
        key = (q, a)
        if key in seen:
            continue
        seen.add(key)
        unique.append((q, a))

    return unique


def build_apkg_from_cards(
    titre: str,
    matiere: str,
    cards: list[tuple[str, str]],
    output_path: str | Path,
) -> dict:
    """Construit un .apkg Anki a partir d'une liste pre-formee de
    (question, reponse). Utilise quand les cards sont generees par LLM
    (route privilegiee). Le .apkg garde model_id stable + deck_id
    deterministe pour permettre re-imports incrementaux.
    """
    if not cards:
        return {"ok": False, "error": "no_cards_extracted", "card_count": 0}
    return _build_apkg_internal(titre=titre, matiere=matiere, cards=cards,
                                output_path=output_path)


def build_apkg(
    titre: str,
    matiere: str,
    fiche_markdown: str,
    output_path: str | Path,
) -> dict:
    """Construit un .apkg Anki contenant les cards extraites de la fiche
    par heuristique regex. Fallback quand le LLM est indisponible.

    Returns {ok, card_count, output_path, model_id, deck_id}.
    """
    cards = extract_cards(fiche_markdown)
    if not cards:
        return {"ok": False, "error": "no_cards_extracted", "card_count": 0}
    return _build_apkg_internal(titre=titre, matiere=matiere, cards=cards,
                                output_path=output_path)


def _build_apkg_internal(
    titre: str,
    matiere: str,
    cards: list[tuple[str, str]],
    output_path: str | Path,
) -> dict:
    # Import paresseux : genanki est lourd au load.
    import genanki

    # Model basique Q/R
    model = genanki.Model(
        _MODEL_ID,
        _MODEL_NAME,
        fields=[{"name": "Question"}, {"name": "Answer"}],
        templates=[{
            "name": "Card 1",
            "qfmt": "{{Question}}",
            "afmt": '{{FrontSide}}<hr id="answer">{{Answer}}',
        }],
        css="""
            .card {
              font-family: -apple-system, "Segoe UI", sans-serif;
              font-size: 18px;
              text-align: left;
              color: #1a1a2e;
              padding: 18px;
            }
            .card strong { color: #0a3460; }
            .card hr { border: 0; border-top: 1px solid #ccc; margin: 12px 0; }
        """,
    )

    deck_id = _stable_int_id(f"sylea::{matiere}::{titre}")
    deck = genanki.Deck(deck_id, f"Sylea - {matiere.capitalize()} - {titre}")

    for question, answer in cards:
        # genanki accepte du HTML simple. On garde le markdown brut tel quel
        # (Anki rend pas le markdown mais le ** est suffisamment lisible).
        # On convertit juste les ** en <b> pour que le gras soit honore.
        q_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", question)
        a_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", answer)
        # Saut de ligne en HTML
        a_html = a_html.replace("\n", "<br>")
        deck.add_note(genanki.Note(model=model, fields=[q_html, a_html]))

    pkg = genanki.Package(deck)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pkg.write_to_file(str(output_path))

    return {
        "ok": True,
        "card_count": len(cards),
        "output_path": str(output_path),
        "model_id": _MODEL_ID,
        "deck_id": deck_id,
        "deck_name": f"Sylea - {matiere.capitalize()} - {titre}",
    }
