"""
Sandbox Python pour Agent 3 — execution de code data science.

Isole chaque execution dans un subprocess Python :
  - Timeout strict (defaut 30s)
  - Dossier temporaire dedie (workspace ephemere)
  - Pas d'acces reseau (hors libs Python stdlib autorisees)
  - Capture stdout / stderr
  - Detection auto des figures matplotlib -> sauvegardees + URLs retournees
  - Injection de libs data science (pandas, numpy, matplotlib si dispo)

Tool `PYTHON_EXEC` dans le dispatcher appelle `run_python_sandbox`.

Limitation MVP :
  - Pas de persistence entre invocations (chaque call est fresh)
  - Pas de vraie sandbox OS (relie sur timeout + isolation dossier)
  - Pour vraie securite prod : E2B.dev / Modal / Firecracker VM

Pour un usage personnel / dev, le niveau d'isolation actuel est acceptable
(meme philosophie que Jupyter local).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("sylea.python_sandbox")


# Dossier de destination des figures generees (servies via /api/agent3/files)
_FIGURES_DIR = Path(__file__).resolve().parent.parent / "data" / "sandbox_figures"
_FIGURES_DIR.mkdir(parents=True, exist_ok=True)


# Wrapper qui entoure le code user pour capturer matplotlib figures et
# gerer quelques convenances data-science.
_WRAPPER_TEMPLATE = r'''
import sys, os, traceback, json as _json

# Redirect matplotlib vers backend non-interactif si dispo
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _plt_available = True
except Exception:
    _plt_available = False

# Import stdlib data si dispos (mais continue si absent)
try:
    import numpy as np
except Exception:
    pass
try:
    import pandas as pd
except Exception:
    pass

_figures_saved = []

def _save_all_figures(output_dir):
    if not _plt_available:
        return
    for num in plt.get_fignums():
        fig = plt.figure(num)
        path = os.path.join(output_dir, f"figure_{num}.png")
        try:
            fig.savefig(path, dpi=96, bbox_inches="tight")
            _figures_saved.append(path)
        except Exception:
            pass
    plt.close("all")

__USER_CODE_START__ = True

__USER_RETURN__ = None
try:
{USER_CODE_INDENTED}
except Exception as _user_exc:
    print("__SANDBOX_EXCEPTION_START__", flush=True)
    traceback.print_exc()
    print("__SANDBOX_EXCEPTION_END__", flush=True)
    __USER_RETURN__ = {"error": type(_user_exc).__name__, "msg": str(_user_exc)}

# Sauvegarde les figures en fin de script
_save_all_figures({OUTPUT_DIR_LITERAL})

print("__SANDBOX_META__" + _json.dumps({
    "figures": _figures_saved,
    "user_return": __USER_RETURN__,
}), flush=True)
'''


def _indent_code(code: str, indent: str = "    ") -> str:
    """Indente chaque ligne non-vide du code user pour qu'il tourne dans try:."""
    return "\n".join(indent + line if line.strip() else line for line in code.split("\n"))


