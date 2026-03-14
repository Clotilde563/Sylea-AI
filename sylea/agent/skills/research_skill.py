"""
Skill Recherche de l'agent Syléa.AI.

Capacités :
  - Synthétiser les axes de recherche sur un sujet
  - Proposer les sources pertinentes à consulter
  - Structurer une note de recherche
  - Identifier les questions clés à investiguer

Note : les recherches sont simulées (aucun accès réel au web).
"""

from __future__ import annotations

from datetime import datetime


class SkillRecherche:
    """
    Skill de recherche d'informations et de synthèse documentaire.

    Génère un plan de recherche structuré avec les axes à explorer,
    les sources recommandées et les questions clés à investiguer.
    """

    description = "Recherche d'informations, synthèse documentaire et analyse concurrentielle"

    def executer(self, instruction: str) -> str:
        """
        Génère un plan de recherche et une synthèse préliminaire.

        Args:
            instruction: Instruction validée décrivant le sujet de recherche

        Returns:
            Rapport de recherche structuré
        """
        sujet = self._extraire_sujet(instruction)
        type_recherche = self._detecter_type(instruction)
        axes = self._generer_axes(type_recherche, instruction)
        sources = self._recommander_sources(type_recherche, instruction)
        questions = self._generer_questions(instruction)

        rapport = f"""RAPPORT DE RECHERCHE -- {datetime.now().strftime('%d/%m/%Y a %H:%M')}
{'=' * 55}

  SUJET     : {sujet}
  TYPE      : {type_recherche.upper()}

{'-' * 55}
  AXES DE RECHERCHE
{'-' * 55}
{axes}

{'-' * 55}
  SOURCES RECOMMANDEES
{'-' * 55}
{sources}

{'-' * 55}
  QUESTIONS CLES A INVESTIGUER
{'-' * 55}
{questions}

{'=' * 55}
[!] Synthese preliminaire -- A approfondir avec des sources reelles
{'=' * 55}"""
        return rapport

    # ── Méthodes internes ────────────────────────────────────────────────────

    @staticmethod
    def _extraire_sujet(instruction: str) -> str:
        """Extrait le sujet principal de l'instruction."""
        mots = instruction.split()
        # Ignorer les premiers mots (verbe + compléments)
        mots_significatifs = [m for m in mots[2:] if len(m) > 3]
        if mots_significatifs:
            return " ".join(mots_significatifs[:5])
        return instruction[:60]

    @staticmethod
    def _detecter_type(instruction: str) -> str:
        """Détecte le type de recherche demandée."""
        inst = instruction.lower()
        if any(m in inst for m in ["concurrent", "marché", "secteur", "industrie"]):
            return "analyse concurrentielle"
        elif any(m in inst for m in ["candidat", "recrutement", "profil"]):
            return "recherche de profils"
        elif any(m in inst for m in ["fournisseur", "prestataire", "partenaire"]):
            return "recherche de fournisseurs"
        elif any(m in inst for m in ["réglementation", "loi", "juridique", "légal"]):
            return "recherche juridique"
        elif any(m in inst for m in ["technologie", "solution", "outil", "logiciel"]):
            return "veille technologique"
        return "recherche documentaire"

    @staticmethod
    def _generer_axes(type_recherche: str, instruction: str) -> str:
        """Génère les axes de recherche selon le type."""
        axes_par_type = {
            "analyse concurrentielle": [
                "1. Identification des acteurs principaux du marche",
                "2. Analyse des parts de marche et positionnement",
                "3. Comparaison des offres produits/services",
                "4. Analyse des strategies de prix",
                "5. Points forts et faiblesses de chaque concurrent",
            ],
            "recherche de profils": [
                "1. Definition du profil ideal (competences, experiences)",
                "2. Canaux de recrutement adaptes",
                "3. Analyse du marche des candidats",
                "4. Benchmarks de remuneration",
                "5. Recommandations de processus de selection",
            ],
            "recherche de fournisseurs": [
                "1. Cartographie des fournisseurs potentiels",
                "2. Criteres d'evaluation (prix, delai, qualite)",
                "3. References et avis clients",
                "4. Conditions contractuelles types",
                "5. Risques fournisseurs a anticiper",
            ],
            "recherche juridique": [
                "1. Identification du cadre legal applicable",
                "2. Textes de reference (lois, decrets, jurisprudence)",
                "3. Obligations et droits des parties",
                "4. Risques de non-conformite",
                "5. Recommandations pour la mise en conformite",
            ],
            "veille technologique": [
                "1. Solutions existantes sur le marche",
                "2. Comparaison fonctionnelle des outils",
                "3. Analyse des couts (licences, implementation)",
                "4. Retours d'experience d'utilisateurs",
                "5. Tendances d'evolution a 2 ans",
            ],
            "recherche documentaire": [
                "1. Definition du perimetre de recherche",
                "2. Identification des sources primaires",
                "3. Collecte et tri des informations",
                "4. Synthese des donnees collectees",
                "5. Validation et verification des sources",
            ],
        }
        axes = axes_par_type.get(type_recherche, axes_par_type["recherche documentaire"])
        return "\n".join(f"  {axe}" for axe in axes)

    @staticmethod
    def _recommander_sources(type_recherche: str, instruction: str) -> str:
        """Recommande des types de sources adaptés à la recherche."""
        sources_communes = [
            "  • Bases de données professionnelles (LinkedIn, Kompass, Societe.com)",
            "  • Sites officiels des organisations concernées",
            "  • Rapports sectoriels (INSEE, Xerfi, Statista)",
        ]
        sources_specifiques = {
            "analyse concurrentielle": [
                "  • Sites web et réseaux sociaux des concurrents",
                "  • Avis clients (Trustpilot, G2, Capterra)",
                "  • Presse spécialisée et études de marché",
            ],
            "recherche juridique": [
                "  • Légifrance.gouv.fr (textes officiels français)",
                "  • EUR-Lex (réglementations européennes)",
                "  • Jurisprudence : Cour de cassation, Conseil d'État",
            ],
            "veille technologique": [
                "  • Product Hunt, G2, Capterra (comparatifs logiciels)",
                "  • GitHub (projets open source)",
                "  • TechCrunch, Wired, MIT Technology Review",
            ],
        }
        spec = sources_specifiques.get(type_recherche, [])
        return "\n".join(sources_communes + spec)

    @staticmethod
    def _generer_questions(instruction: str) -> str:
        """Génère des questions clés à investiguer."""
        questions = [
            "  Q1 : Quels sont les acteurs ou éléments incontournables du sujet ?",
            "  Q2 : Quelles sont les tendances actuelles et à venir ?",
            "  Q3 : Quels sont les points de différenciation possibles ?",
            "  Q4 : Quels sont les risques ou obstacles principaux ?",
            "  Q5 : Quel est le niveau de maturité du sujet sur le marché ?",
        ]
        return "\n".join(questions)
