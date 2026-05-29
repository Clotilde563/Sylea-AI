"""
Tests E2E pour les endpoints /api/dilemme/tracking/* (mode tracking).

Couvre :
  - POST /create  : creation tracking (nb_periodes calcule)
  - GET  /        : listing
  - GET  /:id     : detail
  - POST /:id/respond : reponses periodes + transition awaiting_validation
  - GET  /:id/recap   : calcul recap pondere
  - POST /:id/validate: application impact final
  - POST /:id/cancel  : modes zero + partial

Pattern : meme fixture que tests/test_api_dilemme.py (SQLite shared, no agent).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_db, get_agent
from tests.conftest import make_shared_db, dispose_shared_db


# ── Helpers ──────────────────────────────────────────────────────────────────

_PROFIL_PAYLOAD = {
    "nom": "Tracking Tester",
    "age": 30,
    "profession": "Ingenieur",
    "ville": "Paris",
    "situation_familiale": "Celibataire",
    "revenu_annuel": 50000,
    "patrimoine_estime": 10000,
    "charges_mensuelles": 1500,
    "objectif": {
        "description": "Devenir CTO",
        "categorie": "carrière",
        "deadline": "2030-01-01",
        "probabilite_base": 25.0,
    },
}


def _create_tracking_payload(
    impact_jours: int = 365,
    options: list[dict] | None = None,
):
    """Construit un payload pour POST /create."""
    if options is None:
        options = [
            {
                "lettre": "A",
                "description": "Apprendre l'anglais 1h/jour",
                "impact_jours": 150.0,
                "pros": ["Carriere", "Voyages"],
                "cons": ["Temps requis"],
                "resume": "Bon pour la carriere.",
            },
            {
                "lettre": "B",
                "description": "Apprendre l'italien 1h/jour",
                "impact_jours": -80.0,
                "pros": ["Plaisir personnel"],
                "cons": ["Pas de retour direct sur l'objectif"],
                "resume": "Moins utile professionnellement.",
            },
        ]
    return {
        "question": "Faut-il apprendre l'anglais ou l'italien ?",
        "options": options,
        "impact_temporel_jours": impact_jours,
        "verdict": "L'anglais ouvre plus d'opportunites.",
        "etude_scientifique": "Etude X sur l'apprentissage des langues.",
        "device_tz": "Europe/Paris",
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = make_shared_db(tmp_path, monkeypatch)

    async def _override_get_db():
        yield db

    def _override_get_agent():
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_agent] = _override_get_agent

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    dispose_shared_db(db)


@pytest.fixture()
def client_with_profil(client: TestClient):
    resp = client.post("/api/profil", json=_PROFIL_PAYLOAD)
    assert resp.status_code == 200, f"Profil creation failed: {resp.text}"
    return client


# ── Tests : POST /create ─────────────────────────────────────────────────────

def test_create_tracking_returns_id_and_nb_periodes(client_with_profil: TestClient):
    """Cree un tracking d'1 an : nb_periodes doit etre 12 (mensuel)."""
    payload = _create_tracking_payload(impact_jours=365)
    resp = client_with_profil.post("/api/dilemme/tracking/create", json=payload)
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert data["ok"] is True
    t = data["tracking"]
    assert t["id"]
    assert t["status"] == "tracking"
    # 365j / 30 = 12.17 -> round = 12
    assert t["nb_periodes"] == 12
    assert t["impact_temporel_jours"] == 365
    assert t["next_notif_at"]  # ISO timestamp non vide
    assert len(t["choices"]) == 12
    assert all(c["choice"] is None for c in t["choices"])


def test_create_tracking_short_duration_single_period(client_with_profil: TestClient):
    """Duree <= 30j -> 1 seule periode (notif unique de fin)."""
    payload = _create_tracking_payload(impact_jours=7)
    resp = client_with_profil.post("/api/dilemme/tracking/create", json=payload)
    assert resp.status_code == 200
    t = resp.json()["tracking"]
    assert t["nb_periodes"] == 1
    assert len(t["choices"]) == 1


