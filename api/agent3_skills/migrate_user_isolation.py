"""
Migration ClawHub skills -> isolation per-user (Phase 4.2).

Avant : tous les skills auto-installes atterrissent dans `~/.openclaw/skills/`,
partages entre tous les users de l'instance Sylea.

Apres : chaque user a son propre dossier
`~/.sylea/users/{auth_user_id}/.openclaw/skills/`, isole des autres.

Cette migration copie (pas move) les skills legacy vers le dossier d'un user
cible. Non-destructive par defaut : le legacy path est conserve pour permettre
un rollback.

Usage :

    # Dry-run : liste ce qui serait copie
    python -m api.agent3_skills.migrate_user_isolation --user-id alice-123

    # Applique la copie
    python -m api.agent3_skills.migrate_user_isolation --user-id alice-123 --apply

    # Copie un sous-ensemble de slugs
    python -m api.agent3_skills.migrate_user_isolation --user-id alice-123 \
        --apply --slugs weather,postgres-backup

    # Copie + supprime du legacy (DESTRUCTIF, demande confirmation)
    python -m api.agent3_skills.migrate_user_isolation --user-id alice-123 \
        --apply --cleanup-legacy

    # Aide
    python -m api.agent3_skills.migrate_user_isolation --help
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional


def _import_loader():
    """Import en dernier recours pour eviter une dependence circulaire en test."""
    from api.agent3_skills.clawhub_loader import (
        LEGACY_USER_SKILLS_DIR,
        get_user_skills_dir,
        ensure_user_skills_dir,
    )
    return LEGACY_USER_SKILLS_DIR, get_user_skills_dir, ensure_user_skills_dir


def _list_legacy_slugs(legacy_dir: Path) -> list[str]:
    """Liste les slugs presents dans le legacy dir (chaque sous-dossier avec SKILL.md)."""
    if not legacy_dir.exists() or not legacy_dir.is_dir():
        return []
    slugs = []
    for entry in sorted(legacy_dir.iterdir()):
        if entry.is_dir() and (entry / "SKILL.md").exists():
            slugs.append(entry.name)
    return slugs


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy tree. Si dst existe, on le laisse et on merge (dirs_exist_ok=True)."""
    shutil.copytree(src, dst, dirs_exist_ok=True)


