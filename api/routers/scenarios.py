"""
Router Scenarios — Plans d'action What-If pour Sylea.AI.

Prefix : /api/scenarios
Table  : scenarios

Permet de creer des scenarios hypothetiques, generer 3 plans d'action
(Prudent / Equilibre / Intensif) avec courbes de completion, et exporter en PDF.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.dependencies import get_db, get_optional_user
from api.routers.agent3_openclaw import WORKSPACE_BASE, get_workspace_folder_name
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository

logger = logging.getLogger("scenarios")

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

# ── Export directory ─────────────────────────────────────────────────────────
SCENARIO_EXPORT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "scenario_exports"
SCENARIO_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# ── Schemas ──────────────────────────────────────────────────────────────────

class VariableIn(BaseModel):
    name: str
    value: float | str
    impact_area: str = ""  # carriere/sante/finance/relation/developpement


class ScenarioCreateIn(BaseModel):
    title: str
    hypothesis: str
    variables: list[VariableIn] = []
    timeline_months: int = Field(default=12, ge=1, le=120)


class ScenarioOut(BaseModel):
    id: str
    title: str
    description: str
    hypothesis: str
    variables_json: str
    result_json: str
    probability_before: float
    probability_after: float
    timeline_months: int
    chart_data_json: str
    created_at: str
    updated_at: str


class ScenarioCompareIn(BaseModel):
    scenario_ids: list[str] = Field(..., min_length=2, max_length=5)


class ScenarioCompareOut(BaseModel):
    scenarios: list[ScenarioOut]
    comparison: dict


# ── DB schema init ───────────────────────────────────────────────────────────

def _ensure_scenario_tables(db: DatabaseManager):
    """Create scenarios table if it doesn't exist."""
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id TEXT PRIMARY KEY,
            auth_user_id TEXT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            hypothesis TEXT DEFAULT '',
            variables_json TEXT DEFAULT '[]',
            result_json TEXT DEFAULT '{}',
            probability_before REAL DEFAULT 0,
            probability_after REAL DEFAULT 0,
            timeline_months INTEGER DEFAULT 12,
            chart_data_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    db.conn.commit()


def _gen_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Claude AI helper (same pattern as agent3_openclaw) ───────────────────────