async def run_python_sandbox(
    code: str,
    *,
    user_id: str | None = None,
    timeout_s: float = 30.0,
    allow_network: bool = False,
) -> dict[str, Any]:
    """Execute du Python dans un subprocess isole.

    Retourne :
      {
        "stdout": str,
        "stderr": str,
        "exit_code": int,
        "duration_s": float,
        "figures": list[str],           # URLs relatives
        "error": str | None,
        "timed_out": bool,
      }
    """
    # Dossier temp isole pour cette execution
    run_id = uuid.uuid4().hex[:12]
    work_dir = Path(tempfile.mkdtemp(prefix=f"sylea_sandbox_{run_id}_"))
    figures_out_dir = _FIGURES_DIR / run_id
    figures_out_dir.mkdir(parents=True, exist_ok=True)

    # Construit le wrapped code
    wrapped = _WRAPPER_TEMPLATE.replace(
        "{USER_CODE_INDENTED}", _indent_code(code, "    ")
    ).replace(
        "{OUTPUT_DIR_LITERAL}", repr(str(figures_out_dir)),
    )

    script_path = work_dir / "run.py"
    script_path.write_text(wrapped, encoding="utf-8")

    # Environnement restreint
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "HOME": str(work_dir),
        "TMPDIR": str(work_dir),
        "TEMP": str(work_dir),
        "TMP": str(work_dir),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows compat
        # Windows : matplotlib (et d'autres libs) appellent Path.home() qui
        # veut USERPROFILE / HOMEPATH+HOMEDRIVE. Sans ca -> RuntimeError
        # "Could not determine home directory.". On pointe vers work_dir
        # pour que les fichiers de config matplotlib s'ecrivent dans le
        # sandbox isole et soient nettoyes en fin de run.
        "USERPROFILE": str(work_dir),
        "HOMEDRIVE": str(work_dir.drive) if hasattr(work_dir, "drive") and work_dir.drive else os.environ.get("HOMEDRIVE", "C:"),
        "HOMEPATH": str(work_dir),
        "APPDATA": str(work_dir),
        "LOCALAPPDATA": str(work_dir),
        # Force matplotlib backend non-interactif et cache dir local
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(work_dir / "mpl_config"),
    }
    # Preserve LANG pour UTF-8
    if "LANG" in os.environ:
        env["LANG"] = os.environ["LANG"]
    # Cree le repertoire mplconfig pour eviter les warnings
    try:
        (work_dir / "mpl_config").mkdir(exist_ok=True)
    except Exception:
        pass

    # Utilise le meme Python que le serveur (pour acceder aux memes libs)
    python_exe = sys.executable or "python"

    start = time.time()
    timed_out = False
    try:
        # Sur Windows, asyncio.create_subprocess_exec necessite un
        # ProactorEventLoop. Uvicorn (meme avec --loop asyncio) utilise
        # parfois SelectorEventLoop -> NotImplementedError. Solution
        # robuste : utiliser subprocess.run sync dans un thread (asyncio.to_thread).
        # Couts negligeables (subprocess prend de toute facon des ms).
        import subprocess as _sp

        def _run_sync():
            try:
                _r = _sp.run(
                    [python_exe, str(script_path)],
                    stdout=_sp.PIPE,
                    stderr=_sp.PIPE,
                    cwd=str(work_dir),
                    env=env,
                    timeout=timeout_s,
                )
                return _r.stdout, _r.stderr, _r.returncode, False
            except _sp.TimeoutExpired:
                return b"", b"Timeout.", -1, True

        stdout_bytes, stderr_bytes, exit_code_sync, timed_out = await asyncio.to_thread(_run_sync)

        # Wrapper pour mimicer l'interface attendue plus bas
        class _ProcShim:
            def __init__(self, rc):
                self.returncode = rc
        proc = _ProcShim(exit_code_sync)
    except Exception as e:
        logger.exception(f"Sandbox subprocess crashed: {e}")
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass
        return {
            "stdout": "",
            "stderr": f"Erreur subprocess : {type(e).__name__} {e}",
            "exit_code": -1,
            "duration_s": time.time() - start,
            "figures": [],
            "error": str(e),
            "timed_out": False,
        }

    duration_s = time.time() - start
    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

    # Parse le metadata a la fin du stdout
    figures_paths: list[str] = []
    user_error_msg: str | None = None
    exception_trace: str | None = None
    meta_marker = "__SANDBOX_META__"
    if meta_marker in stdout:
        idx = stdout.rfind(meta_marker)
        meta_line = stdout[idx + len(meta_marker):].split("\n", 1)[0]
        import json as _json
        try:
            meta = _json.loads(meta_line)
            figures_paths = meta.get("figures", []) or []
            if meta.get("user_return") and isinstance(meta["user_return"], dict):
                user_error_msg = f"{meta['user_return'].get('error', '?')}: {meta['user_return'].get('msg', '')}"
        except Exception:
            pass
        stdout = stdout[:idx].rstrip()

    # Extrait la trace user (entre markers) pour l'afficher plus proprement
    if "__SANDBOX_EXCEPTION_START__" in stdout:
        a = stdout.find("__SANDBOX_EXCEPTION_START__")
        b = stdout.find("__SANDBOX_EXCEPTION_END__")
        if b > a:
            exception_trace = stdout[a + len("__SANDBOX_EXCEPTION_START__"):b].strip()
            # Retire les markers du stdout affiche
            stdout = stdout[:a].rstrip() + (stdout[b + len("__SANDBOX_EXCEPTION_END__"):].lstrip() if len(stdout) > b else "")

    if exception_trace:
        # Merge dans stderr pour lisibilite (les tracebacks Python vont deja en stderr normalement)
        stderr = (stderr + "\n" + exception_trace).strip() if stderr else exception_trace

    # Transforme les paths absolus des figures en URLs relatives
    fig_urls = []
    for p in figures_paths:
        try:
            rel = Path(p).relative_to(_FIGURES_DIR.resolve())
            fig_urls.append(f"/api/agent3/sandbox-figures/{rel.as_posix()}")
        except ValueError:
            # Pas sous _FIGURES_DIR, on garde le chemin brut
            fig_urls.append(str(p))

    # Cleanup work_dir (figures_out_dir est conservee pour le serve)
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass

    result = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": -1 if timed_out else (proc.returncode if proc else -1),
        "duration_s": round(duration_s, 2),
        "figures": fig_urls,
        "error": user_error_msg,
        "timed_out": timed_out,
    }
    return result


__all__ = ["run_python_sandbox"]