def migrate(
    auth_user_id: str,
    *,
    apply: bool = False,
    slugs_filter: Optional[list[str]] = None,
    cleanup_legacy: bool = False,
    confirm_cleanup: bool = False,
    verbose: bool = True,
) -> dict:
    """Copie les skills du legacy dir vers le dossier du user.

    Args:
        auth_user_id: identifiant du user cible.
        apply: si False (defaut), dry-run seulement.
        slugs_filter: liste de slugs a migrer (None = tous).
        cleanup_legacy: si True + apply, supprime le legacy apres copie reussie.
        confirm_cleanup: doit etre True pour autoriser cleanup_legacy (safety).
        verbose: imprime un recap.

    Returns:
        {"planned": [...], "copied": [...], "skipped": [...], "removed_legacy": bool}
    """
    LEGACY_USER_SKILLS_DIR, get_user_skills_dir, ensure_user_skills_dir = _import_loader()

    if not auth_user_id or not auth_user_id.strip():
        raise ValueError("auth_user_id est requis")

    target_dir = get_user_skills_dir(auth_user_id)
    legacy_dir = LEGACY_USER_SKILLS_DIR

    if verbose:
        print(f"[migrate] Legacy : {legacy_dir}")
        print(f"[migrate] Target : {target_dir}")
        print(f"[migrate] User   : {auth_user_id}")

    if not legacy_dir.exists():
        if verbose:
            print(f"[migrate] Legacy dir absent — rien a faire.")
        return {
            "planned": [],
            "copied": [],
            "skipped": [],
            "removed_legacy": False,
            "legacy_missing": True,
        }

    all_slugs = _list_legacy_slugs(legacy_dir)
    if slugs_filter:
        slugs_filter_set = {s.strip() for s in slugs_filter if s.strip()}
        slugs = [s for s in all_slugs if s in slugs_filter_set]
        unknown = slugs_filter_set - set(all_slugs)
        if unknown and verbose:
            print(f"[migrate] Slugs inconnus (ignores): {sorted(unknown)}")
    else:
        slugs = all_slugs

    if not slugs:
        if verbose:
            print(f"[migrate] Aucun slug a migrer.")
        return {
            "planned": [],
            "copied": [],
            "skipped": [],
            "removed_legacy": False,
        }

    if apply:
        ensure_user_skills_dir(auth_user_id)

    copied: list[str] = []
    skipped: list[str] = []

    for slug in slugs:
        src = legacy_dir / slug
        dst = target_dir / slug
        if dst.exists() and (dst / "SKILL.md").exists():
            if verbose:
                print(f"  [skip] {slug}  (deja present dans {dst})")
            skipped.append(slug)
            continue

        if verbose:
            action = "copy" if apply else "would copy"
            print(f"  [{action}] {slug}  ->  {dst}")

        if apply:
            try:
                _copy_tree(src, dst)
                copied.append(slug)
            except Exception as e:
                print(f"  [error] copie de {slug} echouee: {e}", file=sys.stderr)

    removed_legacy = False
    if cleanup_legacy and apply:
        if not confirm_cleanup:
            print(
                "\n[migrate] --cleanup-legacy demande mais --confirm-cleanup "
                "absent. Les fichiers legacy ne sont PAS supprimes.",
                file=sys.stderr,
            )
        elif not copied and not skipped:
            print(
                "\n[migrate] Aucun skill migre, pas de cleanup pour eviter la "
                "perte de donnees.",
                file=sys.stderr,
            )
        else:
            try:
                for slug in slugs:
                    src = legacy_dir / slug
                    if src.exists():
                        shutil.rmtree(src, ignore_errors=False)
                removed_legacy = True
                if verbose:
                    print(f"\n[migrate] Legacy slugs supprimes de {legacy_dir}")
            except Exception as e:
                print(f"[migrate] Cleanup echoue: {e}", file=sys.stderr)

    if verbose:
        mode = "APPLY" if apply else "DRY-RUN"
        print(f"\n[migrate] {mode} : {len(copied)} copie(s), {len(skipped)} deja present(s), {len(slugs)} planifie(s)")

    return {
        "planned": slugs,
        "copied": copied,
        "skipped": skipped,
        "removed_legacy": removed_legacy,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate_user_isolation",
        description="Migre ~/.openclaw/skills/ vers ~/.sylea/users/{user}/.openclaw/skills/",
    )
    p.add_argument(
        "--user-id",
        required=True,
        help="auth_user_id cible. Les skills legacy seront copies dans le dossier de ce user.",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Execute la copie. Sinon dry-run (affichage seulement).",
    )
    p.add_argument(
        "--slugs",
        help="Liste de slugs separes par virgules (ex: 'weather,postgres-backup'). Defaut : tous.",
    )
    p.add_argument(
        "--cleanup-legacy",
        action="store_true",
        help="Supprime les slugs du legacy dir apres copie reussie. Necessite --confirm-cleanup.",
    )
    p.add_argument(
        "--confirm-cleanup",
        action="store_true",
        help="Confirme la suppression du legacy (requis avec --cleanup-legacy).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Supprime la sortie verbose.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    slugs_filter: Optional[list[str]] = None
    if args.slugs:
        slugs_filter = [s for s in args.slugs.split(",") if s.strip()]

    try:
        result = migrate(
            auth_user_id=args.user_id,
            apply=args.apply,
            slugs_filter=slugs_filter,
            cleanup_legacy=args.cleanup_legacy,
            confirm_cleanup=args.confirm_cleanup,
            verbose=not args.quiet,
        )
    except Exception as e:
        print(f"[migrate] Echec: {e}", file=sys.stderr)
        return 2

    if args.apply and result.get("copied"):
        return 0
    if not args.apply:
        return 0  # dry-run toujours OK
    if result.get("skipped") and not result.get("copied"):
        return 0  # tout deja migre, OK
    return 0


if __name__ == "__main__":
    sys.exit(main())