async def _claude_chat(system_prompt: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """Direct Claude API call for scenario analysis."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return ""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=messages,
            )
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Claude API failed for scenario: {e}")
        return ""


# ── Full profile data scanner ────────────────────────────────────────────────

def _get_current_probability(db: DatabaseManager, user_id: str | None) -> float:
    """Get the current probability from user profile."""
    try:
        if user_id:
            row = db.conn.execute(
                "SELECT probabilite_actuelle FROM profil_utilisateur WHERE auth_user_id = ? ORDER BY mis_a_jour_le DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        else:
            row = db.conn.execute(
                "SELECT probabilite_actuelle FROM profil_utilisateur ORDER BY mis_a_jour_le DESC LIMIT 1"
            ).fetchone()
        if row:
            return float(row["probabilite_actuelle"])
    except Exception:
        pass
    return 45.0  # Default fallback


def _get_user_profile_data(db: DatabaseManager, user_id: str | None) -> dict:
    """Scan ALL relevant tables for comprehensive profile context."""
    result = {
        "nom": "Utilisateur",
        "age": 30,
        "profession": "",
        "ville": "",
        "situation_familiale": "",
        "revenu_annuel": 0,
        "patrimoine_estime": 0,
        "charges_mensuelles": 0,
        "objectif_financier": 0,
        "heures_travail": 8.0,
        "heures_sommeil": 7.0,
        "heures_loisirs": 2.0,
        "heures_transport": 1.0,
        "heures_objectif": 1.0,
        "niveau_sante": 7,
        "niveau_stress": 5,
        "niveau_energie": 7,
        "niveau_bonheur": 7,
        "competences": [],
        "diplomes": [],
        "langues": [],
        "objectif": "",
        "categorie": "",
        "deadline": "",
        "probabilite": 45.0,
        "sous_objectifs": [],
        "decisions_recentes": [],
        "bilans_moyens": {},
        "taches_recentes": [],
    }

    try:
        # ── 1. profil_utilisateur: ALL fields ────────────────────────────
        if user_id:
            row = db.conn.execute(
                "SELECT * FROM profil_utilisateur WHERE auth_user_id = ? ORDER BY mis_a_jour_le DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        else:
            row = db.conn.execute(
                "SELECT * FROM profil_utilisateur ORDER BY mis_a_jour_le DESC LIMIT 1"
            ).fetchone()

        if row:
            profile_id = row["id"]
            result["nom"] = row["nom"] or "Utilisateur"
            result["age"] = row["age"] or 30
            result["profession"] = row["profession"] or ""
            result["ville"] = row["ville"] or ""
            result["situation_familiale"] = row["situation_familiale"] or ""
            result["revenu_annuel"] = float(row["revenu_annuel"] or 0)
            result["patrimoine_estime"] = float(row["patrimoine_estime"] or 0)
            result["charges_mensuelles"] = float(row["charges_mensuelles"] or 0)
            result["objectif_financier"] = float(row["objectif_financier"] or 0)
            result["heures_travail"] = float(row["heures_travail"] or 8)
            result["heures_sommeil"] = float(row["heures_sommeil"] or 7)
            result["heures_loisirs"] = float(row["heures_loisirs"] or 2)
            result["heures_transport"] = float(row["heures_transport"] or 1)
            result["heures_objectif"] = float(row["heures_objectif"] or 1)
            result["niveau_sante"] = int(row["niveau_sante"] or 7)
            result["niveau_stress"] = int(row["niveau_stress"] or 5)
            result["niveau_energie"] = int(row["niveau_energie"] or 7)
            result["niveau_bonheur"] = int(row["niveau_bonheur"] or 7)
            result["objectif"] = row["objectif_description"] or ""
            result["categorie"] = row["objectif_categorie"] or ""
            result["deadline"] = row["objectif_deadline"] or ""
            result["probabilite"] = float(row["probabilite_actuelle"] or 45)

            # Parse comma-separated lists
            for field in ("competences", "diplomes", "langues"):
                raw = row[field] or ""
                if raw.startswith("["):
                    try:
                        result[field] = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        result[field] = [x.strip() for x in raw.split(",") if x.strip()]
                else:
                    result[field] = [x.strip() for x in raw.split(",") if x.strip()]

            # ── 2. sous_objectifs ─────────────────────────────────────────
            try:
                so_rows = db.conn.execute(
                    "SELECT titre, description, progression, ordre, temps_estime FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
                    (profile_id,),
                ).fetchall()
                result["sous_objectifs"] = [
                    {
                        "titre": r["titre"],
                        "description": r["description"] or "",
                        "progression": float(r["progression"] or 0),
                        "temps_estime": float(r["temps_estime"] or 0),
                    }
                    for r in so_rows
                ]
            except Exception:
                pass

            # ── 3. decisions: last 10 for context ─────────────────────────
            try:
                dec_rows = db.conn.execute(
                    "SELECT question, probabilite_avant, probabilite_apres, cree_le FROM decisions WHERE user_id = ? ORDER BY cree_le DESC LIMIT 10",
                    (profile_id,),
                ).fetchall()
                result["decisions_recentes"] = [
                    {
                        "question": r["question"],
                        "prob_avant": float(r["probabilite_avant"] or 0),
                        "prob_apres": float(r["probabilite_apres"] or 0) if r["probabilite_apres"] else None,
                        "date": (r["cree_le"] or "")[:10],
                    }
                    for r in dec_rows
                ]
            except Exception:
                pass

            # ── 4. bilans_quotidiens: averages ────────────────────────────
            try:
                bilan_row = db.conn.execute(
                    """SELECT
                        AVG(niveau_sante) as avg_sante,
                        AVG(niveau_stress) as avg_stress,
                        AVG(niveau_energie) as avg_energie,
                        AVG(niveau_bonheur) as avg_bonheur,
                        AVG(heures_objectif) as avg_heures_objectif,
                        COUNT(*) as nb_bilans
                    FROM bilans_quotidiens WHERE user_id = ?""",
                    (profile_id,),
                ).fetchone()
                if bilan_row and bilan_row["nb_bilans"] and int(bilan_row["nb_bilans"]) > 0:
                    result["bilans_moyens"] = {
                        "avg_sante": round(float(bilan_row["avg_sante"] or 0), 1),
                        "avg_stress": round(float(bilan_row["avg_stress"] or 0), 1),
                        "avg_energie": round(float(bilan_row["avg_energie"] or 0), 1),
                        "avg_bonheur": round(float(bilan_row["avg_bonheur"] or 0), 1),
                        "avg_heures_objectif": round(float(bilan_row["avg_heures_objectif"] or 0), 1),
                        "nb_bilans": int(bilan_row["nb_bilans"]),
                    }
            except Exception:
                pass

            # ── 5. taches_quotidiennes: recent tasks ──────────────────────
            try:
                tache_rows = db.conn.execute(
                    "SELECT date, taches_json, statut FROM taches_quotidiennes WHERE user_id = ? ORDER BY date DESC LIMIT 5",
                    (profile_id,),
                ).fetchall()
                for tr in tache_rows:
                    try:
                        taches = json.loads(tr["taches_json"] or "[]")
                        total = len(taches)
                        done = sum(1 for t in taches if t.get("completee"))
                        result["taches_recentes"].append({
                            "date": tr["date"],
                            "total": total,
                            "completees": done,
                            "statut": tr["statut"] or "",
                        })
                    except (json.JSONDecodeError, TypeError):
                        pass
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"Error scanning profile data: {e}")

    return result


# ── Simulation engine — completion % curves ──────────────────────────────────

def _simulate_trajectories(
    timeline_months: int,
    plan_durations: dict[str, int],
) -> dict:
    """Generate completion percentage curves for the 3 plans.

    Returns chart_data_json format:
    {labels: ["M1","M2",...], plan_prudent: [...], plan_equilibre: [...], plan_intensif: [...]}

    Each plan follows an S-curve reaching 100% at its specific duration.
    X-axis goes up to the longest plan's duration.
    """
    max_duration = max(plan_durations.values())
    labels = [f"M{i}" for i in range(1, max_duration + 1)]

    def _s_curve(month: int, total_months: int) -> float:
        """S-curve (logistic) reaching ~100% at total_months."""
        if month >= total_months:
            return 100.0
        if total_months <= 0:
            return 100.0
        # Normalized progress (0 to 1)
        t = month / total_months
        # Logistic S-curve: steeper in the middle
        # Using smoothstep for clean curves
        progress = t * t * (3 - 2 * t)
        # Add slight acceleration in mid-section
        val = progress * 100.0
        # Small realistic noise
        noise = math.sin(month * 1.7) * 1.2
        val = val + noise
        return round(max(0.0, min(100.0, val)), 1)

    plan_prudent = []
    plan_equilibre = []
    plan_intensif = []

    dur_p = plan_durations.get("prudent", max_duration)
    dur_e = plan_durations.get("equilibre", timeline_months)
    dur_i = plan_durations.get("intensif", max(1, int(timeline_months * 0.6)))

    for month in range(1, max_duration + 1):
        plan_prudent.append(_s_curve(month, dur_p))
        plan_equilibre.append(_s_curve(month, dur_e))
        plan_intensif.append(_s_curve(month, dur_i))

    return {
        "labels": labels,
        "plan_prudent": plan_prudent,
        "plan_equilibre": plan_equilibre,
        "plan_intensif": plan_intensif,
    }


# ── PDF export helpers ───────────────────────────────────────────────────────

def _sanitize_text(text: str) -> str:
    """Replace non-latin1 characters for fpdf2 Helvetica compatibility."""
    replacements = {
        "\u00e9": "e", "\u00e8": "e", "\u00ea": "e", "\u00eb": "e",
        "\u00e0": "a", "\u00e2": "a", "\u00e4": "a",
        "\u00f4": "o", "\u00f6": "o",
        "\u00fb": "u", "\u00fc": "u", "\u00f9": "u",
        "\u00ee": "i", "\u00ef": "i",
        "\u00e7": "c",
        "\u00c9": "E", "\u00c8": "E", "\u00ca": "E",
        "\u00c0": "A", "\u00c2": "A",
        "\u00d4": "O", "\u00d6": "O",
        "\u00db": "U", "\u00dc": "U",
        "\u00ce": "I", "\u00cf": "I",
        "\u00c7": "C",
        "\u0153": "oe", "\u0152": "OE",
        "\u00ab": "<<", "\u00bb": ">>",
        "\u2019": "'", "\u2018": "'",
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "--",
        "\u2026": "...",
        "\u20ac": "EUR", "\u00a3": "GBP",
        "\u2022": "-", "\u25cf": "-", "\u25cb": "o",
        "\u2192": "->", "\u2190": "<-", "\u2194": "<->",
        "\u2705": "[OK]", "\u274c": "[X]", "\u26a0": "[!]",
        "\u00b0": "deg",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text


def _strip_markdown(text: str) -> str:
    """Remove markdown syntax (##, **, -, etc.) and return clean text."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            cleaned.append("")
            continue
        # Remove heading markers
        line = re.sub(r'^#{1,6}\s*', '', line)
        # Remove bold/italic markers
        line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
        line = re.sub(r'\*([^*]+)\*', r'\1', line)
        # Remove leading "- " bullet (we handle bullets separately)
        # Keep the line as-is otherwise
        cleaned.append(line)
    return "\n".join(cleaned)


def _parse_analysis_sections(analysis: str) -> list[dict]:
    """Parse markdown analysis into structured sections.

    Returns list of {title, items, text} dicts.
    """
    sections: list[dict] = []
    current: dict | None = None

    for line in analysis.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Detect heading (## or ###)
        heading_match = re.match(r'^#{1,6}\s+(.+)$', stripped)
        if heading_match:
            if current:
                sections.append(current)
            current = {"title": heading_match.group(1).strip(), "items": [], "text": ""}
            continue

        if current is None:
            current = {"title": "", "items": [], "text": ""}

        # Detect bullet points
        bullet_match = re.match(r'^[-*]\s+(.+)$', stripped)
        numbered_match = re.match(r'^\d+\.\s+(.+)$', stripped)
        if bullet_match:
            item = bullet_match.group(1)
            # Remove bold markers
            item = re.sub(r'\*\*([^*]+)\*\*', r'\1', item)
            current["items"].append(item)
        elif numbered_match:
            item = numbered_match.group(1)
            item = re.sub(r'\*\*([^*]+)\*\*', r'\1', item)
            current["items"].append(item)
        else:
            # Plain text paragraph
            clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', stripped)
            if current["text"]:
                current["text"] += " " + clean
            else:
                current["text"] = clean

    if current:
        sections.append(current)
    return sections


# ── Color palette for PDF ────────────────────────────────────────────────────
_PDF_COLORS = {
    "primary": (99, 102, 241),       # Indigo
    "primary_dark": (67, 56, 202),    # Darker indigo
    "success": (16, 185, 129),        # Emerald green
    "danger": (239, 68, 68),          # Red
    "warning": (245, 158, 11),        # Amber
    "info": (59, 130, 246),           # Blue
    "purple": (139, 92, 246),         # Violet
    "text_dark": (30, 30, 45),        # Near black
    "text_mid": (80, 80, 100),        # Gray
    "text_light": (130, 130, 150),    # Light gray
    "bg_light": (245, 245, 255),      # Very light indigo
    "bg_section": (240, 242, 255),    # Section background
    "white": (255, 255, 255),
    "border": (200, 205, 230),        # Light border
}


class _SyleaPDF:
    """FPDF subclass with automatic header/footer for Sylea reports."""

    def __init__(self, title: str, created: str, timeline: int):
        from fpdf import FPDF

        class _PDF(FPDF):
            _title = title
            _created = created
            _timeline = timeline
            _is_first_page = True

            def header(self):
                if self._is_first_page:
                    return  # First page has custom banner
                # Thin colored bar on top of continuation pages
                self.set_fill_color(*_PDF_COLORS["primary"])
                self.rect(0, 0, 210, 4, "F")
                self.set_y(8)

            def footer(self):
                self.set_y(-12)
                self.set_draw_color(*_PDF_COLORS["border"])
                self.line(15, self.get_y() - 2, 195, self.get_y() - 2)
                self.set_text_color(*_PDF_COLORS["text_light"])
                self.set_font("Helvetica", "I", 7)
                self.cell(90, 5, "Sylea.AI - Rapport genere par intelligence artificielle")
                self.cell(90, 5, f"Page {self.page_no()}/{{nb}}", align="R")

        self.pdf = _PDF()
        self.pdf.alias_nb_pages()
        self.pdf.set_auto_page_break(auto=True, margin=18)
        self.pw = 210
        self.margin = 15
        self.cw = self.pw - 2 * self.margin

    def build(self, scenario: dict) -> None:
        pdf = self.pdf
        margin = self.margin
        cw = self.cw
        pw = self.pw

        title = _sanitize_text(scenario.get("title", "Scenario"))
        hypothesis = _sanitize_text(scenario.get("hypothesis", ""))
        timeline = scenario.get("timeline_months", 12)
        created = scenario.get("created_at", "")[:10]

        # Parse plans from result_json
        try:
            result = json.loads(scenario.get("result_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            result = {}
        plans = result.get("plans", [])

        # ── PAGE 1 — Banner ──────────────────────────────────────────────
        pdf.add_page()
        pdf.set_left_margin(margin)
        pdf.set_right_margin(margin)

        # Gradient-like banner
        pdf.set_fill_color(*_PDF_COLORS["primary_dark"])
        pdf.rect(0, 0, pw, 52, "F")
        pdf.set_fill_color(*_PDF_COLORS["primary"])
        pdf.rect(0, 0, pw, 48, "F")

        pdf.set_xy(margin, 8)
        pdf.set_text_color(*_PDF_COLORS["white"])
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(cw, 5, "SYLEA.AI  |  ANALYSE PAR PLANS D'ACTION", ln=True)
        pdf.set_xy(margin, 18)
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(cw, 12, title[:60], ln=True)
        pdf.set_xy(margin, 35)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(cw, 5, f"Genere le {created}  |  Projection sur {timeline} mois", ln=True)

        pdf.set_y(58)
        pdf._is_first_page = False  # Next pages use thin bar header

        # ── Hypothesis box ────────────────────────────────────────────────
        if hypothesis:
            pdf.set_font("Helvetica", "", 9)
            nb_lines = max(1, pdf.get_string_width(hypothesis[:300]) / (cw - 16)) + 1
            box_h = 14 + int(nb_lines) * 4.5
            box_h = max(22, min(40, box_h))

            box_y = pdf.get_y()
            pdf.set_fill_color(*_PDF_COLORS["bg_light"])
            pdf.set_draw_color(*_PDF_COLORS["primary"])
            pdf.rect(margin, box_y, cw, box_h, "DF")
            pdf.set_fill_color(*_PDF_COLORS["primary"])
            pdf.rect(margin, box_y, 3, box_h, "F")

            pdf.set_xy(margin + 7, box_y + 3)
            pdf.set_text_color(*_PDF_COLORS["primary"])
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, "HYPOTHESE", ln=True)
            pdf.set_xy(margin + 7, box_y + 10)
            pdf.set_text_color(*_PDF_COLORS["text_dark"])
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(cw - 12, 4.5, hypothesis[:300])
            pdf.set_y(box_y + box_h + 4)

        # ── 3 Plan cards ─────────────────────────────────────────────────
        card_w = (cw - 8) / 3
        cy = pdf.get_y()

        # Default plan data if no plans in result
        default_plans = [
            {"name": "Plan Prudent", "duration_months": int(timeline * 1.5), "color": "success"},
            {"name": "Plan Equilibre", "duration_months": timeline, "color": "primary"},
            {"name": "Plan Intensif", "duration_months": max(1, int(timeline * 0.6)), "color": "danger"},
        ]
        display_plans = plans if len(plans) >= 3 else default_plans

        plan_colors_map = {
            "success": _PDF_COLORS["success"],
            "primary": _PDF_COLORS["primary"],
            "danger": _PDF_COLORS["danger"],
        }

        for i, plan in enumerate(display_plans[:3]):
            plan_name = _sanitize_text(plan.get("name", f"Plan {i+1}"))
            dur = plan.get("duration_months", timeline)
            color_key = plan.get("color", "primary")
            color = plan_colors_map.get(color_key, _PDF_COLORS["primary"])

            x = margin + i * (card_w + 4)
            pdf.set_fill_color(*_PDF_COLORS["bg_section"])
            pdf.set_draw_color(*_PDF_COLORS["border"])
            pdf.rect(x, cy, card_w, 28, "DF")
            # Top accent line
            pdf.set_fill_color(*color)
            pdf.rect(x, cy, card_w, 2, "F")
            # Plan name
            pdf.set_xy(x + 3, cy + 5)
            pdf.set_text_color(*_PDF_COLORS["text_light"])
            pdf.set_font("Helvetica", "", 7)
            pdf.cell(card_w - 6, 4, plan_name.upper())
            # Duration
            pdf.set_xy(x + 3, cy + 12)
            pdf.set_text_color(*color)
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(card_w - 6, 10, f"{dur} mois")

        pdf.set_y(cy + 34)

        # ── Completion chart ─────────────────────────────────────────────
        try:
            chart_data = json.loads(scenario.get("chart_data_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            chart_data = {}

        plan_prudent_data = chart_data.get("plan_prudent", [])
        plan_equilibre_data = chart_data.get("plan_equilibre", [])
        plan_intensif_data = chart_data.get("plan_intensif", [])

        if plan_equilibre_data and len(plan_equilibre_data) > 1:
            chart_h = 50
            chart_x = margin + 10
            chart_cw = cw - 18

            pdf.set_text_color(*_PDF_COLORS["text_dark"])
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(cw, 6, "Courbes de completion par plan", ln=True)
            pdf.ln(1)
            chart_y = pdf.get_y()

            # Background
            pdf.set_fill_color(*_PDF_COLORS["bg_light"])
            pdf.set_draw_color(*_PDF_COLORS["border"])
            pdf.rect(margin, chart_y, cw, chart_h, "DF")

            # Y axis: 0-100%
            y_min = 0.0
            y_max = 100.0
            y_range = 100.0
            n = len(plan_equilibre_data)

            def _v2y(val):
                return chart_y + 4 + (chart_h - 12) * (1 - (val - y_min) / y_range)

            # Grid
            pdf.set_draw_color(215, 218, 235)
            pdf.set_text_color(*_PDF_COLORS["text_light"])
            pdf.set_font("Helvetica", "", 5.5)
            for i in range(5):
                gy = chart_y + 4 + (chart_h - 12) * i / 4
                gval = y_max - y_range * i / 4
                pdf.line(chart_x, gy, chart_x + chart_cw, gy)
                pdf.set_xy(margin, gy - 1.5)
                pdf.cell(9, 3, f"{gval:.0f}%", align="R")

            for i in range(n):
                lx = chart_x + chart_cw * i / max(1, n - 1)
                if i % max(1, n // 6) == 0 or i == n - 1:
                    pdf.set_xy(lx - 4, chart_y + chart_h - 7)
                    pdf.cell(8, 4, f"M{i + 1}", align="C")

            def _draw_curve(data, color, w=0.5):
                if not data or len(data) < 2:
                    return
                pdf.set_draw_color(*color)
                pdf.set_line_width(w)
                pts = min(len(data), n)
                for j in range(pts - 1):
                    x1 = chart_x + chart_cw * j / max(1, n - 1)
                    x2 = chart_x + chart_cw * (j + 1) / max(1, n - 1)
                    pdf.line(x1, _v2y(data[j]), x2, _v2y(data[j + 1]))

            # Fill area between intensif and prudent (light shading)
            if plan_intensif_data and plan_prudent_data:
                for j in range(min(len(plan_intensif_data), n) - 1):
                    x1 = chart_x + chart_cw * j / max(1, n - 1)
                    x2 = chart_x + chart_cw * (j + 1) / max(1, n - 1)
                    mid_int_y = (_v2y(plan_intensif_data[j]) + _v2y(plan_intensif_data[min(j + 1, len(plan_intensif_data) - 1)])) / 2
                    mid_pru_y = (_v2y(plan_prudent_data[j]) + _v2y(plan_prudent_data[min(j + 1, len(plan_prudent_data) - 1)])) / 2
                    band_h = max(0.5, mid_pru_y - mid_int_y)
                    pdf.set_fill_color(220, 225, 255)
                    pdf.rect(x1, mid_int_y, x2 - x1, band_h, "F")

            _draw_curve(plan_prudent_data, _PDF_COLORS["success"], 0.4)
            _draw_curve(plan_intensif_data, _PDF_COLORS["danger"], 0.4)
            _draw_curve(plan_equilibre_data, _PDF_COLORS["primary"], 0.9)

            # Endpoint dots
            for data, color in [
                (plan_equilibre_data, _PDF_COLORS["primary"]),
                (plan_prudent_data, _PDF_COLORS["success"]),
                (plan_intensif_data, _PDF_COLORS["danger"]),
            ]:
                if data:
                    pdf.set_fill_color(*color)
                    ey = _v2y(data[-1])
                    ex = chart_x + chart_cw
                    pdf.ellipse(ex - 1, ey - 1, 2, 2, "F")

            # Legend bar
            legend_y = chart_y + chart_h + 2
            pdf.set_font("Helvetica", "", 6.5)
            for i, (lbl, col) in enumerate([
                ("Plan Prudent", _PDF_COLORS["success"]),
                ("Plan Equilibre", _PDF_COLORS["primary"]),
                ("Plan Intensif", _PDF_COLORS["danger"]),
            ]):
                lx = margin + 8 + i * 48
                pdf.set_fill_color(*col)
                pdf.rect(lx, legend_y + 1, 6, 2, "F")
                pdf.set_text_color(*_PDF_COLORS["text_mid"])
                pdf.set_xy(lx + 8, legend_y - 0.5)
                pdf.cell(35, 4, lbl)

            pdf.set_y(legend_y + 7)
            pdf.set_line_width(0.2)

        # ── Separator ─────────────────────────────────────────────────────
        sep_y = pdf.get_y()
        pdf.set_draw_color(*_PDF_COLORS["border"])
        pdf.line(margin + 20, sep_y, margin + cw - 20, sep_y)
        pdf.set_y(sep_y + 4)

        # ── Analysis sections ─────────────────────────────────────────────
        analysis = result.get("analysis", "")

        if analysis:
            sections = _parse_analysis_sections(analysis)
            section_colors = [
                _PDF_COLORS["primary"], _PDF_COLORS["danger"],
                _PDF_COLORS["success"], _PDF_COLORS["warning"],
                _PDF_COLORS["info"], _PDF_COLORS["purple"],
            ]

            for idx, section in enumerate(sections):
                col = section_colors[idx % len(section_colors)]

                # Estimate section height (title + text + items)
                n_items = len(section.get("items", []))
                est_h = 12  # title
                if section["text"]:
                    est_h += 12
                est_h += n_items * 6
                # If section won't fit, force new page (keep title with content)
                remaining = 280 - pdf.get_y()  # 280 = page height - footer
                if remaining < min(est_h, 35):
                    pdf.add_page()

                # Section title
                if section["title"]:
                    t = _sanitize_text(section["title"])
                    t = re.sub(r'\*\*([^*]*)\*\*', r'\1', t)

                    sy = pdf.get_y()
                    # Colored accent bar + light tinted background
                    pdf.set_fill_color(*col)
                    pdf.rect(margin, sy, 3, 7, "F")
                    r = min(255, col[0] + (255 - col[0]) * 85 // 100)
                    g = min(255, col[1] + (255 - col[1]) * 85 // 100)
                    b = min(255, col[2] + (255 - col[2]) * 85 // 100)
                    pdf.set_fill_color(r, g, b)
                    pdf.rect(margin + 3, sy, cw - 3, 7, "F")

                    pdf.set_xy(margin + 6, sy + 0.5)
                    pdf.set_text_color(*col)
                    pdf.set_font("Helvetica", "B", 9)
                    pdf.cell(cw - 8, 6, t)
                    pdf.set_y(sy + 9)

                # Section text
                if section["text"]:
                    ct = _sanitize_text(section["text"])
                    ct = re.sub(r'\*\*([^*]*)\*\*', r'\1', ct)
                    pdf.set_text_color(*_PDF_COLORS["text_dark"])
                    pdf.set_font("Helvetica", "", 8)
                    pdf.set_x(margin + 4)
                    pdf.multi_cell(cw - 8, 4, ct)
                    pdf.ln(1.5)

                # Section items
                for item in section.get("items", []):
                    ci = _sanitize_text(item)
                    ci = re.sub(r'\*\*([^*]*)\*\*', r'\1', ci)
                    # Check space for at least one bullet
                    if pdf.get_y() > 272:
                        pdf.add_page()
                    iy = pdf.get_y()
                    pdf.set_fill_color(*col)
                    pdf.ellipse(margin + 5, iy + 1, 1.8, 1.8, "F")
                    pdf.set_xy(margin + 10, iy)
                    pdf.set_text_color(*_PDF_COLORS["text_dark"])
                    pdf.set_font("Helvetica", "", 8)
                    pdf.multi_cell(cw - 14, 4, ci)
                    pdf.ln(0.8)

                pdf.ln(2)

    def save(self, filepath: Path) -> None:
        self.pdf.output(str(filepath))


def _export_scenario_pdf(scenario: dict) -> Path:
    """Generate a colorful, professional PDF report with charts."""
    title = _sanitize_text(scenario.get("title", "Scenario"))
    created = scenario.get("created_at", "")[:10]
    timeline = scenario.get("timeline_months", 12)

    builder = _SyleaPDF(title, created, timeline)
    builder.build(scenario)

    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip().replace(" ", "_")
    filename = f"scenario_{safe_title}_{scenario['id']}.pdf"
    filepath = SCENARIO_EXPORT_DIR / filename
    builder.save(filepath)
    return filepath


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ScenarioOut])
async def list_scenarios(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """List all scenarios for the current user."""
    _ensure_scenario_tables(db)
    if user_id:
        rows = db.conn.execute(
            "SELECT * FROM scenarios WHERE auth_user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    else:
        rows = db.conn.execute(
            "SELECT * FROM scenarios ORDER BY updated_at DESC"
        ).fetchall()
    return [
        ScenarioOut(
            id=r["id"], title=r["title"], description=r["description"],
            hypothesis=r["hypothesis"], variables_json=r["variables_json"],
            result_json=r["result_json"], probability_before=r["probability_before"],
            probability_after=r["probability_after"], timeline_months=r["timeline_months"],
            chart_data_json=r["chart_data_json"], created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


@router.post("/create", response_model=ScenarioOut)
async def create_scenario(
    data: ScenarioCreateIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Create a scenario with 3 action plans (Prudent / Equilibre / Intensif).

    Scans the full user profile, generates AI-powered action plans,
    and produces completion percentage curves for each plan.
    """
    _ensure_scenario_tables(db)

    # Get full profile data
    current_prob = _get_current_probability(db, user_id)
    profile_data = _get_user_profile_data(db, user_id)

    # Prepare variables JSON
    variables_list = [
        {"name": v.name, "value": v.value, "impact_area": v.impact_area}
        for v in data.variables
    ]

    # Build comprehensive profile context for Claude
    profile_context = f"""Profil complet de l'utilisateur:
- Nom: {profile_data['nom']}, Age: {profile_data['age']} ans
- Profession: {profile_data['profession']}, Ville: {profile_data['ville']}
- Situation familiale: {profile_data['situation_familiale']}
- Revenu annuel: {profile_data['revenu_annuel']:.0f} EUR, Patrimoine: {profile_data['patrimoine_estime']:.0f} EUR
- Charges mensuelles: {profile_data['charges_mensuelles']:.0f} EUR
- Temps quotidien: travail {profile_data['heures_travail']}h, sommeil {profile_data['heures_sommeil']}h, loisirs {profile_data['heures_loisirs']}h, transport {profile_data['heures_transport']}h, objectif {profile_data['heures_objectif']}h
- Bien-etre: sante {profile_data['niveau_sante']}/10, stress {profile_data['niveau_stress']}/10, energie {profile_data['niveau_energie']}/10, bonheur {profile_data['niveau_bonheur']}/10
- Competences: {', '.join(profile_data['competences'][:10]) if profile_data['competences'] else 'non renseignees'}
- Diplomes: {', '.join(profile_data['diplomes'][:5]) if profile_data['diplomes'] else 'non renseignes'}
- Langues: {', '.join(profile_data['langues'][:5]) if profile_data['langues'] else 'non renseignees'}
- Objectif de vie: {profile_data['objectif']}
- Categorie: {profile_data['categorie']}
- Deadline: {profile_data['deadline'] or 'non definie'}
- Probabilite actuelle: {profile_data['probabilite']:.0f}%"""

    # Add sub-goals if available
    if profile_data["sous_objectifs"]:
        profile_context += "\n- Sous-objectifs:"
        for so in profile_data["sous_objectifs"][:6]:
            profile_context += f"\n  * {so['titre']} (progression: {so['progression']:.0f}%)"

    # Add daily metrics averages if available
    if profile_data["bilans_moyens"]:
        bm = profile_data["bilans_moyens"]
        profile_context += f"\n- Moyennes bilans ({bm['nb_bilans']} jours): sante {bm['avg_sante']}/10, stress {bm['avg_stress']}/10, energie {bm['avg_energie']}/10, bonheur {bm['avg_bonheur']}/10, heures objectif {bm['avg_heures_objectif']}h/jour"

    # Add recent task completion rate
    if profile_data["taches_recentes"]:
        total_t = sum(t["total"] for t in profile_data["taches_recentes"])
        done_t = sum(t["completees"] for t in profile_data["taches_recentes"])
        if total_t > 0:
            profile_context += f"\n- Taux completion taches recentes: {done_t}/{total_t} ({done_t*100//total_t}%)"

    # Compute plan durations
    dur_prudent = int(data.timeline_months * 1.5)
    dur_equilibre = data.timeline_months
    dur_intensif = max(1, int(data.timeline_months * 0.6))

    # Call Claude for AI analysis with action plans
    system_prompt = f"""Tu es un analyste strategique expert en planification de vie et gestion de projets personnels.

{profile_context}

L'utilisateur te soumet un scenario hypothetique. Tu dois generer 3 PLANS D'ACTION concrets et chronologiques pour realiser cette hypothese.

Structure ta reponse EXACTEMENT ainsi (utilise ## pour les titres):

## Synthese
Un paragraphe bref (2-3 phrases) resumant ce qu'il faut pour realiser cette hypothese, en tenant compte du profil complet de l'utilisateur.

## Plan Prudent ({dur_prudent} mois)
Le plan le plus sur, le plus progressif. Rythme soutenable.
- Etape 1 (Mois 1-X): description concrete de l'action
- Etape 2 (Mois X-Y): description concrete de l'action
- Etape 3 (Mois Y-Z): description concrete de l'action
- Etape 4 (Mois Z-W): description concrete de l'action
- Etape 5 (Mois W-{dur_prudent}): description concrete de l'action

## Plan Equilibre ({dur_equilibre} mois)
Le plan balance entre effort et temps. Rythme soutenu mais realiste.
- Etape 1 (Mois 1-X): description concrete de l'action
- Etape 2 (Mois X-Y): description concrete de l'action
- Etape 3 (Mois Y-Z): description concrete de l'action
- Etape 4 (Mois Z-W): description concrete de l'action
- Etape 5 (Mois W-{dur_equilibre}): description concrete de l'action

## Plan Intensif ({dur_intensif} mois)
Le plan le plus rapide et exigeant. Effort maximal.
- Etape 1 (Mois 1-X): description concrete de l'action
- Etape 2 (Mois X-Y): description concrete de l'action
- Etape 3 (Mois Y-Z): description concrete de l'action
- Etape 4 (Mois Z-W): description concrete de l'action
- Etape 5 (Mois W-{dur_intensif}): description concrete de l'action

## Ressources necessaires
- Liste des investissements, formations, outils, contacts necessaires
- Estimation budgetaire si pertinent

## Risques et conditions de succes
- Liste des risques principaux pour chaque plan
- Conditions cles de reussite

Reponds en francais, de maniere structuree et concise (max 600 mots). ZERO emoji. ZERO markdown bold (**). Utilise uniquement ## pour les titres et - pour les listes. Adapte les etapes au profil specifique de l'utilisateur (competences, situation financiere, temps disponible, etc.)."""

    user_prompt = f"""Scenario: {data.title}
Hypothese: {data.hypothesis}
Variables supplementaires: {json.dumps(variables_list, ensure_ascii=False)}
Timeline de reference: {data.timeline_months} mois"""

    analysis_text = await _claude_chat(
        system_prompt,
        [{"role": "user", "content": user_prompt}],
        max_tokens=1200,
    )

    # Build plans metadata
    plans = [
        {"name": "Plan Prudent", "duration_months": dur_prudent, "difficulty": "facile", "color": "success"},
        {"name": "Plan Equilibre", "duration_months": dur_equilibre, "difficulty": "moyen", "color": "primary"},
        {"name": "Plan Intensif", "duration_months": dur_intensif, "difficulty": "intensif", "color": "danger"},
    ]

    result = {
        "analysis": analysis_text,
        "plans": plans,
    }

    # Generate completion curves
    plan_durations = {
        "prudent": dur_prudent,
        "equilibre": dur_equilibre,
        "intensif": dur_intensif,
    }
    chart_data = _simulate_trajectories(data.timeline_months, plan_durations)

    # Save to DB
    scenario_id = _gen_id()
    now = _now()
    description = analysis_text[:200] if analysis_text else data.hypothesis[:200]

    # probability_before = current prob, probability_after = estimated prob boost
    # from the balanced plan (Equilibre). This gives a meaningful delta for comparisons.
    prob_after_plan = min(99.9, round(current_prob + (100 - current_prob) * 0.6 * (data.timeline_months / max(dur_equilibre, 1)), 2))
    db.conn.execute(
        """INSERT INTO scenarios
           (id, auth_user_id, title, description, hypothesis, variables_json,
            result_json, probability_before, probability_after, timeline_months,
            chart_data_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            scenario_id, user_id or "", data.title, description, data.hypothesis,
            json.dumps(variables_list, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False),
            round(current_prob, 2), prob_after_plan, data.timeline_months,
            json.dumps(chart_data, ensure_ascii=False),
            now, now,
        ),
    )
    db.conn.commit()

    return ScenarioOut(
        id=scenario_id, title=data.title, description=description,
        hypothesis=data.hypothesis,
        variables_json=json.dumps(variables_list, ensure_ascii=False),
        result_json=json.dumps(result, ensure_ascii=False),
        probability_before=round(current_prob, 2),
        probability_after=round(current_prob, 2),
        timeline_months=data.timeline_months,
        chart_data_json=json.dumps(chart_data, ensure_ascii=False),
        created_at=now, updated_at=now,
    )


@router.get("/{scenario_id}", response_model=ScenarioOut)
async def get_scenario(
    scenario_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Get a scenario by ID."""
    _ensure_scenario_tables(db)
    if user_id:
        row = db.conn.execute(
            "SELECT * FROM scenarios WHERE id = ? AND auth_user_id = ?",
            (scenario_id, user_id),
        ).fetchone()
    else:
        row = db.conn.execute(
            "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Scenario non trouve")
    return ScenarioOut(
        id=row["id"], title=row["title"], description=row["description"],
        hypothesis=row["hypothesis"], variables_json=row["variables_json"],
        result_json=row["result_json"], probability_before=row["probability_before"],
        probability_after=row["probability_after"], timeline_months=row["timeline_months"],
        chart_data_json=row["chart_data_json"], created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.delete("/{scenario_id}")
async def delete_scenario(
    scenario_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Delete a scenario."""
    _ensure_scenario_tables(db)
    if user_id:
        db.conn.execute(
            "DELETE FROM scenarios WHERE id = ? AND auth_user_id = ?",
            (scenario_id, user_id),
        )
    else:
        db.conn.execute(
            "DELETE FROM scenarios WHERE id = ?", (scenario_id,)
        )
    db.conn.commit()
    return {"success": True, "message": "Scenario supprime"}


@router.post("/compare", response_model=ScenarioCompareOut)
async def compare_scenarios(
    data: ScenarioCompareIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Compare 2-5 scenarios side by side."""
    _ensure_scenario_tables(db)

    scenarios = []
    for sid in data.scenario_ids:
        if user_id:
            row = db.conn.execute(
                "SELECT * FROM scenarios WHERE id = ? AND auth_user_id = ?",
                (sid, user_id),
            ).fetchone()
        else:
            row = db.conn.execute(
                "SELECT * FROM scenarios WHERE id = ?", (sid,)
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Scenario {sid} non trouve")
        scenarios.append(
            ScenarioOut(
                id=row["id"], title=row["title"], description=row["description"],
                hypothesis=row["hypothesis"], variables_json=row["variables_json"],
                result_json=row["result_json"], probability_before=row["probability_before"],
                probability_after=row["probability_after"], timeline_months=row["timeline_months"],
                chart_data_json=row["chart_data_json"], created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )

    # Build comparison data — compare by fastest plan (intensif duration)
    best_idx = 0
    best_duration = 9999
    for i, s in enumerate(scenarios):
        try:
            res = json.loads(s.result_json)
            plans = res.get("plans", [])
            # Find the intensif plan duration
            for p in plans:
                if "Intensif" in p.get("name", ""):
                    dur = p.get("duration_months", 9999)
                    if dur < best_duration:
                        best_duration = dur
                        best_idx = i
        except (json.JSONDecodeError, TypeError):
            pass

    comparison = {
        "best_scenario": scenarios[best_idx].id,
        "best_scenario_title": scenarios[best_idx].title,
        "best_duration_months": round(best_duration, 0),
        "best_impact": round(scenarios[best_idx].probability_after - scenarios[best_idx].probability_before, 2),
        "summary": [
            {
                "id": s.id,
                "title": s.title,
                "probability_before": s.probability_before,
                "probability_after": s.probability_after,
                "impact": round(s.probability_after - s.probability_before, 2),
                "duration_intensif_months": next(
                    (p.get("duration_months", 0) for p in json.loads(s.result_json).get("plans", [])
                     if "Intensif" in p.get("name", "")),
                    s.timeline_months,
                ) if s.result_json else s.timeline_months,
                "timeline_months": s.timeline_months,
            }
            for s in scenarios
        ],
    }

    return ScenarioCompareOut(scenarios=scenarios, comparison=comparison)


@router.get("/{scenario_id}/export")
async def export_scenario(
    scenario_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Export a scenario as PDF with analysis and chart description."""
    _ensure_scenario_tables(db)
    if user_id:
        row = db.conn.execute(
            "SELECT * FROM scenarios WHERE id = ? AND auth_user_id = ?",
            (scenario_id, user_id),
        ).fetchone()
    else:
        row = db.conn.execute(
            "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Scenario non trouve")

    scenario_dict = dict(row)
    filepath = _export_scenario_pdf(scenario_dict)

    # ── Also copy PDF to user's workspace Hypotheses folder ──
    try:
        if user_id:
            obj_name = get_workspace_folder_name(db, user_id)
            workspace_dir = WORKSPACE_BASE / obj_name
            workspace_dir.mkdir(parents=True, exist_ok=True)
            hypotheses_dir = workspace_dir / "Hypotheses"
            hypotheses_dir.mkdir(parents=True, exist_ok=True)
            ws_dest = hypotheses_dir / filepath.name
            if not ws_dest.exists():
                shutil.copy2(str(filepath), str(ws_dest))
                logger.info("Scenario PDF copied to workspace/Hypotheses: %s", ws_dest)
    except Exception as e:
        logger.warning("Could not copy PDF to workspace: %s", e)

    return FileResponse(
        path=str(filepath),
        filename=filepath.name,
        media_type="application/pdf",
    )