def test_create_tracking_45_days_two_periods(client_with_profil: TestClient):
    """Custom duration 45j -> round(45/30) = 2 periodes."""
    payload = _create_tracking_payload(impact_jours=45)
    resp = client_with_profil.post("/api/dilemme/tracking/create", json=payload)
    assert resp.status_code == 200
    t = resp.json()["tracking"]
    assert t["nb_periodes"] == 2


def test_create_tracking_requires_two_options(client_with_profil: TestClient):
    """Moins de 2 options -> 400."""
    payload = _create_tracking_payload(
        options=[{
            "lettre": "A", "description": "Seule option", "impact_jours": 10.0,
            "pros": [], "cons": [], "resume": "",
        }],
    )
    resp = client_with_profil.post("/api/dilemme/tracking/create", json=payload)
    assert resp.status_code == 400


def test_create_tracking_without_profil_returns_404(client: TestClient):
    """Sans profil -> 404."""
    resp = client.post("/api/dilemme/tracking/create", json=_create_tracking_payload())
    assert resp.status_code == 404


# ── Tests : GET / et /:id ────────────────────────────────────────────────────

def test_list_and_get_tracking(client_with_profil: TestClient):
    """Cree un tracking, le liste, et le re-fetch par id."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=30),
    )
    assert create_resp.status_code == 200
    tracking_id = create_resp.json()["tracking"]["id"]

    list_resp = client_with_profil.get("/api/dilemme/tracking")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == tracking_id

    get_resp = client_with_profil.get(f"/api/dilemme/tracking/{tracking_id}")
    assert get_resp.status_code == 200
    t = get_resp.json()["tracking"]
    assert t["id"] == tracking_id
    assert t["status"] == "tracking"


def test_list_filter_by_status(client_with_profil: TestClient):
    """Filtrer par status='tracking' renvoie le tracking."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=30),
    )
    assert create_resp.status_code == 200

    resp_tracking = client_with_profil.get("/api/dilemme/tracking?status=tracking")
    assert resp_tracking.status_code == 200
    assert len(resp_tracking.json()["items"]) == 1

    resp_validated = client_with_profil.get("/api/dilemme/tracking?status=validated")
    assert resp_validated.status_code == 200
    assert len(resp_validated.json()["items"]) == 0


def test_list_invalid_status_returns_400(client_with_profil: TestClient):
    resp = client_with_profil.get("/api/dilemme/tracking?status=bogus")
    assert resp.status_code == 400


def test_get_unknown_tracking_returns_404(client_with_profil: TestClient):
    resp = client_with_profil.get("/api/dilemme/tracking/does-not-exist")
    assert resp.status_code == 404


# ── Tests : POST /:id/respond ────────────────────────────────────────────────

def test_respond_single_period_transitions_to_awaiting(client_with_profil: TestClient):
    """Duree courte (1 periode) : repondre 1 fois -> awaiting_validation."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=7),
    )
    tracking_id = create_resp.json()["tracking"]["id"]

    resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},  # option A
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["all_responded"] is True
    assert data["nb_responded"] == 1
    assert data["nb_total"] == 1

    # Verifier que status est passe a awaiting_validation
    get_resp = client_with_profil.get(f"/api/dilemme/tracking/{tracking_id}")
    assert get_resp.json()["tracking"]["status"] == "awaiting_validation"


def test_respond_multiple_periods(client_with_profil: TestClient):
    """12 periodes : repondre 6×A 4×B 2×none -> awaiting_validation."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=365),
    )
    tracking_id = create_resp.json()["tracking"]["id"]

    pattern = ["0"] * 6 + ["1"] * 4 + ["none"] * 2  # 12 reponses
    for idx, choice in enumerate(pattern):
        resp = client_with_profil.post(
            f"/api/dilemme/tracking/{tracking_id}/respond",
            json={"periode_idx": idx, "choice": choice},
        )
        assert resp.status_code == 200
        is_last = (idx == 11)
        assert resp.json()["all_responded"] is is_last

    final = client_with_profil.get(f"/api/dilemme/tracking/{tracking_id}")
    assert final.json()["tracking"]["status"] == "awaiting_validation"


