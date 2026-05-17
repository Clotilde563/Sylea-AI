"""
Helper invariant-preserving pour la mise a jour des progressions sous-objectifs.

Sprint QA pre-commercialisation :
======================================================================

INVARIANT DASHBOARD (critique pour la coherence UI) :

    sum_i (te_prop_i * (1 - prog_i / 100))  ==  objectif_restant
                                            ==  temps_initial - temps_gagne

ou te_prop_i = (te_i / sum(te)) * temps_initial.

Cet invariant DOIT etre preserve apres chaque mutation (creation
decision, evenement, suppression). Avant ce module :
  - dilemme.py    : capait new_prog a 100 sans redistribuer => drift
  - evenement.py  : redistribuait l'overflow en POINTS DE % uniformes
                    alors que les SOs ont des te differents => drift
                    (ex: overflow 5% sur SO te=200 + SO te=300 ajoute
                     5j+7.5j=12.5j au lieu des 5j attendus)

Ce module fournit `apply_impact_invariant_safe_async()` (async, PG-compatible) qui :
  1. Appliquent l'impact sur le SO cible (identifie par l'IA).
  2. Si overflow, capent a 100 et redistribuent le SURPLUS EN JOURS sur
     les autres SOs non-satures, en preservant l'invariant
     (delta_pct uniforme = surplus_jours / sum_remaining_te_prop * 100).
  3. Cascadent si certaines redistributions saturent a leur tour.

Migration PG (2026-05-12) : la version async utilise SQLAlchemy text() et
attend que le caller gere la transaction (session.commit/rollback). Les
versions sync ont ete supprimees apres migration complete (2026-05-13).

Le DELETE flow appelle `_recompute_so_progressions` (historique.py)
qui re-derive les progressions a partir de temps_gagne, garantissant
que l'invariant est maintenu meme apres suppression.
"""

from __future__ import annotations

from typing import Set


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-12)
# ═══════════════════════════════════════════════════════════════════════════

