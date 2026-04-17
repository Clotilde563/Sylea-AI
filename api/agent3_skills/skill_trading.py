"""
Skill TradingAnalysis — Analyse de marche et trading.

Utilise la recherche web pour recuperer des donnees de marche recentes
puis genere une analyse structuree via Claude.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from api.agent3_skills.base import Skill, SkillResult, SkillContext

logger = logging.getLogger("sylea.agent3.skills.trading")


ANALYSIS_SYSTEM = """Tu es un analyste de marche senior. Analyse les donnees fournies et genere un rapport
structure en francais. Sois factuel, concis, cite les sources.

Structure du rapport :
1. RESUME (2-3 phrases)
2. NIVEAUX CLES (support/resistance)
3. TENDANCE (court/moyen/long terme)
4. CATALYSEURS (news, events)
5. RISQUES

Maximum 300 mots. Pas de conseil d'investissement direct — formule comme "analyse technique suggere" ou "le consensus est".
"""


class TradingAnalysisSkill(Skill):
    name = "trading_analysis"
    description = "Analyse de marche : prix, tendances, niveaux cles, news financieres"
    category = "finance"
    triggers = [
        "analyse", "trading", "bitcoin", "btc", "ethereum", "eth",
        "cours", "prix", "marche", "bourse", "action",
        "sp500", "s&p", "nasdaq", "cac40", "forex",
        "support", "resistance", "tendance", "trend",
        "bullish", "bearish", "achat", "vente",
        "crypto", "altcoin", "defi",
        "saxo", "tradingview", "binance",
    ]
    required_tools = ["web_search"]
    is_async_heavy = True

    def _extract_asset(self, instruction: str) -> str:
        """Extrait le symbole / nom de l'actif depuis l'instruction."""
        # Patterns courants
        patterns = [
            r'\b(BTC|ETH|SOL|ADA|XRP|BNB|DOGE|DOT|AVAX|MATIC|LINK)\b',
            r'\b(bitcoin|ethereum|solana|cardano|ripple)\b',
            r'\b(SP500|S&P\s*500|NASDAQ|CAC\s*40|DAX|NIKKEI)\b',
            r'\b(EUR/?USD|GBP/?USD|USD/?JPY|USD/?CHF)\b',
            r'\b(AAPL|MSFT|GOOGL|AMZN|META|TSLA|NVDA)\b',
            r'\b(or|gold|argent|silver|petrole|oil|WTI|brent)\b',
        ]
        text_upper = instruction.upper()
        for pat in patterns:
            m = re.search(pat, text_upper)
            if m:
                return m.group(1)
        # Fallback : prendre les mots apres "analyse" ou "cours"
        m = re.search(r'(?:analyse|cours|prix|trading)\s+(?:de\s+)?(\w+)', instruction, re.IGNORECASE)
        if m:
            return m.group(1)
        return "BTC"

    async def execute(
        self,
        instruction: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        from api.openclaw_bridge import openclaw_web_search

        asset = self._extract_asset(instruction)
        session_key = context.session_key if context else ""

        # 1. Recherche de donnees recentes
        queries = [
            f"{asset} price analysis today",
            f"{asset} technical analysis support resistance",
        ]
        all_results = []
        for q in queries:
            try:
                sr = await openclaw_web_search(query=q, session_key=session_key, max_results=5)
                if sr.get("success") and sr.get("results"):
                    all_results.extend(sr["results"])
            except Exception as e:
                logger.debug(f"Trading search failed for '{q}': {e}")

        if not all_results:
            return SkillResult(
                success=False,
                error=f"Impossible de recuperer des donnees pour {asset}",
                data={"asset": asset},
            )

        # 2. Formater le contexte pour Claude
        snippets = []
        for r in all_results[:10]:
            title = r.get("title", "")
            snippet = r.get("snippet", r.get("description", ""))[:250]
            snippets.append(f"- {title}: {snippet}")
        market_data = "\n".join(snippets)

        # 3. Analyse via Claude
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return SkillResult(
                success=True,
                content=f"Donnees brutes pour {asset}:\n{market_data}",
                data={"asset": asset, "raw_count": len(all_results), "analyzed": False},
            )

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            prompt = (
                f"Actif : {asset}\n"
                f"Demande utilisateur : {instruction}\n\n"
                f"Donnees de marche recentes :\n{market_data}\n\n"
                "Genere l'analyse structuree."
            )
            resp = await asyncio.to_thread(
                client.messages.create,
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=[{
                    "type": "text",
                    "text": ANALYSIS_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            analysis = "".join(b.text for b in resp.content if hasattr(b, "text"))
        except Exception as e:
            logger.warning(f"Trading analysis LLM failed: {e}")
            analysis = f"Donnees pour {asset} (synthese non disponible):\n{market_data}"

        return SkillResult(
            success=True,
            content=analysis,
            data={
                "asset": asset,
                "raw_count": len(all_results),
                "analyzed": True,
                "sources": [r.get("url", "") for r in all_results[:5] if r.get("url")],
            },
        )
