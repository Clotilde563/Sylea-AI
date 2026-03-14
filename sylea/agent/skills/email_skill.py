"""
Skill Email de l'agent Syléa.AI.

Capacités :
  - Rédiger des brouillons d'email professionnels
  - Identifier les éléments clés à inclure
  - Proposer l'objet, les formules de politesse et le corps du message

Note : toutes les exécutions sont simulées (aucun envoi réel).
"""

from __future__ import annotations

import random
from datetime import datetime


class SkillEmail:
    """
    Skill de rédaction et d'organisation d'emails.

    Génère des brouillons d'email professionnels à partir de l'instruction,
    en extrayant les informations clés (destinataire, objet, contexte).
    """

    description = "Rédaction de brouillons d'email, relances et réponses professionnelles"

    def executer(self, instruction: str) -> str:
        """
        Génère un brouillon d'email basé sur l'instruction.

        Args:
            instruction: Instruction validée décrivant l'email à préparer

        Returns:
            Rapport textuel contenant le brouillon et les métadonnées
        """
        # Extraction des éléments clés de l'instruction
        destinataire = self._extraire_destinataire(instruction)
        objet = self._generer_objet(instruction)
        corps = self._generer_corps(instruction)
        formule_politesse = self._choisir_formule_politesse(instruction)

        brouillon = f"""
-------------------------------------------------
  BROUILLON D'EMAIL -- {datetime.now().strftime('%d/%m/%Y a %H:%M')}
-------------------------------------------------

A      : {destinataire}
Objet  : {objet}

-------------------------------------------------

{corps}

{formule_politesse}

-------------------------------------------------
[!] BROUILLON -- A relire et valider avant envoi
-------------------------------------------------
""".strip()

        rapport = (
            f"Email préparé avec succès.\n"
            f"Destinataire estimé : {destinataire}\n"
            f"Objet : {objet}\n\n"
            f"{brouillon}"
        )
        return rapport

    # ── Méthodes internes ────────────────────────────────────────────────────

    @staticmethod
    def _extraire_destinataire(instruction: str) -> str:
        """Tente d'extraire le destinataire depuis l'instruction."""
        mots = instruction.split()
        # Cherche des noms propres (majuscule, pas en début de phrase)
        for i, mot in enumerate(mots[1:], 1):
            if mot[0].isupper() and len(mot) > 2:
                return mot
        return "[Destinataire à compléter]"

    @staticmethod
    def _generer_objet(instruction: str) -> str:
        """Génère un objet d'email en extrayant le contexte de l'instruction."""
        inst_lower = instruction.lower()

        if "relance" in inst_lower or "relancer" in inst_lower:
            return "Relance — Suite à notre échange"
        elif "devis" in inst_lower:
            return "Devis — Proposition commerciale"
        elif "réunion" in inst_lower or "meeting" in inst_lower:
            return "Confirmation de réunion"
        elif "présentation" in inst_lower:
            return "Présentation — Documents joints"
        elif "rapport" in inst_lower:
            return "Rapport — Synthèse"
        elif "partenariat" in inst_lower:
            return "Proposition de partenariat"
        else:
            return "Suite à notre conversation — Action requise"

    @staticmethod
    def _generer_corps(instruction: str) -> str:
        """Génère le corps de l'email selon le contexte."""
        inst_lower = instruction.lower()

        if "relance" in inst_lower:
            return (
                "Bonjour,\n\n"
                "Je me permets de revenir vers vous concernant notre échange précédent.\n"
                "Sans retour de votre part, je souhaitais m'assurer que vous avez bien "
                "reçu les informations transmises.\n\n"
                "Seriez-vous disponible pour en discuter cette semaine ?\n\n"
                "Je reste à votre disposition pour tout complément d'information."
            )
        elif "devis" in inst_lower or "offre" in inst_lower:
            return (
                "Bonjour,\n\n"
                "Suite à nos échanges, veuillez trouver ci-joint notre proposition.\n\n"
                "Celle-ci comprend :\n"
                "  • La description détaillée des prestations\n"
                "  • Le calendrier d'intervention\n"
                "  • Les conditions tarifaires\n\n"
                "Je reste disponible pour répondre à vos questions."
            )
        elif "réunion" in inst_lower:
            return (
                "Bonjour,\n\n"
                "Je reviens vers vous afin d'organiser une réunion pour faire le point "
                "sur l'avancement de notre collaboration.\n\n"
                "Seriez-vous disponible en début de semaine prochaine ?\n"
                "Je peux m'adapter à vos disponibilités.\n\n"
                "Dans l'attente de votre retour,"
            )
        else:
            return (
                "Bonjour,\n\n"
                "Je me permets de vous contacter concernant notre projet en cours.\n\n"
                "Après analyse de la situation, voici les points importants à retenir :\n"
                "  • Point 1 — [À compléter]\n"
                "  • Point 2 — [À compléter]\n\n"
                "N'hésitez pas à me revenir si vous avez des questions."
            )

    @staticmethod
    def _choisir_formule_politesse(instruction: str) -> str:
        """Choisit une formule de politesse adaptée au contexte."""
        formules = [
            "Cordialement,",
            "Bien cordialement,",
            "Avec mes meilleures salutations,",
        ]
        if "client" in instruction.lower():
            return "Avec mes sincères salutations,"
        return random.choice(formules)
