"""Agent IA de Syléa.AI — interface avec Claude d'Anthropic."""

# Import optionnel : anthropic n'est requis que pour le mode Claude complet.
# Sans cette bibliothèque, l'application fonctionne en mode simulation locale.
try:
    from .claude_agent import AgentSylea
    __all__ = ["AgentSylea"]
except ImportError:
    AgentSylea = None  # type: ignore[assignment,misc]
    __all__ = []