async def apply_impact_invariant_safe_async(
    session,
    profil_id: str,
    target_so_id: str | None,
    impact_jours: float,
    temps_initial: float,
) -> tuple[str | None, float]:
    """Applique impact_jours au sous-objectif cible avec cascade preservant
    l'invariant Dashboard (version async, PG-compatible).

    Args:
        session: AsyncSession SQLAlchemy.
        profil_id: id du profil utilisateur.
        target_so_id: id du SO identifie par l'IA comme principal impact.
                       Si None ou inexistant, premier SO non-sature pris.
        impact_jours: impact signe en jours (+ pour gain, - pour perte).
        temps_initial: profil.temps_initial_jours (pour le calcul de te_prop).

    Returns:
        (target_so_id_used, applied_delta_pct):
          - target_so_id_used : id du SO sur lequel le delta principal a ete
            applique (peut differer du parametre si fallback).
          - applied_delta_pct : delta % effectivement applique au SO cible
            (a stocker dans decision.impact_sous_objectif). Sera < intent si
            cap a 100 (ou > 0).

    Edge cases couverts :
      - temps_initial <= 0      → no-op, retourne (target, 0.0)
      - impact_jours = 0        → no-op
      - |impact_jours| > temps_initial → cap a temps_initial (signe preserve)
      - aucun SO trouve         → no-op
      - tous SOs au cap dans la direction de l'impact → no-op
      - target_so_id orphelin   → fallback au premier non-sature

    La transaction est implicite (geree par la session SQLAlchemy) — le
    caller doit appeler session.commit() ou session.rollback() apres.

    Concurrence (PG) : pour eviter la corruption, encadrer l'appel d'un
    SELECT ... FOR UPDATE sur les rows sous_objectifs du profil. Pour
    SQLite, la serialization est automatique via le verrou de fichier.
    """
    from sqlalchemy import text

    # Edge case : impact nul → no-op
    if not impact_jours or abs(impact_jours) < 0.001:
        return target_so_id, 0.0

    # Edge case : impact superieur a la capacite totale → cap (signe preserve)
    if temps_initial > 0 and abs(impact_jours) > temps_initial:
        impact_jours = float(temps_initial if impact_jours > 0 else -temps_initial)

    result = await session.execute(
        text(
            "SELECT id, progression, temps_estime FROM sous_objectifs "
            "WHERE user_id = :uid ORDER BY ordre"
        ),
        {"uid": profil_id},
    )
    rows = result.mappings().all()
    if not rows or temps_initial <= 0:
        return target_so_id, 0.0

    so_te: dict[str, float] = {r["id"]: float(max(30, r["temps_estime"] or 180)) for r in rows}
    so_prog: dict[str, float] = {r["id"]: float(r["progression"] or 0.0) for r in rows}
    sum_te = sum(so_te.values())
    if sum_te <= 0:
        return target_so_id, 0.0

    # te_prop = te / sum_te * temps_initial. Somme(te_prop) == temps_initial.
    te_prop: dict[str, float] = {sid: so_te[sid] / sum_te * temps_initial for sid in so_te}

    # Resoudre target : si non fourni / orphelin / sature, fallback au
    # premier non-sature dans la direction de l'impact.
    target_is_orphan = target_so_id is None or target_so_id not in so_te
    target_is_saturated = (
        not target_is_orphan and (
            (impact_jours >= 0 and so_prog[target_so_id] >= 100.0)
            or (impact_jours < 0 and so_prog[target_so_id] <= 0.0)
        )
    )
    if target_is_orphan or target_is_saturated:
        if impact_jours >= 0:
            candidates = [sid for sid in so_te if so_prog[sid] < 100]
        else:
            candidates = [sid for sid in so_te if so_prog[sid] > 0]
        if not candidates:
            return target_so_id, 0.0
        target_so_id = candidates[0]

    target_te_prop = te_prop[target_so_id]
    target_prog_before = so_prog[target_so_id]

    # Intent : appliquer impact_jours integralement sur le SO cible.
    if target_te_prop > 0:
        intent_delta_pct = (impact_jours / target_te_prop) * 100
    else:
        intent_delta_pct = 0.0
    new_prog_target = target_prog_before + intent_delta_pct

    # Cas 1 : pas d'overflow, applique tel quel.
    if 0.0 <= new_prog_target <= 100.0:
        await session.execute(
            text("UPDATE sous_objectifs SET progression = :p WHERE id = :sid"),
            {"p": new_prog_target, "sid": target_so_id},
        )
        return target_so_id, intent_delta_pct

    # Cas 2 : overflow positif (cap a 100).
    if new_prog_target > 100.0:
        applied_target_delta = 100.0 - target_prog_before  # >= 0
        target_gain_jours = applied_target_delta / 100.0 * target_te_prop
        overflow_jours = impact_jours - target_gain_jours  # > 0
        so_prog[target_so_id] = 100.0
        await session.execute(
            text("UPDATE sous_objectifs SET progression = 100 WHERE id = :sid"),
            {"sid": target_so_id},
        )
        await _cascade_overflow_async(
            session, te_prop, so_prog, overflow_jours, exclude={target_so_id}
        )
        return target_so_id, applied_target_delta

    # Cas 3 : overflow negatif (cap a 0).
    applied_target_delta = 0.0 - target_prog_before  # <= 0
    target_loss_jours = applied_target_delta / 100.0 * target_te_prop  # negatif ou 0
    overflow_jours = impact_jours - target_loss_jours  # negatif (le surplus de perte)
    so_prog[target_so_id] = 0.0
    await session.execute(
        text("UPDATE sous_objectifs SET progression = 0 WHERE id = :sid"),
        {"sid": target_so_id},
    )
    await _cascade_overflow_async(
        session, te_prop, so_prog, overflow_jours, exclude={target_so_id}
    )
    return target_so_id, applied_target_delta


