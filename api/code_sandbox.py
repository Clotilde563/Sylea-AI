"""
Code Sandbox — Execution isolee de code pour Sylea Agent 3.

Fournit un environnement d'execution securise avec :
  - Isolation par repertoire temporaire (chaque execution a son propre dossier)
  - Validation statique du code (blocage des patterns dangereux)
  - Timeout configurable (defaut 30s)
  - Limite de taille de sortie (defaut 50KB)
  - Support multi-langage (Python, Node.js, shell)
  - Nettoyage automatique apres execution

Architecture :
  [Agent 3] -> [ACTION:CODE] -> [CodeSandbox.execute()] -> [subprocess isolé]
                                                         -> [SandboxResult]
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("code_sandbox")

# ── Configuration ─────────────────────────────────────────────────────────────

SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "30"))       # secondes
SANDBOX_MAX_OUTPUT = int(os.environ.get("SANDBOX_MAX_OUTPUT", "51200"))  # 50KB
SANDBOX_BASE_DIR = Path(os.environ.get(
    "SANDBOX_DIR",
    str(Path(__file__).resolve().parent.parent / "data" / "sandbox")
))

# Langages supportes avec leur commande d'execution
SUPPORTED_LANGUAGES = {
    "python": {"ext": ".py", "cmd": [sys.executable]},
    "python3": {"ext": ".py", "cmd": [sys.executable]},
    "py": {"ext": ".py", "cmd": [sys.executable]},
    "javascript": {"ext": ".js", "cmd": ["node"]},
    "js": {"ext": ".js", "cmd": ["node"]},
    "node": {"ext": ".js", "cmd": ["node"]},
    "bash": {"ext": ".sh", "cmd": ["bash"]},
    "sh": {"ext": ".sh", "cmd": ["bash"]},
    "powershell": {"ext": ".ps1", "cmd": ["powershell", "-ExecutionPolicy", "Bypass", "-File"]},
    "ps1": {"ext": ".ps1", "cmd": ["powershell", "-ExecutionPolicy", "Bypass", "-File"]},
    "bat": {"ext": ".bat", "cmd": ["cmd", "/c"]},
    "cmd": {"ext": ".bat", "cmd": ["cmd", "/c"]},
}

# ── Patterns dangereux (validation statique) ──────────────────────────────────

# Patterns bloques dans le code source AVANT execution
# Niveau 1 : Critiques (peuvent detruire le systeme)
BLOCKED_PATTERNS_CRITICAL: list[tuple[str, str]] = [
    (r"\bos\.system\s*\(", "os.system() interdit — utilise subprocess"),
    (r"\bshutil\.rmtree\s*\(", "shutil.rmtree() interdit — suppression recursive"),
    (r"\bos\.remove\s*\(", "os.remove() interdit en sandbox"),
    (r"\bos\.unlink\s*\(", "os.unlink() interdit en sandbox"),
    (r"\bos\.rmdir\s*\(", "os.rmdir() interdit en sandbox"),
    (r"\bos\.rename\s*\(", "os.rename() interdit en sandbox"),
    (r"\bos\.chmod\s*\(", "os.chmod() interdit en sandbox"),
    (r"\bos\.chown\s*\(", "os.chown() interdit en sandbox"),
    (r"\bos\.kill\s*\(", "os.kill() interdit en sandbox"),
    (r"\bos\.exec", "os.exec*() interdit en sandbox"),
    (r"\bos\.fork\s*\(", "os.fork() interdit en sandbox"),
    (r"\bos\.spawn", "os.spawn*() interdit en sandbox"),
    (r"\bctypes\b", "ctypes interdit en sandbox"),
    (r"\bsubprocess\s*\.\s*(Popen|run|call|check_output|check_call)\s*\(", "subprocess interdit en sandbox"),
    (r"__import__\s*\(", "__import__() interdit en sandbox"),
    (r"\beval\s*\(.*\bos\b", "eval() avec os interdit"),
    (r"\bexec\s*\(.*\bos\b", "exec() avec os interdit"),
    (r"import\s+ctypes", "import ctypes interdit"),
    (r"from\s+ctypes", "from ctypes interdit"),
]

# Niveau 2 : Reseau (peut exfiltrer des donnees)
BLOCKED_PATTERNS_NETWORK: list[tuple[str, str]] = [
    (r"\bsocket\b.*\bconnect\b", "socket.connect() interdit en sandbox"),
    (r"\burllib\.request\b", "urllib.request interdit en sandbox — pas d'acces reseau"),
    (r"\bhttpx?\b.*\b(get|post|put|delete)\b", "HTTP requests interdit en sandbox"),
    (r"\brequests\.(get|post|put|delete|head|patch)\s*\(", "requests interdit en sandbox"),
]

# Niveau 3 : Acces fichiers hors sandbox
BLOCKED_PATTERNS_FS: list[tuple[str, str]] = [
    (r"""open\s*\(\s*['"]/""", "Acces fichier absolu interdit (chemin /)"),
    (r"""open\s*\(\s*['"][A-Z]:\\""", "Acces fichier absolu interdit (chemin Windows)"),
    (r"\.\.\s*/", "Traversal de repertoire interdit (../)"),
    (r"\.\.\s*\\\\", r"Traversal de repertoire interdit (..\\)"),
]


@dataclass
class SandboxResult:
    """Resultat d'une execution en sandbox."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    language: str
    filename: str
    execution_time_ms: int = 0
    truncated: bool = False
    blocked: bool = False
    block_reason: str = ""
    sandbox_id: str = ""

    def to_dict(self) -> dict:
        d = {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "language": self.language,
            "filename": self.filename,
            "execution_time_ms": self.execution_time_ms,
        }
        if self.truncated:
            d["truncated"] = True
        if self.blocked:
            d["blocked"] = True
            d["block_reason"] = self.block_reason
        if self.sandbox_id:
            d["sandbox_id"] = self.sandbox_id
        return d


class CodeSandbox:
    """
    Environnement d'execution isole pour du code utilisateur.

    Usage :
        sandbox = CodeSandbox()
        result = await sandbox.execute("print('hello')", language="python")
        print(result.stdout)  # "hello\n"
    """

    def __init__(
        self,
        timeout: int = SANDBOX_TIMEOUT,
        max_output: int = SANDBOX_MAX_OUTPUT,
        allow_network: bool = False,
        allow_fs_write: bool = True,  # Ecriture dans le sandbox uniquement
    ):
        self.timeout = timeout
        self.max_output = max_output
        self.allow_network = allow_network
        self.allow_fs_write = allow_fs_write

    def validate_code(self, code: str, language: str) -> tuple[bool, str]:
        """
        Valide le code source AVANT execution.
        Retourne (True, "") si OK, (False, raison) si bloque.
        """
        if not code or not code.strip():
            return False, "Code vide"

        # Taille max du code source : 100KB
        if len(code) > 102400:
            return False, f"Code trop long ({len(code)} chars, max 100KB)"

        # Seuls Python, JS, shell sont valides statiquement
        if language not in ("python", "python3", "py", "javascript", "js", "node"):
            # Shell/bat/ps1 : pas de validation statique avancee, juste taille
            return True, ""

        # Verifier les patterns critiques
        for pattern, reason in BLOCKED_PATTERNS_CRITICAL:
            if re.search(pattern, code, re.IGNORECASE):
                return False, reason

        # Verifier les patterns reseau (sauf si allow_network)
        if not self.allow_network:
            for pattern, reason in BLOCKED_PATTERNS_NETWORK:
                if re.search(pattern, code, re.IGNORECASE):
                    return False, reason

        # Verifier les acces fichiers hors sandbox
        for pattern, reason in BLOCKED_PATTERNS_FS:
            if re.search(pattern, code, re.IGNORECASE):
                return False, reason

        return True, ""

    async def execute(
        self,
        code: str,
        language: str = "python",
        filename: str | None = None,
    ) -> SandboxResult:
        """
        Execute du code dans un environnement isole.

        Args:
            code: Code source a executer
            language: Langage (python, javascript, bash, powershell, etc.)
            filename: Nom du fichier (optionnel, genere automatiquement)

        Returns:
            SandboxResult avec stdout, stderr, exit_code, etc.
        """
        language = language.lower().strip()
        sandbox_id = uuid.uuid4().hex[:12]

        # Verifier le langage
        lang_config = SUPPORTED_LANGUAGES.get(language)
        if not lang_config:
            return SandboxResult(
                success=False, exit_code=-1, stdout="", stderr=f"Langage non supporte: {language}. Langages disponibles: {', '.join(SUPPORTED_LANGUAGES.keys())}",
                language=language, filename="", blocked=True, block_reason=f"Langage '{language}' non supporte",
                sandbox_id=sandbox_id,
            )

        # Valider le code source
        is_valid, block_reason = self.validate_code(code, language)
        if not is_valid:
            return SandboxResult(
                success=False, exit_code=-1, stdout="", stderr=f"Code bloque: {block_reason}",
                language=language, filename="", blocked=True, block_reason=block_reason,
                sandbox_id=sandbox_id,
            )

        # Creer le repertoire sandbox isole
        SANDBOX_BASE_DIR.mkdir(parents=True, exist_ok=True)
        sandbox_dir = SANDBOX_BASE_DIR / f"run_{sandbox_id}"
        sandbox_dir.mkdir(parents=True, exist_ok=True)

        # Generer le nom de fichier
        ext = lang_config["ext"]
        if not filename:
            filename = f"script{ext}"
        elif not filename.endswith(ext):
            filename = f"{filename}{ext}"

        script_path = sandbox_dir / filename

        try:
            # Ecrire le code dans le fichier
            script_path.write_text(code, encoding="utf-8")

            # Construire la commande
            cmd_base = list(lang_config["cmd"])

            # Verifier que l'executable existe
            exe = cmd_base[0]
            exe_path = shutil.which(exe)
            if not exe_path:
                return SandboxResult(
                    success=False, exit_code=-1, stdout="",
                    stderr=f"Executable '{exe}' introuvable. Verifiez que {language} est installe.",
                    language=language, filename=filename, sandbox_id=sandbox_id,
                )
            cmd_base[0] = exe_path

            cmd = cmd_base + [str(script_path)]

            # Preparer l'environnement restreint
            env = self._build_restricted_env(sandbox_dir)

            # Flags Windows : pas de fenetre console
            is_windows = sys.platform == "win32"
            creation_flags = 0x08000000 if is_windows else 0  # CREATE_NO_WINDOW

            # Executer dans un thread (asyncio.to_thread pour Windows ProactorEventLoop)
            import subprocess as _sp
            import time

            def _run():
                start = time.monotonic()
                try:
                    result = _sp.run(
                        cmd,
                        capture_output=True,
                        timeout=self.timeout,
                        cwd=str(sandbox_dir),
                        env=env,
                        creationflags=creation_flags,
                    )
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    return result, elapsed_ms
                except _sp.TimeoutExpired:
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    return None, elapsed_ms

            proc_result, elapsed_ms = await asyncio.to_thread(_run)

            if proc_result is None:
                return SandboxResult(
                    success=False, exit_code=-1,
                    stdout="", stderr=f"Timeout: execution interrompue apres {self.timeout}s",
                    language=language, filename=filename,
                    execution_time_ms=elapsed_ms, sandbox_id=sandbox_id,
                )

            # Decoder la sortie
            stdout = proc_result.stdout.decode("utf-8", errors="replace")
            stderr = proc_result.stderr.decode("utf-8", errors="replace")

            # Tronquer si necessaire
            truncated = False
            if len(stdout) > self.max_output:
                stdout = stdout[:self.max_output] + f"\n\n... [sortie tronquee a {self.max_output // 1024}KB]"
                truncated = True
            if len(stderr) > self.max_output:
                stderr = stderr[:self.max_output] + f"\n\n... [erreur tronquee a {self.max_output // 1024}KB]"
                truncated = True

            return SandboxResult(
                success=proc_result.returncode == 0,
                exit_code=proc_result.returncode,
                stdout=stdout,
                stderr=stderr,
                language=language,
                filename=filename,
                execution_time_ms=elapsed_ms,
                truncated=truncated,
                sandbox_id=sandbox_id,
            )

        except Exception as e:
            logger.exception(f"Sandbox execution error: {e}")
            return SandboxResult(
                success=False, exit_code=-1, stdout="",
                stderr=f"Erreur sandbox ({type(e).__name__}): {str(e)[:300]}",
                language=language, filename=filename, sandbox_id=sandbox_id,
            )
        finally:
            # Nettoyage du repertoire sandbox
            self._cleanup(sandbox_dir)

    def _build_restricted_env(self, sandbox_dir: Path) -> dict:
        """
        Construit un environnement restreint pour le subprocess.
        Herite de l'env systeme mais restreint certaines variables.
        """
        env = os.environ.copy()

        # Forcer le repertoire de travail
        env["HOME"] = str(sandbox_dir)
        env["USERPROFILE"] = str(sandbox_dir)
        env["TMPDIR"] = str(sandbox_dir)
        env["TEMP"] = str(sandbox_dir)
        env["TMP"] = str(sandbox_dir)

        # Supprimer les secrets/tokens
        keys_to_remove = [
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY",
            "OPENCLAW_GATEWAY_TOKEN", "OPENCLAW_CLI_PATH",
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
            "GITHUB_TOKEN", "GH_TOKEN",
            "DATABASE_URL", "DB_PASSWORD",
            "SMTP_PASSWORD", "EMAIL_PASSWORD",
        ]
        for key in keys_to_remove:
            env.pop(key, None)

        # Marquer l'env comme sandbox
        env["SYLEA_SANDBOX"] = "1"
        env["SYLEA_SANDBOX_DIR"] = str(sandbox_dir)

        return env

    def _cleanup(self, sandbox_dir: Path) -> None:
        """Nettoie le repertoire sandbox apres execution."""
        try:
            if sandbox_dir.exists():
                shutil.rmtree(sandbox_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Sandbox cleanup failed for {sandbox_dir}: {e}")

    async def execute_shell(self, command: str) -> SandboxResult:
        """
        Execute une commande shell unique dans le sandbox.
        Raccourci pour execute() avec language="bash" ou "cmd".
        """
        is_windows = sys.platform == "win32"
        lang = "cmd" if is_windows else "bash"
        return await self.execute(code=command, language=lang, filename="command")


# ── Instance globale ──────────────────────────────────────────────────────────

_sandbox = CodeSandbox()


async def sandbox_execute_code(
    code: str,
    language: str = "python",
    filename: str | None = None,
    timeout: int | None = None,
) -> SandboxResult:
    """
    Point d'entree principal pour executer du code en sandbox.
    Utilise l'instance globale avec timeout optionnel.
    """
    if timeout and timeout != _sandbox.timeout:
        sandbox = CodeSandbox(timeout=timeout)
        return await sandbox.execute(code, language, filename)
    return await _sandbox.execute(code, language, filename)


async def sandbox_execute_shell(command: str) -> SandboxResult:
    """Execute une commande shell dans le sandbox."""
    return await _sandbox.execute_shell(command)


def sandbox_validate(code: str, language: str = "python") -> tuple[bool, str]:
    """Valide du code sans l'executer."""
    return _sandbox.validate_code(code, language)
