"""
Skill Todo de l'agent Syléa.AI.

Capacités :
  - Créer des listes de tâches structurées
  - Prioriser les actions selon leur impact
  - Décomposer des projets en étapes actionnables
  - Suivre l'avancement

Note : les listes sont générées heuristiquement et retournées sous forme textuelle.
"""

from __future__ import annotations

from datetime import datetime


class SkillTodo:
    """
    Skill de création et gestion de listes de tâches.

    Génère des listes de tâches priorisées et décomposées en actions
    concrètes à partir de l'instruction de l'utilisateur.
    """

    description = "Création de listes de tâches priorisées et décomposition de projets en étapes"

    def executer(self, instruction: str) -> str:
        """
        Génère une liste de tâches basée sur l'instruction.

        Args:
            instruction: Instruction validée décrivant le projet ou la liste à créer

        Returns:
            Liste de tâches formatée avec priorités et délais estimés
        """
        contexte = self._extraire_contexte(instruction)
        taches = self._generer_taches(instruction)
        priorite_conseil = self._conseil_priorite(instruction)

        rapport = f"""LISTE DE TACHES -- {datetime.now().strftime('%d/%m/%Y a %H:%M')}
{'=' * 55}

  CONTEXTE : {contexte}

{'-' * 55}
  TACHES PRIORISEES
{'-' * 55}

  [!] PRIORITE HAUTE (a faire aujourd'hui)
{taches['haute']}

  [~] PRIORITE MOYENNE (cette semaine)
{taches['moyenne']}

  [+] PRIORITE BASSE (quand possible)
{taches['basse']}

{'-' * 55}
  CONSEIL DE PRIORISATION
{'-' * 55}
  {priorite_conseil}

{'=' * 55}
  [OK] Liste creee. Cochez chaque tache a mesure que vous avancez.
{'=' * 55}"""
        return rapport

    # ── Méthodes internes ────────────────────────────────────────────────────

    @staticmethod
    def _extraire_contexte(instruction: str) -> str:
        """Extrait le contexte de la liste depuis l'instruction."""
        mots = instruction.split()
        mots_contexte = [m for m in mots[2:] if len(m) > 3]
        return " ".join(mots_contexte[:6]) if mots_contexte else instruction[:50]

    @staticmethod
    def _generer_taches(instruction: str) -> dict[str, str]:
        """Génère des tâches adaptées au contexte de l'instruction."""
        inst = instruction.lower()

        if any(m in inst for m in ["lancement", "lancer", "démarrer", "projet"]):
            return {
                "haute": (
                    "  [ ]Définir les objectifs et indicateurs de succès\n"
                    "  [ ]Identifier les parties prenantes et responsabilités\n"
                    "  [ ]Allouer le budget et les ressources"
                ),
                "moyenne": (
                    "  [ ]Créer le plan de communication\n"
                    "  [ ]Préparer les outils et environnements\n"
                    "  [ ]Planifier les jalons clés et revues"
                ),
                "basse": (
                    "  [ ]Documenter les processus\n"
                    "  [ ]Anticiper les risques et préparer les plans B\n"
                    "  [ ]Mettre en place le suivi de projet"
                ),
            }

        elif any(m in inst for m in ["client", "réunion", "rendez-vous", "présentation"]):
            return {
                "haute": (
                    "  [ ]Préparer l'ordre du jour et l'envoyer au client\n"
                    "  [ ]Rassembler et relire les documents pertinents\n"
                    "  [ ]Confirmer la participation des intervenants"
                ),
                "moyenne": (
                    "  [ ]Préparer les slides de présentation\n"
                    "  [ ]Anticiper les questions difficiles\n"
                    "  [ ]Préparer le matériel (projecteur, accès, etc.)"
                ),
                "basse": (
                    "  [ ]Envoyer un résumé après la réunion\n"
                    "  [ ]Mettre à jour le CRM\n"
                    "  [ ]Planifier la prochaine étape"
                ),
            }

        elif any(m in inst for m in ["commercial", "vente", "prospect", "acquisition"]):
            return {
                "haute": (
                    "  [ ]Identifier et qualifier les 5 prospects les plus chauds\n"
                    "  [ ]Envoyer les relances en attente (> 3 jours)\n"
                    "  [ ]Préparer les offres commerciales prioritaires"
                ),
                "moyenne": (
                    "  [ ]Mettre à jour le pipeline commercial\n"
                    "  [ ]Planifier les appels découverte\n"
                    "  [ ]Analyser les taux de conversion"
                ),
                "basse": (
                    "  [ ]Alimenter la base de prospects (enrichissement)\n"
                    "  [ ]Préparer les supports de vente\n"
                    "  [ ]Analyser la concurrence"
                ),
            }

        else:
            # Liste générique
            return {
                "haute": (
                    "  [ ]Identifier la tâche la plus bloquante et la résoudre\n"
                    "  [ ]Traiter les éléments urgents et importants\n"
                    "  [ ]Communiquer sur les dépendances critiques"
                ),
                "moyenne": (
                    "  [ ]Avancer sur les projets en cours\n"
                    "  [ ]Planifier les prochaines actions\n"
                    "  [ ]Traiter les emails et demandes reçues"
                ),
                "basse": (
                    "  [ ]Classer et archiver les documents\n"
                    "  [ ]Mettre à jour la documentation\n"
                    "  [ ]Préparer les sujets de la semaine prochaine"
                ),
            }

    @staticmethod
    def _conseil_priorite(instruction: str) -> str:
        """Génère un conseil de priorisation adapté."""
        inst = instruction.lower()
        if any(m in inst for m in ["urgence", "urgent", "demain"]):
            return (
                "Appliquez la matrice Eisenhower : commencez par URGENT + IMPORTANT, "
                "déléguer URGENT + non important."
            )
        elif any(m in inst for m in ["long terme", "objectif", "projet"]):
            return (
                "Utilisez la règle 80/20 : identifiez les 20% de tâches "
                "qui produiront 80% des résultats."
            )
        return (
            "Commencez par la tâche que vous redoutez le plus — "
            "c'est souvent la plus importante (méthode 'Eat the frog')."
        )


