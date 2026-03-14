"""
Skill Calendrier de l'agent Syléa.AI.

Capacités :
  - Proposer une organisation de l'emploi du temps
  - Suggérer des créneaux de travail optimal
  - Planifier des séquences de tâches
  - Générer un planning hebdomadaire

Note : les créneaux sont générés heuristiquement (pas de connexion calendrier réelle).
"""

from __future__ import annotations

from datetime import datetime, timedelta


class SkillCalendrier:
    """
    Skill de planification et d'organisation temporelle.

    Génère des propositions d'emploi du temps et des blocs de travail
    adaptés à l'instruction reçue.
    """

    description = "Planification de l'emploi du temps, suggestion de créneaux et organisation"

    def executer(self, instruction: str) -> str:
        """
        Génère une proposition de planning basée sur l'instruction.

        Args:
            instruction: Instruction validée décrivant la demande de planification

        Returns:
            Planning proposé sous forme textuelle
        """
        type_planning = self._detecter_type(instruction)
        planning = self._generer_planning(type_planning, instruction)
        conseils = self._generer_conseils_productivite(instruction)

        rapport = f"""PLANNING PROPOSE -- {datetime.now().strftime('%d/%m/%Y a %H:%M')}
{'=' * 55}

  TYPE : {type_planning.upper()}

{'-' * 55}
  ORGANISATION SUGGEREE
{'-' * 55}
{planning}

{'-' * 55}
  CONSEILS DE PRODUCTIVITE
{'-' * 55}
{conseils}

{'=' * 55}
  Note : Planning a valider et ajuster selon vos contraintes reelles.
{'=' * 55}"""
        return rapport

    # ── Méthodes internes ────────────────────────────────────────────────────

    @staticmethod
    def _detecter_type(instruction: str) -> str:
        """Détecte le type de planning demandé."""
        inst = instruction.lower()
        if any(m in inst for m in ["semaine", "hebdomadaire", "semaine prochaine"]):
            return "planning hebdomadaire"
        elif any(m in inst for m in ["journée", "aujourd'hui", "demain"]):
            return "planning journalier"
        elif any(m in inst for m in ["mois", "mensuel"]):
            return "planning mensuel"
        elif any(m in inst for m in ["réunion", "rendez-vous", "créneau"]):
            return "gestion de réunions"
        elif any(m in inst for m in ["sprint", "projet", "lancement"]):
            return "planning projet"
        return "planning journalier"

    @staticmethod
    def _generer_planning(type_planning: str, instruction: str) -> str:
        """Génère la structure du planning selon le type."""
        maintenant = datetime.now()

        if type_planning == "planning journalier":
            demain = (maintenant + timedelta(days=1)).strftime("%A %d %B")
            return (
                f"  Planning du {demain}\n\n"
                "  08h00 - 09h00  | Routine matinale + lecture des messages\n"
                "  09h00 - 10h30  | BLOC FOCUS #1 -- Tache prioritaire du jour\n"
                "  10h30 - 10h45  | Pause\n"
                "  10h45 - 12h15  | BLOC FOCUS #2 -- Tache secondaire\n"
                "  12h15 - 13h30  | Dejeuner (idealement sans ecran)\n"
                "  13h30 - 15h00  | Traitement emails + communication\n"
                "  15h00 - 16h30  | BLOC FOCUS #3 -- Reunions ou tache tactique\n"
                "  16h30 - 17h00  | [OK] Revue du jour + preparation du lendemain\n"
                "  17h00          | Activite physique recommandee"
            )

        elif type_planning == "planning hebdomadaire":
            lundi = maintenant + timedelta(days=(7 - maintenant.weekday()))
            semaine = lundi.strftime("semaine du %d %B")
            return (
                f"  Planning -- {semaine}\n\n"
                "  LUNDI     | Revue objectifs semaine + tache principale #1\n"
                "  MARDI     | Bloc production (4h focus) + reunions importantes\n"
                "  MERCREDI  | Tache principale #2 + developpement reseau\n"
                "  JEUDI     | Suivi des projets en cours + tache #3\n"
                "  VENDREDI  | Taches administratives + bilan hebdomadaire\n\n"
                "  Chaque matin (09h-10h30) : BLOC FOCUS non negociable\n"
                "  Chaque soir (17h-17h30) : Preparation du lendemain"
            )

        elif type_planning == "planning projet":
            return (
                "  PHASE 1 -- Cadrage (J1-J3)\n"
                "    - Definition des objectifs et perimetre\n"
                "    - Identification des parties prenantes\n"
                "    - Inventaire des ressources disponibles\n\n"
                "  PHASE 2 -- Production (J4-J15)\n"
                "    - Execution des taches selon priorite\n"
                "    - Points d'avancement quotidiens (15 min)\n"
                "    - Resolution des blocages\n\n"
                "  PHASE 3 -- Finalisation (J16-J20)\n"
                "    - Revue qualite et corrections\n"
                "    - Validation par les parties prenantes\n"
                "    - Livraison et bilan"
            )

        elif type_planning == "gestion de réunions":
            return (
                "  BONNES PRATIQUES — Organisation des réunions\n\n"
                "  • Créneaux idéaux : 10h-12h ou 14h-16h\n"
                "  • Éviter : lundi matin, vendredi après-midi\n"
                "  • Durée recommandée : 30 min (décision) / 45 min (revue)\n"
                "  • Envoyer l'ordre du jour 24h à l'avance\n"
                "  • Désigner un animateur et un secrétaire de séance\n"
                "  • Clôturer avec : actions, responsables, délais"
            )

        else:  # planning mensuel
            mois = (maintenant + timedelta(days=30)).strftime("%B")
            return (
                f"  PLANNING MENSUEL — {mois}\n\n"
                "  Semaine 1 : Cadrage et lancement des sujets prioritaires\n"
                "  Semaine 2 : Exécution intense — bloc focus quotidien\n"
                "  Semaine 3 : Suivi, ajustements et réunions bilan\n"
                "  Semaine 4 : Finalisation, livraisons et préparation mois suivant\n\n"
                "  • 1 bilan hebdomadaire : vendredi 17h\n"
                "  • 1 revue mensuelle : dernier vendredi du mois"
            )

    @staticmethod
    def _generer_conseils_productivite(instruction: str) -> str:
        """Génère des conseils de productivité adaptés."""
        inst = instruction.lower()
        conseils = []

        if any(m in inst for m in ["réunion", "meeting"]):
            conseils.append(
                "  Limitez les reunions recurrentes a 30 minutes "
                "et imposez un ordre du jour ecrit."
            )

        conseils += [
            "  Technique Pomodoro : 25 min de focus + 5 min de pause",
            "  Desactivez les notifications pendant vos blocs focus",
            "  Placez votre tache la plus importante en debut de journee",
            "  Terminez chaque journee en preparant la liste de demain",
        ]
        return "\n".join(conseils[:4])