def test_respond_invalid_choice_returns_400(client_with_profil: TestClient):
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=7),
    )
    tracking_id = create_resp.json()["tracking"]["id"]
    resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "abc"},  # ni nombre ni 'none'
    )
    assert resp.status_code == 400


def test_respond_periode_out_of_range_returns_400(client_with_profil: TestClient):
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=7),
    )
    tracking_id = create_resp.json()["tracking"]["id"]
    resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 5, "choice": "0"},  # 5 hors range pour nb_periodes=1
    )
    assert resp.status_code == 400


# ── Tests : GET /:id/recap ───────────────────────────────────────────────────

def test_recap_weighted_breakdown(client_with_profil: TestClient):
    """Recap : 6×A (impact +150j) + 4×B (impact -80j) + 2×none sur 12 periodes.
    Anglais: 150 * 6/12 = 75. Italien: -80 * 4/12 = -26.67. None: 0. Total: 48.33."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=365),
    )
    tracking_id = create_resp.json()["tracking"]["id"]

    pattern = ["0"] * 6 + ["1"] * 4 + ["none"] * 2
    for idx, choice in enumerate(pattern):
        client_with_profil.post(
            f"/api/dilemme/tracking/{tracking_id}/respond",
            json={"periode_idx": idx, "choice": choice},
        )

    recap_resp = client_with_profil.get(f"/api/dilemme/tracking/{tracking_id}/recap")
    assert recap_resp.status_code == 200
    data = recap_resp.json()
    assert data["status"] == "awaiting_validation"
    recap = data["recap"]
    assert recap["nb_periodes"] == 12
    by_option = {b["option"]: b for b in recap["breakdown"]}
    assert by_option["0"]["nb_clicks"] == 6
    assert by_option["1"]["nb_clicks"] == 4
    assert by_option["none"]["nb_clicks"] == 2
    assert by_option["0"]["impact_pondere"] == pytest.approx(75.0, abs=0.05)
    assert by_option["1"]["impact_pondere"] == pytest.approx(-26.67, abs=0.05)
    assert by_option["none"]["impact_pondere"] == 0
    assert recap["impact_total_jours"] == pytest.approx(48.33, abs=0.05)


# ── Tests : POST /:id/validate ───────────────────────────────────────────────

def test_validate_applies_impact_and_marks_validated(client_with_profil: TestClient):
    """Validate apres reponses -> status='validated' + impact_final stocke."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=30),
    )
    tracking_id = create_resp.json()["tracking"]["id"]

    # Repondre option A (impact +150j attendu pondere = 150 * 1/1 = 150)
    client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )

    validate_resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/validate"
    )
    assert validate_resp.status_code == 200, validate_resp.text
    data = validate_resp.json()
    assert data["ok"] is True
    assert data["impact_jours_applique"] == pytest.approx(150.0, abs=0.05)
    # delta_probabilite : positif (impact_jours > 0)
    assert data["delta_probabilite"] >= 0

    # status passe a validated
    final = client_with_profil.get(f"/api/dilemme/tracking/{tracking_id}")
    assert final.json()["tracking"]["status"] == "validated"


