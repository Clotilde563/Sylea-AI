"""
Skill Document de l'agent Syléa.AI.

Capacités :
  - Structurer des dossiers professionnels
  - Créer des plans de présentation
  - Générer des trames de rapports
  - Proposer des structures de notes de synthèse

Note : toutes les exécutions sont simulées (aucun fichier n'est créé sur disque).
"""

from __future__ import annotations

from datetime import datetime


class SkillDocument:
    """
    Skill de structuration et création de documents professionnels.

    Génère des plans et structures détaillées pour différents types
    de documents en fonction de l'instruction de l'utilisateur.
    """

    description = "Structuration de dossiers, rapports, présentations et notes de synthèse"

    def executer(self, instruction: str) -> str:
        """
        Génère la structure d'un document basé sur l'instruction.

        Args:
            instruction: Instruction validée décrivant le document à créer

        Returns:
            Rapport textuel contenant la structure proposée
        """
        type_doc = self._detecter_type(instruction)
        titre = self._generer_titre(instruction, type_doc)
        structure = self._generer_structure(type_doc, instruction)

        rapport = (
            f"Document structure -- {datetime.now().strftime('%d/%m/%Y a %H:%M')}\n"
            f"Type : {type_doc.upper()}\n"
            f"Titre suggere : {titre}\n\n"
            f"STRUCTURE PROPOSEE :\n"
            f"{'-' * 50}\n"
            f"{structure}\n"
            f"{'-' * 50}\n"
            f"Structure prete a etre completee."
        )
        return rapport

    # ── Méthodes internes ────────────────────────────────────────────────────

    @staticmethod
    def _detecter_type(instruction: str) -> str:
        """Détecte le type de document demandé."""
        inst = instruction.lower()
        if any(m in inst for m in ["présentation", "powerpoint", "slides", "deck"]):
            return "présentation"
        elif any(m in inst for m in ["rapport", "compte rendu", "bilan"]):
            return "rapport"
        elif any(m in inst for m in ["synthèse", "résumé", "note de"]):
            return "synthèse"
        elif any(m in inst for m in ["dossier", "cahier", "brief"]):
            return "dossier"
        elif any(m in inst for m in ["contrat", "accord", "convention"]):
            return "contrat"
        return "dossier"

    @staticmethod
    def _generer_titre(instruction: str, type_doc: str) -> str:
        """Génère un titre pour le document."""
        # Extraire un nom propre ou un sujet de l'instruction
        mots = instruction.split()
        noms_propres = [m for m in mots[2:] if m and m[0].isupper() and len(m) > 2]

        if noms_propres:
            sujet = " ".join(noms_propres[:2])
            return f"{type_doc.capitalize()} — {sujet}"
        return f"{type_doc.capitalize()} — Sujet à préciser"

    @staticmethod
    def _generer_structure(type_doc: str, instruction: str) -> str:
        """Génère une structure adaptée au type de document."""
        structures = {
            "présentation": (
                "  I.    Page de titre\n"
                "  II.   Contexte et problématique (2 slides)\n"
                "  III.  Analyse de la situation actuelle (3 slides)\n"
                "  IV.   Solution proposée et bénéfices (3 slides)\n"
                "  V.    Plan d'action et jalons (2 slides)\n"
                "  VI.   Budget et ressources nécessaires (1 slide)\n"
                "  VII.  Conclusion et prochaines étapes (1 slide)\n"
                "  VIII. Questions / Échanges (1 slide)"
            ),
            "rapport": (
                "  1. Page de garde\n"
                "     -> Titre, auteur, date, destinataire\n"
                "  2. Resume executif (1 page)\n"
                "     -> Points cles et conclusions principales\n"
                "  3. Introduction\n"
                "     -> Contexte, objectifs, perimetre\n"
                "  4. Methodologie\n"
                "     -> Sources utilisees, approche d'analyse\n"
                "  5. Resultats et analyse\n"
                "     -> Donnees, graphiques, interpretations\n"
                "  6. Recommandations\n"
                "     -> Actions prioritaires et feuille de route\n"
                "  7. Annexes\n"
                "     -> Donnees brutes, references, glossaire"
            ),
            "synthese": (
                "  * Objet de la synthese\n"
                "  * Principaux enseignements (3-5 points)\n"
                "  * Analyse critique\n"
                "  * Recommandations operationnelles\n"
                "  * Points de vigilance\n"
                "  * Prochaines etapes"
            ),
            "dossier": (
                "  1. Page de presentation\n"
                "     -> Contexte general, objectif du dossier\n"
                "  2. Presentation de l'entite / projet\n"
                "     -> Description, historique, acteurs cles\n"
                "  3. Analyse des besoins\n"
                "     -> Problematiques identifiees\n"
                "  4. Proposition / Solution\n"
                "     -> Detail de l'offre ou du plan\n"
                "  5. Planning et organisation\n"
                "     -> Jalons, responsabilites, delais\n"
                "  6. Elements financiers\n"
                "     -> Budget, ROI estime\n"
                "  7. Documents complementaires"
            ),
            "contrat": (
                "  Art. 1 — Objet du contrat\n"
                "  Art. 2 — Parties contractantes\n"
                "  Art. 3 — Durée et prise d'effet\n"
                "  Art. 4 — Obligations de chaque partie\n"
                "  Art. 5 — Conditions financières\n"
                "  Art. 6 — Confidentialité\n"
                "  Art. 7 — Résiliation\n"
                "  Art. 8 — Litiges et juridiction compétente\n"
                "  Annexes : [Liste des pièces jointes]"
            ),
        }
        return structures.get(type_doc, structures["dossier"])
