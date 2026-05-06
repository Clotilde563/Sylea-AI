"""
Rendu HTML d'une fiche markdown (Sprint 3.2 — Ecoute active).

Le markdown brut est illisible quand l'utilisateur l'ouvre dans Word ou
double-clique le fichier. On genere a cote un .html avec :
  - CSS minimal soigne (typographie reading-friendly)
  - KaTeX (CDN) pour rendu LaTeX inline + display
  - Code blocks avec coloration legere
  - Blockquotes avec rail vertical

Le fichier .html est self-contained (CSS + KaTeX inline ou via CDN), peut
etre ouvert :
  - dans Word (rendu ~correct, sans LaTeX si offline)
  - dans un navigateur (rendu parfait, LaTeX OK)
  - imprime en PDF via Ctrl+P
"""

from __future__ import annotations


# CSS embarque — typographie academique sobre, palette cyan/violet pour les
# titres en hommage a la palette Sylea.
_CSS = """
* { box-sizing: border-box; }
body {
    font-family: Georgia, "Cambria", "Times New Roman", serif;
    line-height: 1.65;
    max-width: 760px;
    margin: 40px auto;
    padding: 0 28px;
    color: #1a1a2e;
    background: #fafbfc;
}
h1 {
    font-family: -apple-system, "Segoe UI", "Inter", sans-serif;
    font-size: 2em;
    color: #0a3460;
    border-bottom: 3px solid #00c8ff;
    padding-bottom: 8px;
    margin-top: 0;
}
h2 {
    font-family: -apple-system, "Segoe UI", "Inter", sans-serif;
    font-size: 1.4em;
    color: #1848d8;
    margin-top: 2em;
    border-left: 4px solid #00c8ff;
    padding-left: 12px;
}
h3 {
    font-family: -apple-system, "Segoe UI", "Inter", sans-serif;
    font-size: 1.15em;
    color: #5520b8;
    margin-top: 1.5em;
}
h4, h5, h6 {
    font-family: -apple-system, "Segoe UI", sans-serif;
    color: #444;
}
p { margin: 0.6em 0; }
strong { color: #0a3460; }
em { color: #5520b8; }
ul, ol { margin: 0.6em 0; padding-left: 1.6em; }
li { margin: 0.25em 0; }
blockquote {
    margin: 1.2em 0;
    padding: 0.6em 1em;
    border-left: 4px solid #5520b8;
    background: rgba(85, 32, 184, 0.05);
    font-style: italic;
    color: #444;
    border-radius: 0 6px 6px 0;
}
code {
    font-family: "JetBrains Mono", "Cascadia Code", Consolas, monospace;
    font-size: 0.92em;
    background: rgba(0, 200, 255, 0.08);
    padding: 1px 5px;
    border-radius: 3px;
    color: #0a3460;
}
pre {
    background: #f4f6fa;
    border: 1px solid #d8dde6;
    border-radius: 6px;
    padding: 12px 16px;
    overflow-x: auto;
}
pre code { background: transparent; padding: 0; color: #1a1a2e; }
hr { border: none; border-top: 1px solid #d0d7e2; margin: 2em 0; }
table {
    border-collapse: collapse;
    margin: 1em 0;
    width: 100%;
}
th, td {
    border: 1px solid #c9d2e0;
    padding: 6px 12px;
    text-align: left;
}
th {
    background: rgba(0, 200, 255, 0.08);
    color: #0a3460;
}
.fiche-meta {
    font-family: -apple-system, "Segoe UI", monospace;
    font-size: 0.78em;
    color: #6a7585;
    background: rgba(0, 200, 255, 0.05);
    border: 1px solid rgba(0, 200, 255, 0.20);
    padding: 8px 12px;
    border-radius: 6px;
    margin-bottom: 24px;
}
.fiche-meta strong { color: #1848d8; }
@media print {
    body { background: white; max-width: 100%; padding: 0 1cm; }
    .fiche-meta { background: #f0f0f0; }
}
"""


# KaTeX via CDN — rendu LaTeX automatique sur $...$ et $$...$$
# auto-render attache un script qui scanne le DOM et remplace les
# delimiteurs par du LaTeX rendu. Fonctionne offline une fois la page
# chargee (KaTeX est embedded dans la cache navigateur).
_KATEX_HEAD = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" crossorigin="anonymous">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js" crossorigin="anonymous"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js" crossorigin="anonymous"
        onload="renderMathInElement(document.body, {
            delimiters: [
                {left: '$$', right: '$$', display: true},
                {left: '$', right: '$', display: false}
            ]
        });"></script>
"""


def render_fiche_html(
    fiche_markdown: str,
    titre: str,
    matiere: str,
    formation: str | None = None,
    session_id: str | None = None,
    matiere_auto_detected: bool = False,
) -> str:
    """Convertit le markdown en HTML standalone avec CSS + KaTeX."""
    import markdown as md
    body_html = md.markdown(
        fiche_markdown,
        extensions=["extra", "sane_lists", "smarty"],
    )

    # Encadre meta lignes (matiere, formation, session) en haut du corps
    meta_parts = []
    if matiere:
        m_str = matiere.upper()
        if matiere_auto_detected:
            m_str += " (auto-detect)"
        meta_parts.append(f"<strong>Matiere</strong> : {m_str}")
    if formation:
        meta_parts.append(f"<strong>Formation</strong> : {formation}")
    if session_id:
        meta_parts.append(f"<strong>Session</strong> : <code>{session_id}</code>")
    meta_html = ""
    if meta_parts:
        meta_html = '<div class="fiche-meta">' + ' &nbsp; · &nbsp; '.join(meta_parts) + '</div>'

    safe_title = (titre or "Cours").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} — Sylea Agent</title>
<style>{_CSS}</style>
{_KATEX_HEAD}
</head>
<body>
{meta_html}
{body_html}
<hr>
<p style="font-size: 0.72em; color: #8a95a5; text-align: center;">
  Genere par Sylea Agent · Ecoute active
</p>
</body>
</html>
"""