def test_validate_twice_returns_409(client_with_profil: TestClient):
    """Valider 2x -> 409 (status_invalid)."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=7),
    )
    tracking_id = create_resp.json()["tracking"]["id"]
    client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )
    first = client_with_profil.post(f"/api/dilemme/tracking/{tracking_id}/validate")
    assert first.status_code == 200
    second = client_with_profil.post(f"/api/dilemme/tracking/{tracking_id}/validate")
    assert second.status_code == 409


# ── Tests : POST /:id/cancel ─────────────────────────────────────────────────

def test_cancel_zero_mode_no_impact(client_with_profil: TestClient):
    """Cancel mode=zero -> impact 0, status='cancelled'."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=30),
    )
    tracking_id = create_resp.json()["tracking"]["id"]

    cancel_resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/cancel",
        json={"mode": "zero"},
    )
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    assert data["ok"] is True
    assert data["impact_jours_applique"] == 0
    assert data["delta_probabilite"] == 0

    final = client_with_profil.get(f"/api/dilemme/tracking/{tracking_id}")
    assert final.json()["tracking"]["status"] == "cancelled"
    assert final.json()["tracking"]["cancellation_mode"] == "zero"


def test_cancel_partial_applies_impact(client_with_profil: TestClient):
    """Cancel mode=partial avec 1 reponse sur 12 = impact partiel applique."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=365),
    )
    tracking_id = create_resp.json()["tracking"]["id"]

    # 1 reponse sur 12 (option A, +150j theoriques)
    client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )

    cancel_resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/cancel",
        json={"mode": "partial"},
    )
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    # 150 * (1/12) = 12.5j
    assert data["impact_jours_applique"] == pytest.approx(12.5, abs=0.05)

    final = client_with_profil.get(f"/api/dilemme/tracking/{tracking_id}")
    assert final.json()["tracking"]["status"] == "cancelled"
    assert final.json()["tracking"]["cancellation_mode"] == "partial"


def test_cancel_invalid_mode_returns_400(client_with_profil: TestClient):
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=7),
    )
    tracking_id = create_resp.json()["tracking"]["id"]
    resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/cancel",
        json={"mode": "bogus"},
    )
    assert resp.status_code == 400


def test_cancel_already_validated_returns_409(client_with_profil: TestClient):
    """Cancel sur tracking deja 'validated' -> 409."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=7),
    )
    tracking_id = create_resp.json()["tracking"]["id"]
    client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )
    client_with_profil.post(f"/api/dilemme/tracking/{tracking_id}/validate")
    resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/cancel",
        json={"mode": "zero"},
    )
    assert resp.status_code == 409


# ── Tests : validation temporelle (anti-bypass) ──────────────────────────────

def test_respond_periode_not_yet_due_returns_425(client_with_profil: TestClient, monkeypatch):
    """Sans SYLEA_TRACKING_BYPASS_TIME, l'API doit refuser de repondre a une
    periode avant son echeance (425 Too Early). Garantit qu'on ne peut pas
    'completer' un engagement de 90j en quelques secondes via DevTools."""
    # On retire le bypass temporel pour ce test specifique
    monkeypatch.delenv("SYLEA_TRACKING_BYPASS_TIME", raising=False)

    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=90),  # 3 periodes mensuelles
    )
    assert create_resp.status_code == 200
    tracking_id = create_resp.json()["tracking"]["id"]

    # La periode 0 est due a J+30 (au plus tot). On tente immediatement.
    resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )
    assert resp.status_code == 425, (
        f"Expected 425 Too Early, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    detail = body["detail"]
    assert detail["error"] == "periode_not_yet_due"
    assert detail["periode_idx"] == 0
    assert "expected_notif_at" in detail


def test_respond_with_bypass_env_var_succeeds(client_with_profil: TestClient, monkeypatch):
    """Avec SYLEA_TRACKING_BYPASS_TIME=true, le check temporel est skip
    (utile pour les tests E2E). Le conftest.py active deja ce flag, on le
    re-confirme explicitement ici."""
    monkeypatch.setenv("SYLEA_TRACKING_BYPASS_TIME", "true")

    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=90),
    )
    tracking_id = create_resp.json()["tracking"]["id"]

    resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


# ── Tests : DELETE /:id (suppression definitive) ────────────────────────────