async def _cascade_overflow_async(
    session,
    te_prop: dict[str, float],
    so_prog: dict[str, float],
    overflow_jours: float,
    exclude: Set[str],
) -> None:
    """Redistribue overflow_jours sur les SOs non-exclus, non-satures, en
    preservant l'invariant (version async, PG-compatible).

    Pour conserver l'invariant : delta_pct = overflow_jours / sum(te_prop_eligibles) * 100.
    Ce delta_pct, applique a chaque SO eligible, augmente la somme
    sum(te_prop_i * prog_i / 100) de overflow_jours exactement.

    Si certains SOs saturent durant la redistribution, leur surplus
    propre est cascade vers les SOs encore eligibles (boucle).

    Note : le commit est gere par le caller.
    """
    from sqlalchemy import text

    exclude = set(exclude)
    safety_iter = 0
    MAX_ITER = 64
    while abs(overflow_jours) > 0.01 and safety_iter < MAX_ITER:
        safety_iter += 1
        if overflow_jours > 0:
            candidates = [sid for sid in te_prop if sid not in exclude and so_prog[sid] < 100.0]
        else:
            candidates = [sid for sid in te_prop if sid not in exclude and so_prog[sid] > 0.0]
        if not candidates:
            break
        sum_remaining_te_prop = sum(te_prop[sid] for sid in candidates)
        if sum_remaining_te_prop <= 0:
            break

        delta_pct = overflow_jours / sum_remaining_te_prop * 100.0
        new_overflow = 0.0
        new_excludes: list[str] = []

        for sid in candidates:
            new_p = so_prog[sid] + delta_pct
            if new_p > 100.0:
                cap_gain_pct = 100.0 - so_prog[sid]
                cap_gain_jours = cap_gain_pct / 100.0 * te_prop[sid]
                applied_gain_jours = delta_pct / 100.0 * te_prop[sid]
                residual = applied_gain_jours - cap_gain_jours
                new_overflow += residual
                so_prog[sid] = 100.0
                await session.execute(
                    text("UPDATE sous_objectifs SET progression = 100 WHERE id = :sid"),
                    {"sid": sid},
                )
                new_excludes.append(sid)
            elif new_p < 0.0:
                cap_loss_pct = 0.0 - so_prog[sid]
                cap_loss_jours = cap_loss_pct / 100.0 * te_prop[sid]
                applied_loss_jours = delta_pct / 100.0 * te_prop[sid]
                residual = applied_loss_jours - cap_loss_jours
                new_overflow += residual
                so_prog[sid] = 0.0
                await session.execute(
                    text("UPDATE sous_objectifs SET progression = 0 WHERE id = :sid"),
                    {"sid": sid},
                )
                new_excludes.append(sid)
            else:
                so_prog[sid] = new_p
                await session.execute(
                    text("UPDATE sous_objectifs SET progression = :p WHERE id = :sid"),
                    {"p": new_p, "sid": sid},
                )

        overflow_jours = new_overflow
        for sid in new_excludes:
            exclude.add(sid)


async def verify_invariant_async(
    session, profil_id: str, temps_initial: float, temps_gagne: float,
    tol: float = 1.0,
) -> tuple[bool, float]:
    """Verifie l'invariant Dashboard pour le profil (version async, PG-compatible).

    Retourne (ok, ecart_jours):
      - ok = True si abs(sum_so_restant - objectif_restant) <= tol jours
      - ecart_jours = sum_so_restant - objectif_restant (signe : positif = trop de restant SO)
    """
    from sqlalchemy import text

    result = await session.execute(
        text("SELECT progression, temps_estime FROM sous_objectifs WHERE user_id = :uid"),
        {"uid": profil_id},
    )
    rows = result.mappings().all()
    if not rows or temps_initial <= 0:
        return True, 0.0

    so_te = [float(max(30, r["temps_estime"] or 180)) for r in rows]
    so_prog = [float(r["progression"] or 0.0) for r in rows]
    sum_te = sum(so_te)
    if sum_te <= 0:
        return True, 0.0

    sum_so_restant = sum(
        (te / sum_te * temps_initial) * (1.0 - prog / 100.0)
        for te, prog in zip(so_te, so_prog)
    )
    objectif_restant = temps_initial - temps_gagne
    ecart = sum_so_restant - objectif_restant
    return (abs(ecart) <= tol), ecart