class SkillTodoTracker:
    """
    Extension du SkillTodo pour le suivi d'avancement en session.

    Permet de marquer des tâches comme complétées pendant une session.
    Les données ne sont pas persistées entre les sessions.
    """

    def __init__(self) -> None:
        self._taches: list[dict] = []

    def ajouter_tache(self, description: str, priorite: str = "moyenne") -> int:
        """
        Ajoute une tâche à la liste de suivi.

        Args:
            description: Description de la tâche
            priorite   : 'haute' | 'moyenne' | 'basse'

        Returns:
            Index de la tâche (pour la complétion)
        """
        self._taches.append({
            "description": description,
            "priorite": priorite,
            "complete": False,
            "cree_le": datetime.now(),
        })
        return len(self._taches) - 1

    def completer_tache(self, index: int) -> bool:
        """
        Marque une tâche comme complétée.

        Args:
            index: Index de la tâche

        Returns:
            True si la tâche a été complétée, False si index invalide
        """
        if 0 <= index < len(self._taches):
            self._taches[index]["complete"] = True
            return True
        return False

    def rapport_avancement(self) -> str:
        """Génère un rapport d'avancement de la liste."""
        if not self._taches:
            return "Aucune tâche dans la liste."

        completes = sum(1 for t in self._taches if t["complete"])
        total = len(self._taches)
        pourcentage = int((completes / total) * 100) if total > 0 else 0

        lignes = [f"Avancement : {completes}/{total} ({pourcentage}%)\n"]
        for i, t in enumerate(self._taches):
            statut = "[OK]" if t["complete"] else "[ ]"
            lignes.append(f"  {statut} [{t['priorite'].upper()}] {t['description']}")

        return "\n".join(lignes)