def test_delete_tracking_removes_from_db(client_with_profil: TestClient):
    """DELETE retire completement le tracking de la DB (pas de trace)."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=30),
    )
    assert create_resp.status_code == 200
    tracking_id = create_resp.json()["tracking"]["id"]

    # Verifier qu'il est listable avant
    listing = client_with_profil.get("/api/dilemme/tracking")
    assert any(t["id"] == tracking_id for t in listing.json()["items"])

    # Delete
    del_resp = client_with_profil.delete(f"/api/dilemme/tracking/{tracking_id}")
    assert del_resp.status_code == 200, del_resp.text
    assert del_resp.json()["ok"] is True
    assert del_resp.json()["deleted"] is True

    # Verifier qu'il n'est plus listable
    listing2 = client_with_profil.get("/api/dilemme/tracking")
    assert not any(t["id"] == tracking_id for t in listing2.json()["items"])


def test_delete_unknown_tracking_returns_404(client_with_profil: TestClient):
    resp = client_with_profil.delete("/api/dilemme/tracking/does-not-exist")
    assert resp.status_code == 404


def test_delete_does_not_apply_impact_on_profil(client_with_profil: TestClient):
    """DELETE ne touche jamais au profil ni aux sous-objectifs."""
    # Snapshot profil avant
    profil_before = client_with_profil.get("/api/profil").json()
    prob_before = profil_before["probabilite_actuelle"]
    tg_before = profil_before["temps_gagne_jours"]

    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=30),
    )
    tracking_id = create_resp.json()["tracking"]["id"]

    # Repondre a la periode (= aurait impact si on validait)
    client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )

    # Delete sans valider
    del_resp = client_with_profil.delete(f"/api/dilemme/tracking/{tracking_id}")
    assert del_resp.status_code == 200

    # Profil inchange
    profil_after = client_with_profil.get("/api/profil").json()
    assert profil_after["probabilite_actuelle"] == prob_before
    assert profil_after["temps_gagne_jours"] == tg_before


def test_delete_validated_tracking_also_removes(client_with_profil: TestClient):
    """On peut delete meme un tracking deja valide (= retire de l'historique).
    L'impact deja applique au profil NE sera PAS reverse par delete."""
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=7),
    )
    tracking_id = create_resp.json()["tracking"]["id"]
    client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )
    client_with_profil.post(f"/api/dilemme/tracking/{tracking_id}/validate")

    # Delete apres validate
    del_resp = client_with_profil.delete(f"/api/dilemme/tracking/{tracking_id}")
    assert del_resp.status_code == 200

    # Plus dans la liste
    listing = client_with_profil.get("/api/dilemme/tracking")
    assert not any(t["id"] == tracking_id for t in listing.json()["items"])


def test_delete_cancelled_partial_keeps_impact(client_with_profil: TestClient):
    """Si on cancel('partial') puis on delete : l'impact partiel est deja
    applique au profil, le delete ne le reverse pas (= verifie la separation
    delete vs cancel)."""
    profil_before = client_with_profil.get("/api/profil").json()
    create_resp = client_with_profil.post(
        "/api/dilemme/tracking/create",
        json=_create_tracking_payload(impact_jours=90),  # 3 periodes
    )
    tracking_id = create_resp.json()["tracking"]["id"]
    # Repondre periode 0 (option A, +150j * 1/3 = +50j attendu si partial)
    client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/respond",
        json={"periode_idx": 0, "choice": "0"},
    )
    # Cancel partial : impact applique
    cancel_resp = client_with_profil.post(
        f"/api/dilemme/tracking/{tracking_id}/cancel",
        json={"mode": "partial"},
    )
    assert cancel_resp.status_code == 200
    profil_after_cancel = client_with_profil.get("/api/profil").json()
    # Delete : ne reverse pas l'impact deja applique
    del_resp = client_with_profil.delete(f"/api/dilemme/tracking/{tracking_id}")
    assert del_resp.status_code == 200
    profil_after_delete = client_with_profil.get("/api/profil").json()
    # L'impact applique pendant cancel reste applique
    assert profil_after_delete["temps_gagne_jours"] == profil_after_cancel["temps_gagne_jours"]
