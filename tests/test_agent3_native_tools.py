"""
Tests pour la boucle agentique native (api/agent3_native_tools.py).

Ces tests verifient :
  - La construction des tool schemas Anthropic
  - La boucle agentique multi-tours avec tool_use/tool_result
  - Le feedback d'erreur au LLM via is_error=True
  - La limite max_turns et les terminaisons propres
  - Le comptage des tokens et actions executees
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterator

import pytest

from api.agent3_native_tools import (
    AgenticLoop,
    MockExecutor,
    build_tool_schemas,
    compact_messages,
    tool_name_to_action_type,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fake Anthropic client — simule messages.create en retournant des reponses
# scriptes. Permet de tester le flow de la boucle sans appel reseau.
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class _Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict | None = None


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class _Response:
    content: list[_Block]
    stop_reason: str
    usage: _Usage


class _FakeMessagesAPI:
    def __init__(self, scripted_responses: list[_Response]):
        self._responses = scripted_responses
        self._idx = 0
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs):
        # Deep-copy messages pour figer l'etat au moment de l'appel (sinon la liste
        # est mutee par les tours suivants et casse les assertions des tests).
        import copy
        self.calls.append({**kwargs, "messages": copy.deepcopy(kwargs.get("messages", []))})
        if self._idx >= len(self._responses):
            raise RuntimeError(f"FakeClient: aucune reponse scriptee pour l'appel {self._idx + 1}")
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


class FakeAnthropicClient:
    def __init__(self, scripted_responses: list[_Response]):
        self.messages = _FakeMessagesAPI(scripted_responses)


# Helpers pour construire des reponses scriptees facilement.

def _text_response(text: str, stop_reason: str = "end_turn") -> _Response:
    return _Response(
        content=[_Block(type="text", text=text)],
        stop_reason=stop_reason,
        usage=_Usage(),
    )


def _tool_use_response(
    tool_name: str,
    tool_input: dict,
    tool_id: str = "tu_1",
    preamble_text: str = "",
) -> _Response:
    blocks: list[_Block] = []
    if preamble_text:
        blocks.append(_Block(type="text", text=preamble_text))
    blocks.append(_Block(
        type="tool_use",
        id=tool_id,
        name=tool_name,
        input=tool_input,
    ))
    return _Response(
        content=blocks,
        stop_reason="tool_use",
        usage=_Usage(),
    )


def _multi_tool_response(tool_calls: list[tuple[str, dict, str]]) -> _Response:
    """Reponse avec plusieurs tool_use dans le meme tour."""
    blocks = [
        _Block(type="tool_use", id=tid, name=tname, input=tinput)
        for tname, tinput, tid in tool_calls
    ]
    return _Response(
        content=blocks,
        stop_reason="tool_use",
        usage=_Usage(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Tool schemas
# ══════════════════════════════════════════════════════════════════════════════


class TestToolSchemas:
    def test_build_returns_list(self):
        tools = build_tool_schemas()
        assert isinstance(tools, list)
        assert len(tools) > 10

    def test_each_tool_has_required_fields(self):
        tools = build_tool_schemas()
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "input_schema" in t
            assert t["input_schema"].get("type") == "object"

    def test_names_are_snake_case(self):
        tools = build_tool_schemas()
        for t in tools:
            assert t["name"] == t["name"].lower()
            assert " " not in t["name"]

    def test_filter_enabled_actions(self):
        tools = build_tool_schemas(enabled_actions={"SEARCH", "MEMORY"})
        names = {t["name"] for t in tools}
        assert names == {"search", "memory"}

    def test_email_is_present(self):
        tools = build_tool_schemas()
        names = {t["name"] for t in tools}
        assert "email" in names

    def test_computer_use_is_present(self):
        tools = build_tool_schemas()
        names = {t["name"] for t in tools}
        assert "computer_use" in names

    def test_email_required_fields(self):
        tools = build_tool_schemas()
        email_tool = next(t for t in tools if t["name"] == "email")
        required = email_tool["input_schema"].get("required", [])
        assert set(required) == {"to", "subject", "body"}


class TestNameConversion:
    def test_snake_to_upper(self):
        assert tool_name_to_action_type("email") == "EMAIL"
        assert tool_name_to_action_type("computer_use") == "COMPUTER_USE"
        assert tool_name_to_action_type("calendar_event") == "CALENDAR_EVENT"


# ══════════════════════════════════════════════════════════════════════════════
# Boucle agentique
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestAgenticLoop:
    async def test_single_turn_no_tools_ends_immediately(self):
        """Un LLM qui repond du texte sans tool doit terminer en 1 tour."""
        client = FakeAnthropicClient([_text_response("Bonjour, voici ma reponse.")])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=5,
        )

        events = []
        async for ev in loop.run(user_message="Salut"):
            events.append(ev)

        assert loop.result is not None
        assert loop.result.turns == 1
        assert loop.result.stop_reason == "end_turn"
        assert "Bonjour" in loop.result.final_text
        assert len(loop.result.actions_executed) == 0
        # done event
        assert events[-1].type == "done"

    async def test_two_turns_with_tool_use(self):
        """LLM -> tool_use -> tool_result -> LLM -> texte final."""
        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "Ada Lovelace"}, tool_id="tu_1"),
            _text_response("Ada Lovelace etait une mathematicienne du XIXe siecle."),
        ])
        executor = MockExecutor(responses={
            "SEARCH": {"content": "Resultats: Ada Lovelace, pionniere de l'informatique.", "is_error": False, "raw": {}}
        })
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=executor,
            max_turns=5,
        )
        events = []
        async for ev in loop.run(user_message="Qui est Ada Lovelace ?"):
            events.append(ev)

        assert loop.result.turns == 2
        assert loop.result.stop_reason == "end_turn"
        assert len(loop.result.actions_executed) == 1
        assert loop.result.actions_executed[0]["action_type"] == "SEARCH"
        assert loop.result.actions_executed[0]["input"] == {"query": "Ada Lovelace"}
        # L'executor a bien ete appele
        assert executor.calls == [("SEARCH", {"query": "Ada Lovelace"})]
        # Un event tool_use et un event tool_result
        types = [e.type for e in events]
        assert types.count("tool_use") == 1
        assert types.count("tool_result") == 1

    async def test_error_feeds_back_to_llm(self):
        """Si un tool echoue (is_error=True), l'erreur est mise dans le tool_result
        et le LLM peut retry/adapter au tour suivant."""
        client = FakeAnthropicClient([
            _tool_use_response("email", {"to": "bad", "subject": "x", "body": "y"}, tool_id="tu_1"),
            _tool_use_response("email", {"to": "good@example.com", "subject": "x", "body": "y"}, tool_id="tu_2"),
            _text_response("Email envoye apres correction."),
        ])
        # Premier appel EMAIL echoue, deuxieme reussit.
        call_count = {"n": 0}

        class _AdaptiveExecutor:
            calls: list[tuple[str, dict]] = []

            async def execute(self, action_type: str, action_input: dict) -> dict:
                self.calls.append((action_type, action_input))
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return {"content": "Erreur: adresse invalide 'bad'", "is_error": True, "raw": {}}
                return {"content": "Email envoye.", "is_error": False, "raw": {}}

        executor = _AdaptiveExecutor()
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=executor,
            max_turns=5,
            # EMAIL est destructive : on pre-approuve les 2 IDs pour tester
            # le feedback d'erreur sans rentrer dans le flow de confirmation.
            pre_approved_tool_ids={"tu_1", "tu_2"},
        )
        async for _ in loop.run(user_message="envoie un email"):
            pass

        assert loop.result.turns == 3
        assert loop.result.stop_reason == "end_turn"
        assert len(loop.result.actions_executed) == 2
        # Le deuxieme appel a recu une adresse valide (preuve que le LLM a adapte)
        assert loop.result.actions_executed[1]["input"]["to"] == "good@example.com"
        # Verifier que l'API Anthropic a recu le tool_result avec is_error=True au 2eme appel
        second_call_messages = client.messages.calls[1]["messages"]
        tool_result_msg = second_call_messages[-1]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["is_error"] is True

    async def test_max_turns_reached(self):
        """La boucle s'arrete a max_turns meme si le LLM continue a tool_use."""
        # 10 reponses tool_use d'affilee
        responses = [_tool_use_response("search", {"query": str(i)}, tool_id=f"tu_{i}") for i in range(10)]
        client = FakeAnthropicClient(responses)
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=MockExecutor(),
            max_turns=3,
        )
        events = []
        async for ev in loop.run(user_message="loop forever"):
            events.append(ev)

        assert loop.result.turns == 3
        # max_turns atteint -> error msg
        assert loop.result.error is not None and "Max turns" in loop.result.error
        # On a execute 3 tools (1 par tour)
        assert len(loop.result.actions_executed) == 3

    async def test_parallel_tool_calls_in_one_turn(self):
        """Un meme tour peut contenir plusieurs tool_use — tous doivent etre executes
        et leurs results groupes dans le message user suivant."""
        client = FakeAnthropicClient([
            _multi_tool_response([
                ("search", {"query": "A"}, "tu_a"),
                ("search", {"query": "B"}, "tu_b"),
                ("search", {"query": "C"}, "tu_c"),
            ]),
            _text_response("Synthese des 3 recherches."),
        ])
        executor = MockExecutor(responses={
            "SEARCH": {"content": "result", "is_error": False, "raw": {}}
        })
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=executor,
            max_turns=5,
        )
        async for _ in loop.run(user_message="go"):
            pass

        assert loop.result.turns == 2
        # 3 actions executees en 1 tour
        assert len(loop.result.actions_executed) == 3
        # 3 tool_results groupes dans un seul message user
        second_call_messages = client.messages.calls[1]["messages"]
        last_msg = second_call_messages[-1]
        assert last_msg["role"] == "user"
        assert len(last_msg["content"]) == 3
        assert all(tr["type"] == "tool_result" for tr in last_msg["content"])

    async def test_llm_call_failure_breaks_loop(self):
        """Si client.messages.create leve, la boucle emet un error event et sort proprement."""

        class _BrokenClient:
            class messages:
                @staticmethod
                async def create(**kwargs):
                    raise RuntimeError("API down")

        loop = AgenticLoop(
            client=_BrokenClient(),
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=MockExecutor(),
            max_turns=5,
        )
        events = []
        async for ev in loop.run(user_message="hi"):
            events.append(ev)

        assert loop.result.error is not None and "API down" in loop.result.error
        assert any(e.type == "error" for e in events)

    async def test_executor_crash_is_reported_as_tool_error(self):
        """Si l'executor crashe, on remonte l'exception au LLM via is_error=True
        plutot que de casser la boucle."""
        class _CrashingExecutor:
            async def execute(self, action_type, action_input):
                raise ValueError("handler boom")

        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "x"}, tool_id="tu_1"),
            _text_response("Desole, ca a echoue."),
        ])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=_CrashingExecutor(),
            max_turns=5,
        )
        async for _ in loop.run(user_message="go"):
            pass

        # La boucle ne doit PAS crasher
        assert loop.result.turns == 2
        assert loop.result.stop_reason == "end_turn"
        # L'action a ete loggee avec is_error
        assert len(loop.result.actions_executed) == 1
        assert loop.result.actions_executed[0]["result"]["is_error"] is True

    async def test_destructive_action_pauses_loop_with_confirmation_needed(self):
        """Un tool_use pour une action destructive (ex. EMAIL) doit stopper la boucle
        et emettre un event confirmation_needed, sans executer l'action."""
        # email -> action_type EMAIL (destructive)
        client = FakeAnthropicClient([
            _tool_use_response("email", {
                "to": "a@b.c", "subject": "x", "body": "y",
            }, tool_id="tu_dest_1"),
        ])

        class _NeverCalled:
            async def execute(self, *a, **kw):
                raise AssertionError("L'executor ne doit PAS etre appele pour une action destructive non confirmee")

        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=_NeverCalled(),
            max_turns=5,
        )
        events = []
        async for ev in loop.run(user_message="envoie un mail"):
            events.append(ev)

        # Un event confirmation_needed doit etre emis
        confirm_events = [e for e in events if e.type == "confirmation_needed"]
        assert len(confirm_events) == 1
        assert confirm_events[0].data["action_type"] == "EMAIL"
        assert confirm_events[0].data["tool_use_id"] == "tu_dest_1"

        # Et l'etat pending_confirmation doit etre renseigne
        assert loop.pending_confirmation is not None
        assert loop.pending_confirmation["pending_tool_uses"][0]["action_type"] == "EMAIL"
        assert loop.pending_confirmation["turn"] == 1

        # stop_reason doit etre awaiting_confirmation
        assert loop.result.stop_reason == "awaiting_confirmation"
        # Aucune action n'a ete executee
        assert len(loop.result.actions_executed) == 0

    async def test_pre_approved_destructive_executes_normally(self):
        """Si le tool_use_id est dans pre_approved_tool_ids, l'action destructive s'execute."""
        client = FakeAnthropicClient([
            _tool_use_response("email", {
                "to": "a@b.c", "subject": "x", "body": "y",
            }, tool_id="tu_approved"),
            _text_response("Email envoye."),
        ])
        executor = MockExecutor(responses={
            "EMAIL": {"content": "Email envoye avec succes", "is_error": False, "raw": {}}
        })
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=executor,
            max_turns=5,
            pre_approved_tool_ids={"tu_approved"},
        )
        events = []
        async for ev in loop.run(user_message="envoie un mail (approuve)"):
            events.append(ev)

        # Pas de confirmation_needed car pre-approuve
        assert not any(e.type == "confirmation_needed" for e in events)
        # L'action a bien ete executee
        assert len(loop.result.actions_executed) == 1
        assert loop.result.actions_executed[0]["action_type"] == "EMAIL"
        assert loop.result.stop_reason == "end_turn"

    async def test_resume_with_approval_executes_action(self):
        """Apres pause pour confirmation, resume_from_confirmation(approvals={id: True})
        execute l'action et continue la boucle jusqu'a end_turn."""
        # Tour 1 : tool_use email (destructive -> pause)
        client = FakeAnthropicClient([
            _tool_use_response("email", {"to": "a@b.c", "subject": "Hi", "body": "Bonjour"}, tool_id="tu_resume_1"),
            # Tour 2 (apres resume) : texte final
            _text_response("Email envoye."),
        ])
        executor = MockExecutor(responses={
            "EMAIL": {"content": "Email envoye via SMTP", "is_error": False, "raw": {}},
        })
        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=build_tool_schemas(), executor=executor, max_turns=5,
        )
        async for _ in loop.run(user_message="envoie un mail"):
            pass
        assert loop.result.stop_reason == "awaiting_confirmation"
        pending = loop.pending_confirmation
        assert pending is not None

        # Resume avec approbation
        events_resume = []
        async for ev in loop.resume_from_confirmation(pending, {"tu_resume_1": True}):
            events_resume.append(ev)

        # Verifier que l'action a ete executee
        assert len(loop.result.actions_executed) == 1
        assert loop.result.actions_executed[0]["action_type"] == "EMAIL"
        assert loop.result.actions_executed[0]["user_approved"] is True
        assert loop.result.actions_executed[0]["result"]["is_error"] is False
        assert loop.result.stop_reason == "end_turn"
        assert "Email envoye" in loop.result.final_text
        assert loop.pending_confirmation is None  # reset apres traitement

    async def test_resume_with_denial_feeds_refusal_to_llm(self):
        """Si l'utilisateur refuse, un tool_result is_error=True est envoye au LLM
        qui doit pouvoir proposer une alternative."""
        client = FakeAnthropicClient([
            _tool_use_response("email", {"to": "a@b.c", "subject": "x", "body": "y"}, tool_id="tu_deny"),
            # Apres refus, le LLM doit juste expliquer et ne pas re-tenter
            _text_response("D'accord, je n'envoie pas l'email. Veux-tu juste que je t'aide a le rediger ?"),
        ])

        class _ShouldNotCall:
            async def execute(self, *a, **kw):
                raise AssertionError("Ne doit PAS etre execute apres refus")

        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=build_tool_schemas(), executor=_ShouldNotCall(), max_turns=5,
        )
        async for _ in loop.run(user_message="envoie"):
            pass
        assert loop.result.stop_reason == "awaiting_confirmation"

        async for _ in loop.resume_from_confirmation(loop.pending_confirmation, {"tu_deny": False}):
            pass

        # Action loggee avec approval=False et is_error=True
        assert loop.result.actions_executed[0]["user_approved"] is False
        assert loop.result.actions_executed[0]["result"]["is_error"] is True
        assert "refuse" in loop.result.actions_executed[0]["result"]["content"].lower()
        # Le LLM a pu terminer son explication
        assert loop.result.stop_reason == "end_turn"

    async def test_non_destructive_action_not_gated(self):
        """SEARCH / MEMORY_SEARCH / FILE_READ ne doivent jamais declencher de confirmation."""
        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "x"}, tool_id="tu_safe"),
            _text_response("ok"),
        ])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=MockExecutor(),
            max_turns=5,
        )
        events = []
        async for ev in loop.run(user_message="cherche"):
            events.append(ev)

        assert not any(e.type == "confirmation_needed" for e in events)
        assert loop.pending_confirmation is None
        assert loop.result.stop_reason == "end_turn"

    async def test_token_counting_across_turns(self):
        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "x"}, tool_id="tu_1"),
            _text_response("done"),
        ])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(),
            executor=MockExecutor(),
            max_turns=5,
        )
        async for _ in loop.run(user_message="go"):
            pass

        # Chaque _Usage par defaut = 100 input + 50 output. 2 tours -> 200 + 100.
        assert loop.result.total_input_tokens == 200
        assert loop.result.total_output_tokens == 100


# ══════════════════════════════════════════════════════════════════════════════
# Compaction automatique du contexte
# ══════════════════════════════════════════════════════════════════════════════


class TestCompactMessages:
    def test_short_history_not_compacted(self):
        """Moins de `keep_last_n` messages -> renvoyes intacts, 0 char economise."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        new, saved = compact_messages(msgs, keep_last_n=4)
        assert new == msgs
        assert saved == 0

    def test_tool_result_truncation(self):
        """Les anciens tool_results longs sont tronques, les recents intacts."""
        long_str = "x" * 2000
        recent_long = "y" * 2000
        msgs = [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"q": "a"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": long_str},
                ],
            },
            {"role": "assistant", "content": "ok continuing"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu_2", "name": "search", "input": {"q": "b"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_2", "content": recent_long},
                ],
            },
        ]
        new, saved = compact_messages(msgs, keep_last_n=3, max_tool_result_chars=100)

        # Ancien tool_result (index 2) tronque
        old_tr = new[2]["content"][0]
        assert len(old_tr["content"]) < 2000
        assert "tronque" in old_tr["content"].lower()

        # Recent tool_result (index 5) intact
        recent_tr = new[5]["content"][0]
        assert recent_tr["content"] == recent_long

        # tool_use IDs preserves pour l'appairage
        assert new[1]["content"][0]["id"] == "tu_1"
        assert new[4]["content"][0]["id"] == "tu_2"

        # Des caracteres ont ete economises
        assert saved > 1000

    def test_text_messages_not_modified(self):
        """Les messages texte simples ne sont pas touches."""
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello, long response " * 50},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "you're welcome"},
            {"role": "user", "content": "bye"},
        ]
        new, saved = compact_messages(msgs, keep_last_n=2)
        # Aucun tool_result -> rien a tronquer
        assert saved == 0
        # Contenu preserve
        for original, new_msg in zip(msgs, new):
            assert original["content"] == new_msg["content"]


@pytest.mark.asyncio
class TestAgenticLoopCompaction:
    async def test_auto_compacts_when_threshold_exceeded(self):
        """Si total_input_tokens depasse le seuil, la boucle compacte les
        anciens tool_results et emet un event 'context_compacted'."""
        # Scenario : 3 tours. Chaque usage = 100 input. Seuil=150 -> declenche
        # avant le 2e tour.
        big_tool_content = "A" * 5000  # sera tronque
        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "alpha"}, tool_id="tu_1"),
            _tool_use_response("search", {"query": "beta"}, tool_id="tu_2"),
            _tool_use_response("search", {"query": "gamma"}, tool_id="tu_3"),
            _text_response("done"),
        ])

        class _BigExecutor:
            async def execute(self, action_type, action_input):
                return {"content": big_tool_content, "is_error": False, "raw": {}}

        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=_BigExecutor(),
            max_turns=6,
            auto_compact_threshold=150,  # declenchera tres tot
        )

        events: list[tuple[str, dict]] = []
        async for ev in loop.run(user_message="go"):
            events.append((ev.type, ev.data))

        compaction_events = [e for e in events if e[0] == "context_compacted"]
        assert len(compaction_events) == 1, "Exactement 1 compaction par run"
        assert compaction_events[0][1]["chars_saved"] > 0
        assert compaction_events[0][1]["threshold_tokens"] == 150

        # Verifie que le flag est bien leve
        assert loop._compacted_once is True

    async def test_no_compaction_below_threshold(self):
        """Si on reste sous le seuil, pas de compaction."""
        client = FakeAnthropicClient([_text_response("reponse courte.")])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            auto_compact_threshold=100_000,
        )
        events = []
        async for ev in loop.run(user_message="bonjour"):
            events.append(ev.type)
        assert "context_compacted" not in events
        assert loop._compacted_once is False

    async def test_llm_retries_on_transient_error(self):
        """Un RateLimitError transitoire -> retry -> succes sans casser la boucle."""
        class _RateLimitError(Exception):
            status_code = 429

        call_count = {"n": 0}

        class _FlakyAPI:
            async def create(self, **kwargs):
                call_count["n"] += 1
                if call_count["n"] < 3:
                    raise _RateLimitError("throttled")
                return _Response(
                    content=[_Block(type="text", text="enfin repondu.")],
                    stop_reason="end_turn",
                    usage=_Usage(),
                )

        class _FlakyClient:
            def __init__(self):
                self.messages = _FlakyAPI()

        loop = AgenticLoop(
            client=_FlakyClient(),
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            max_llm_retries=4,
            retry_backoff_base_s=0.01,  # accelere le test
        )
        events = []
        async for ev in loop.run(user_message="go"):
            events.append(ev.type)
        assert loop.result is not None
        assert loop.result.final_text == "enfin repondu."
        assert call_count["n"] == 3  # 2 echecs + 1 succes

    async def test_llm_retry_gives_up_after_max_attempts(self):
        """Epuisement des retries -> propagation de l'erreur dans l'event 'error'."""
        class _RateLimitError(Exception):
            status_code = 429

        class _AlwaysFailingAPI:
            async def create(self, **kwargs):
                raise _RateLimitError("still throttled")

        class _AlwaysFailingClient:
            def __init__(self):
                self.messages = _AlwaysFailingAPI()

        loop = AgenticLoop(
            client=_AlwaysFailingClient(),
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            max_llm_retries=2,
            retry_backoff_base_s=0.01,
        )
        errored = False
        async for ev in loop.run(user_message="go"):
            if ev.type == "error":
                errored = True
        assert errored

    async def test_non_transient_error_not_retried(self):
        """Une AuthenticationError (401) -> pas de retry, echec immediat."""
        class _AuthError(Exception):
            status_code = 401

        call_count = {"n": 0}

        class _AuthFailingAPI:
            async def create(self, **kwargs):
                call_count["n"] += 1
                raise _AuthError("bad api key")

        class _AuthFailingClient:
            def __init__(self):
                self.messages = _AuthFailingAPI()

        loop = AgenticLoop(
            client=_AuthFailingClient(),
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            max_llm_retries=5,
            retry_backoff_base_s=0.01,
        )
        async for _ in loop.run(user_message="go"):
            pass
        # 1 seul appel (pas de retry sur auth error)
        assert call_count["n"] == 1

    async def test_tool_timeout_injected_as_error(self):
        """Un executor qui pend indefiniment -> timeout -> erreur feed au LLM."""
        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "x"}, tool_id="tu_1"),
            _text_response("ok j'arrete."),
        ])

        class _HangingExecutor:
            async def execute(self, action_type, action_input):
                await asyncio.sleep(10)  # simule un hang
                return {"content": "never reached", "is_error": False, "raw": {}}

        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=_HangingExecutor(),
            max_turns=3,
            tool_timeout_s=0.1,  # timeout tres court pour accelerer le test
        )
        timeout_reported = False
        async for ev in loop.run(user_message="go"):
            if ev.type == "tool_result" and ev.data.get("is_error"):
                if "delai" in ev.data.get("content_preview", "").lower():
                    timeout_reported = True
        assert timeout_reported
        # La boucle continue apres le timeout : un 2e tour est fait
        assert loop.result.turns >= 2

    async def test_compaction_happens_at_most_once(self):
        """Meme si le seuil reste depasse, on ne compacte qu'une fois par run."""
        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "a"}, tool_id="tu_a"),
            _tool_use_response("search", {"query": "b"}, tool_id="tu_b"),
            _tool_use_response("search", {"query": "c"}, tool_id="tu_c"),
            _text_response("done"),
        ])

        class _Exec:
            async def execute(self, action_type, action_input):
                return {"content": "R" * 5000, "is_error": False, "raw": {}}

        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=_Exec(),
            max_turns=6,
            auto_compact_threshold=50,
        )
        count = 0
        async for ev in loop.run(user_message="go"):
            if ev.type == "context_compacted":
                count += 1
        assert count == 1


# ══════════════════════════════════════════════════════════════════════════════
# Streaming + extended thinking + interrupt
# ══════════════════════════════════════════════════════════════════════════════


# Fakes pour le mode streaming : reproduisent la shape des events du SDK
# Anthropic (content_block_delta, text_delta, thinking_delta).

class _FakeDelta:
    def __init__(self, dtype: str, **kw):
        self.type = dtype
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeStreamEvent:
    def __init__(self, etype: str, delta: _FakeDelta | None = None):
        self.type = etype
        self.delta = delta


class _FakeStream:
    """Simule l'async iteration + get_final_message du SDK."""
    def __init__(self, events: list[_FakeStreamEvent], final_message):
        self._events = list(events)
        self._final = final_message

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def get_final_message(self):
        return self._final


class _FakeStreamManager:
    """Async context manager comme retourne par client.messages.stream()."""
    def __init__(self, events, final_message):
        self._events = events
        self._final = final_message
        self.kwargs_captured: dict | None = None

    async def __aenter__(self):
        return _FakeStream(self._events, self._final)

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _StreamingMessagesAPI:
    """Fake messages API supportant `.stream(**kwargs)` en plus de `.create()`."""
    def __init__(self, scripted_streams: list[tuple[list, Any]], scripted_responses=None):
        # scripted_streams : liste de (events, final_message) pour chaque tour
        self._streams = list(scripted_streams)
        self._responses = list(scripted_responses or [])
        self.stream_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        if not self._streams:
            raise RuntimeError("FakeStreamingClient: aucun stream scripte")
        events, final = self._streams.pop(0)
        return _FakeStreamManager(events, final)

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("FakeStreamingClient: aucune reponse create scriptee")
        return self._responses.pop(0)


class FakeStreamingClient:
    def __init__(self, scripted_streams, scripted_responses=None):
        self.messages = _StreamingMessagesAPI(scripted_streams, scripted_responses)


def _make_stream_events(text: str, thinking: str = "") -> tuple[list, Any]:
    """Construit une sequence d'events (tokens + thinking) + un final message."""
    events: list[_FakeStreamEvent] = []
    if thinking:
        # Chunks de ~10 chars pour simuler le streaming granulaire
        for i in range(0, len(thinking), 10):
            events.append(_FakeStreamEvent(
                "content_block_delta",
                _FakeDelta("thinking_delta", thinking=thinking[i:i + 10]),
            ))
    if text:
        for i in range(0, len(text), 5):
            events.append(_FakeStreamEvent(
                "content_block_delta",
                _FakeDelta("text_delta", text=text[i:i + 5]),
            ))
    # Final message : meme shape que _Response
    blocks = []
    if thinking:
        blocks.append(_Block(type="thinking"))
        blocks[-1].thinking = thinking
        blocks[-1].signature = "sig_fake"
    if text:
        blocks.append(_Block(type="text", text=text))
    final = _Response(content=blocks, stop_reason="end_turn", usage=_Usage())
    return events, final


@pytest.mark.asyncio
class TestStreaming:
    async def test_token_deltas_are_emitted_in_order(self):
        """Chaque fragment text_delta doit etre relaye en event token_delta."""
        events, final = _make_stream_events("Bonjour Sylea, voici ma reponse.")
        client = FakeStreamingClient([(events, final)])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            stream=True,
        )
        deltas: list[str] = []
        async for ev in loop.run(user_message="salut"):
            if ev.type == "token_delta":
                deltas.append(ev.data["text"])

        # Les deltas remontes concatenes doivent recomposer le texte entier.
        assert "".join(deltas) == "Bonjour Sylea, voici ma reponse."
        # Plusieurs fragments (pas un seul bloc monolithique).
        assert len(deltas) >= 3
        # Le final_text doit etre bien consolide dans le LoopResult.
        assert loop.result.final_text == "Bonjour Sylea, voici ma reponse."
        # L'API stream a bien ete appelee (pas create).
        assert len(client.messages.stream_calls) == 1
        assert len(client.messages.create_calls) == 0

    async def test_thinking_deltas_when_thinking_enabled(self):
        """Si thinking_enabled=True, les thinking_delta doivent etre emis et
        le bloc thinking preserve dans l'historique pour les tours suivants."""
        events, final = _make_stream_events(
            text="Reponse finale.",
            thinking="Je reflechis profondement a la question posee.",
        )
        client = FakeStreamingClient([(events, final)])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            stream=True,
            thinking_enabled=True,
            thinking_budget_tokens=1000,
        )
        thinking_deltas: list[str] = []
        text_deltas: list[str] = []
        async for ev in loop.run(user_message="go"):
            if ev.type == "thinking_delta":
                thinking_deltas.append(ev.data["text"])
            elif ev.type == "token_delta":
                text_deltas.append(ev.data["text"])

        assert "".join(thinking_deltas) == "Je reflechis profondement a la question posee."
        assert "".join(text_deltas) == "Reponse finale."

        # Verifie que le param `thinking` a bien ete passe a l'API.
        call_kwargs = client.messages.stream_calls[0]
        assert call_kwargs["thinking"]["type"] == "enabled"
        assert call_kwargs["thinking"]["budget_tokens"] == 1000

    async def test_non_streaming_mode_still_works(self):
        """stream=False (defaut) : pas de token_delta, pas d'appel a .stream()."""
        client = FakeAnthropicClient([_text_response("ok non-stream.")])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            stream=False,
        )
        types_seen = []
        async for ev in loop.run(user_message="go"):
            types_seen.append(ev.type)
        assert "token_delta" not in types_seen
        assert loop.result.final_text == "ok non-stream."


@pytest.mark.asyncio
class TestCancellation:
    async def test_cancel_between_turns_stops_loop(self):
        """Si cancel_event.set() avant un tour, la boucle emet `cancelled`
        et sort sans appeler le LLM."""
        import asyncio as _aio
        cancel = _aio.Event()
        cancel.set()  # pre-cancel

        client = FakeAnthropicClient([_text_response("ne devrait pas etre appele")])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            cancel_event=cancel,
        )
        types_seen = []
        async for ev in loop.run(user_message="go"):
            types_seen.append(ev.type)
        assert "cancelled" in types_seen
        # Aucun appel LLM : la boucle s'est arretee avant meme le 1er tour.
        assert len(client.messages.calls) == 0
        assert loop.result.stop_reason == "cancelled"

    async def test_cancel_mid_stream_aborts_generation(self):
        """Si cancel_event.set() pendant qu'on streame, la boucle interrompt
        le stream et sort avec stop_reason='cancelled'."""
        import asyncio as _aio
        cancel = _aio.Event()

        # On cree des events qui bougent — le cancel sera declenche par le 1er
        # token_delta via un callback deguise.
        events, final = _make_stream_events("Texte long qui devrait etre interrompu.")
        client = FakeStreamingClient([(events, final)])
        loop = AgenticLoop(
            client=client,
            system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=MockExecutor(),
            max_turns=3,
            stream=True,
            cancel_event=cancel,
        )

        collected_tokens: list[str] = []
        saw_cancelled = False
        async for ev in loop.run(user_message="go"):
            if ev.type == "token_delta":
                collected_tokens.append(ev.data["text"])
                # Annule apres le 1er fragment recu
                if len(collected_tokens) == 1:
                    cancel.set()
            elif ev.type == "cancelled":
                saw_cancelled = True

        assert saw_cancelled is True
        # On devrait avoir recu 1 token mais PAS tous
        assert len(collected_tokens) < 5
        assert loop.result.stop_reason == "cancelled"


# ══════════════════════════════════════════════════════════════════════════════
# Hooks : pre/post autour de chaque tool_use, possibilite de MODIFY ou BLOCK.
# ══════════════════════════════════════════════════════════════════════════════
class TestHookRegistryIntegration:
    """Hooks pre/post appliques par AgenticLoop autour de chaque tool_use."""

    def _basic_tools(self):
        from api.agent3_native_tools import build_tool_schemas
        return build_tool_schemas(enabled_actions={"SEARCH"})

    @pytest.mark.asyncio
    async def test_pre_hook_modify_mutates_input(self):
        from api.agent3_hooks import HookRegistry, HookResult, HookDecision

        reg = HookRegistry()

        def pre(ctx):
            return HookResult(
                decision=HookDecision.MODIFY,
                modified_data={**ctx.action_data, "query": "mutated"},
            )

        reg.register_pre("SEARCH", pre, name="mutator")

        captured: list[dict] = []

        class _Exec:
            async def execute(self, action_type, action_input):
                captured.append(dict(action_input))
                return {"content": "ok", "is_error": False, "raw": {}}

        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "original"}),
            _text_response("done"),
        ])
        loop = AgenticLoop(
            client=client, system_prompt="", tools=self._basic_tools(),
            executor=_Exec(), max_turns=3,
            hook_registry=reg,
        )
        async for _ in loop.run("go"):
            pass
        assert captured and captured[0]["query"] == "mutated"

    @pytest.mark.asyncio
    async def test_pre_hook_block_prevents_execution(self):
        from api.agent3_hooks import HookRegistry, HookResult, HookDecision

        reg = HookRegistry()
        reg.register_pre(
            "SEARCH",
            lambda ctx: HookResult(decision=HookDecision.BLOCK, block_reason="interdit"),
            name="blocker",
        )

        calls: list[str] = []

        class _Exec:
            async def execute(self, action_type, action_input):
                calls.append(action_type)
                return {"content": "should-not-run", "is_error": False, "raw": {}}

        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "x"}),
            _text_response("resigne"),
        ])
        loop = AgenticLoop(
            client=client, system_prompt="", tools=self._basic_tools(),
            executor=_Exec(), max_turns=3,
            hook_registry=reg,
        )
        events: list = []
        async for ev in loop.run("go"):
            events.append(ev)

        assert calls == []  # executor jamais appele
        hook_blocked = [e for e in events if e.type == "hook_blocked"]
        assert hook_blocked and hook_blocked[0].data["hook_name"] == "blocker"
        # Un tool_result is_error a du etre emis pour que le LLM puisse pivoter.
        tr = [e for e in events if e.type == "tool_result"]
        assert tr and tr[0].data["is_error"] is True

    @pytest.mark.asyncio
    async def test_post_hook_runs_after_success(self):
        from api.agent3_hooks import HookRegistry, HookResult, HookDecision

        reg = HookRegistry()
        post_calls: list[str] = []

        def post(ctx):
            post_calls.append(ctx.action_type)
            return HookResult(decision=HookDecision.LOG_ONLY, log_message="done")

        reg.register_post("SEARCH", post, name="audit")

        class _Exec:
            async def execute(self, action_type, action_input):
                return {"content": "ok", "is_error": False, "raw": {}}

        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "x"}),
            _text_response("fini"),
        ])
        loop = AgenticLoop(
            client=client, system_prompt="", tools=self._basic_tools(),
            executor=_Exec(), max_turns=3,
            hook_registry=reg,
        )
        async for _ in loop.run("go"):
            pass
        assert post_calls == ["SEARCH"]

    @pytest.mark.asyncio
    async def test_no_hook_registry_runs_normally(self):
        """AgenticLoop sans hook_registry doit se comporter comme avant."""

        class _Exec:
            async def execute(self, action_type, action_input):
                return {"content": "ok", "is_error": False, "raw": {}}

        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "x"}),
            _text_response("ok"),
        ])
        loop = AgenticLoop(
            client=client, system_prompt="", tools=self._basic_tools(),
            executor=_Exec(), max_turns=3,
        )
        tool_results = []
        async for ev in loop.run("go"):
            if ev.type == "tool_result":
                tool_results.append(ev)
        assert tool_results and tool_results[0].data["is_error"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4 : Live-feedback auto-extension ClawHub
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestAutoExtensionEvents:
    """Le dispatch des meta-tools CLAWHUB_* doit emettre des events
    auto_extension_start/found/ready/error en plus des classiques tool_use /
    tool_result, pour que l'UI puisse afficher un indicateur live."""

    def _meta_tools(self) -> list[dict]:
        """Meta-tools minimum necessaires pour router CLAWHUB_* via le LLM."""
        return [
            {
                "name": "clawhub_search",
                "description": "search",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
            {
                "name": "clawhub_install",
                "description": "install",
                "input_schema": {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]},
            },
            {
                "name": "clawhub_publish",
                "description": "publish",
                "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            },
        ]

    async def test_search_emits_start_then_found(self):
        """clawhub_search reussi -> auto_extension_start precede auto_extension_found
        avec la liste des candidats extraite de raw.results."""
        client = FakeAnthropicClient([
            _tool_use_response("clawhub_search", {"query": "slack notifications"}, tool_id="tu_s"),
            _text_response("Voici les skills trouves."),
        ])
        executor = MockExecutor(responses={
            "CLAWHUB_SEARCH": {
                "content": "**2 skill(s) trouve(s)**\n1. `slack-notify` — poste sur Slack\n2. `slack-webhook` — via webhook",
                "is_error": False,
                "raw": {
                    "query": "slack notifications",
                    "results": [
                        {"slug": "slack-notify", "description": "poste sur Slack",
                         "author": "alice", "version": "1.2.0"},
                        {"slug": "slack-webhook", "description": "via webhook",
                         "author": "bob", "version": "0.5.1"},
                    ],
                },
            },
        })
        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=self._meta_tools(), executor=executor, max_turns=5,
        )
        events = []
        async for ev in loop.run(user_message="poste sur slack"):
            events.append(ev)

        types = [e.type for e in events]
        # start doit preceder found, qui suivent tool_use/tool_result respectivement
        assert "auto_extension_start" in types
        assert "auto_extension_found" in types
        idx_start = types.index("auto_extension_start")
        idx_found = types.index("auto_extension_found")
        idx_tool_use = types.index("tool_use")
        idx_tool_result = types.index("tool_result")
        # Ordre attendu : tool_use -> auto_extension_start -> tool_result -> auto_extension_found
        assert idx_tool_use < idx_start < idx_tool_result < idx_found

        start_ev = [e for e in events if e.type == "auto_extension_start"][0]
        assert start_ev.data["phase"] == "search"
        assert start_ev.data["action_type"] == "CLAWHUB_SEARCH"
        assert "slack" in start_ev.data["trigger"]

        found_ev = [e for e in events if e.type == "auto_extension_found"][0]
        assert found_ev.data["count"] == 2
        assert found_ev.data["query"] == "slack notifications"
        slugs = [c["slug"] for c in found_ev.data["candidates"]]
        assert slugs == ["slack-notify", "slack-webhook"]
        assert found_ev.data["candidates"][0]["author"] == "alice"

    async def test_install_emits_start_then_ready_with_tool_alias(self):
        """clawhub_install reussi (via pre-approval bypass confirmation) ->
        auto_extension_start + auto_extension_ready avec tool_alias skill_<slug>."""
        client = FakeAnthropicClient([
            _tool_use_response("clawhub_install", {"slug": "postgres-backup"}, tool_id="tu_i"),
            _text_response("Skill installe, voici ce qu'il peut faire."),
        ])
        executor = MockExecutor(responses={
            "CLAWHUB_INSTALL": {
                "content": "Skill 'postgres-backup' installe dans ~/.openclaw/skills/postgres-backup/.",
                "is_error": False,
                "raw": {"slug": "postgres-backup", "version": "2.0.0"},
            },
        })
        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=self._meta_tools(), executor=executor, max_turns=5,
            # Pre-approve car CLAWHUB_INSTALL est destructive en mode default
            pre_approved_tool_ids={"tu_i"},
        )
        events = []
        async for ev in loop.run(user_message="installe le skill postgres"):
            events.append(ev)

        types = [e.type for e in events]
        assert "auto_extension_start" in types
        assert "auto_extension_ready" in types

        start_ev = [e for e in events if e.type == "auto_extension_start"][0]
        assert start_ev.data["phase"] == "install"
        assert start_ev.data["action_type"] == "CLAWHUB_INSTALL"

        ready_ev = [e for e in events if e.type == "auto_extension_ready"][0]
        assert ready_ev.data["phase"] == "install"
        assert ready_ev.data["slug"] == "postgres-backup"
        # Conversion kebab-case -> snake_case pour le nom du tool
        assert ready_ev.data["tool_alias"] == "skill_postgres_backup"

    async def test_publish_emits_start_then_ready(self):
        """clawhub_publish reussi -> auto_extension_start + auto_extension_ready
        avec phase=publish."""
        client = FakeAnthropicClient([
            _tool_use_response("clawhub_publish",
                               {"name": "my-new-skill", "slug": "my-new-skill"},
                               tool_id="tu_p"),
            _text_response("Publie."),
        ])
        executor = MockExecutor(responses={
            "CLAWHUB_PUBLISH": {
                "content": "Skill 'my-new-skill' publie sur ClawHub.",
                "is_error": False,
                "raw": {"slug": "my-new-skill", "version": "0.1.0"},
            },
        })
        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=self._meta_tools(), executor=executor, max_turns=5,
            pre_approved_tool_ids={"tu_p"},
        )
        events = []
        async for ev in loop.run(user_message="publie un skill"):
            events.append(ev)

        types = [e.type for e in events]
        assert "auto_extension_start" in types
        assert "auto_extension_ready" in types

        ready_ev = [e for e in events if e.type == "auto_extension_ready"][0]
        assert ready_ev.data["phase"] == "publish"
        assert ready_ev.data["slug"] == "my-new-skill"

    async def test_failed_search_emits_auto_extension_error_not_found(self):
        """clawhub_search qui echoue (is_error=True) -> auto_extension_error
        emis a la place de auto_extension_found."""
        client = FakeAnthropicClient([
            _tool_use_response("clawhub_search", {"query": "foobar"}, tool_id="tu_f"),
            _text_response("Recherche echouee."),
        ])
        executor = MockExecutor(responses={
            "CLAWHUB_SEARCH": {
                "content": "Recherche ClawHub echouee: CLI non installee.",
                "is_error": True,
                "raw": {"rc": 127},
            },
        })
        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=self._meta_tools(), executor=executor, max_turns=5,
        )
        events = []
        async for ev in loop.run(user_message="cherche foobar"):
            events.append(ev)

        types = [e.type for e in events]
        assert "auto_extension_start" in types
        assert "auto_extension_error" in types
        # Pas de found sur erreur
        assert "auto_extension_found" not in types

        err_ev = [e for e in events if e.type == "auto_extension_error"][0]
        assert err_ev.data["phase"] == "search"
        assert err_ev.data["action_type"] == "CLAWHUB_SEARCH"
        assert "CLI non installee" in err_ev.data["message"]

    async def test_non_clawhub_tool_does_not_emit_auto_extension(self):
        """Un tool normal (SEARCH, MEMORY, etc.) ne doit emettre aucun event
        auto_extension_*. Seuls les meta-tools CLAWHUB_* le font."""
        client = FakeAnthropicClient([
            _tool_use_response("search", {"query": "Ada"}, tool_id="tu_n"),
            _text_response("Voici Ada."),
        ])
        executor = MockExecutor(responses={
            "SEARCH": {"content": "Resultats...", "is_error": False, "raw": {}},
        })
        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=build_tool_schemas(enabled_actions={"SEARCH"}),
            executor=executor, max_turns=5,
        )
        events = []
        async for ev in loop.run(user_message="qui est ada"):
            events.append(ev)

        types = [e.type for e in events]
        assert "tool_use" in types
        assert "tool_result" in types
        # Aucun event auto_extension pour un tool non-meta
        assert not any(t.startswith("auto_extension_") for t in types)

    async def test_install_triggers_tools_refreshed_with_new_slugs(self):
        """Apres un CLAWHUB_INSTALL reussi, AgenticLoop doit :
          1. Appeler tools_rebuild_fn pour regenerer sa liste de tools
          2. Swap self.tools vers la nouvelle liste
          3. Emettre un event tools_refreshed avec added_slugs = [nouveau_slug]
        Ainsi le LLM voit `skill_<slug>` des le prochain tour."""
        client = FakeAnthropicClient([
            _tool_use_response("clawhub_install", {"slug": "jira-sync"}, tool_id="tu_j"),
            _text_response("Skill installe, fin."),
        ])
        executor = MockExecutor(responses={
            "CLAWHUB_INSTALL": {
                "content": "Skill 'jira-sync' installe.", "is_error": False,
                "raw": {"slug": "jira-sync"},
            },
        })

        # Tools initiaux : juste les meta-tools (pas encore skill_jira_sync)
        initial_tools = self._meta_tools()

        # tools apres install : on ajoute skill_jira_sync pour simuler le load
        rebuilt_tools = self._meta_tools() + [{
            "name": "skill_jira_sync",
            "description": "Sync Jira issues",
            "input_schema": {"type": "object", "properties": {"instruction": {"type": "string"}}},
        }]

        rebuild_calls = {"n": 0}
        def _rebuild() -> list[dict]:
            rebuild_calls["n"] += 1
            return rebuilt_tools

        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=initial_tools, executor=executor, max_turns=5,
            pre_approved_tool_ids={"tu_j"},
            tools_rebuild_fn=_rebuild,
        )
        events = []
        async for ev in loop.run(user_message="installe jira-sync"):
            events.append(ev)

        # La closure doit avoir ete appelee exactement 1 fois
        assert rebuild_calls["n"] == 1

        # Un event tools_refreshed doit etre emis avec le nouveau slug
        refresh_events = [e for e in events if e.type == "tools_refreshed"]
        assert len(refresh_events) == 1
        refresh_data = refresh_events[0].data
        assert refresh_data["ok"] is True
        assert refresh_data["added_slugs"] == ["jira-sync"]
        assert refresh_data["total_before"] == len(initial_tools)
        assert refresh_data["total_after"] == len(rebuilt_tools)
        assert refresh_data["trigger"] == "clawhub_install"
        assert refresh_data["slug"] == "jira-sync"

        # self.tools a bien ete swap
        assert any(t["name"] == "skill_jira_sync" for t in loop.tools)

    async def test_install_without_rebuild_fn_still_invalidates_cache(self):
        """Si tools_rebuild_fn n'est pas fourni, tools_refreshed est quand meme
        emis (avec added_slugs=[], total_before=total_after, ok=False) mais
        sans crasher. Le cache du loader est invalide best-effort."""
        client = FakeAnthropicClient([
            _tool_use_response("clawhub_install", {"slug": "foo"}, tool_id="tu_n"),
            _text_response("ok"),
        ])
        executor = MockExecutor(responses={
            "CLAWHUB_INSTALL": {"content": "installed", "is_error": False, "raw": {}},
        })
        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=self._meta_tools(), executor=executor, max_turns=5,
            pre_approved_tool_ids={"tu_n"},
            # tools_rebuild_fn omis
        )
        events = []
        async for ev in loop.run(user_message="installe foo"):
            events.append(ev)

        refresh_events = [e for e in events if e.type == "tools_refreshed"]
        assert len(refresh_events) == 1
        # Pas de nouveau slug puisque le callback etait absent
        assert refresh_events[0].data["added_slugs"] == []
        assert refresh_events[0].data["ok"] is False
        # Pas de crash : la boucle a abouti normalement
        assert loop.result is not None

    async def test_search_and_publish_do_not_trigger_tools_refreshed(self):
        """Seul CLAWHUB_INSTALL declenche tools_refreshed. Un search ou un
        publish (meme reussi) n'ajoute pas de tool skill_<slug>, donc pas de
        refresh."""
        client = FakeAnthropicClient([
            _tool_use_response("clawhub_search", {"query": "x"}, tool_id="tu_s"),
            _tool_use_response("clawhub_publish", {"slug": "my-skill", "name": "my-skill"}, tool_id="tu_p"),
            _text_response("done"),
        ])
        executor = MockExecutor(responses={
            "CLAWHUB_SEARCH": {"content": "empty", "is_error": False, "raw": {"results": []}},
            "CLAWHUB_PUBLISH": {"content": "published", "is_error": False, "raw": {}},
        })
        rebuild_calls = {"n": 0}
        def _rebuild(): rebuild_calls["n"] += 1; return self._meta_tools()

        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=self._meta_tools(), executor=executor, max_turns=5,
            pre_approved_tool_ids={"tu_p"},
            tools_rebuild_fn=_rebuild,
        )
        events = []
        async for ev in loop.run(user_message="test"):
            events.append(ev)

        # tools_refreshed NE doit PAS etre emis pour search ou publish
        types = [e.type for e in events]
        assert "tools_refreshed" not in types
        # Et la closure ne doit pas avoir ete appelee
        assert rebuild_calls["n"] == 0

    async def test_install_via_resume_after_confirmation_emits_events(self):
        """Meme chemin via resume_from_confirmation : l'utilisateur approuve
        un CLAWHUB_INSTALL paused -> start + ready emis dans la reprise."""
        client = FakeAnthropicClient([
            _tool_use_response("clawhub_install", {"slug": "discord-notify"}, tool_id="tu_c"),
            _text_response("Installe."),
        ])
        executor = MockExecutor(responses={
            "CLAWHUB_INSTALL": {
                "content": "Skill installe.",
                "is_error": False,
                "raw": {"slug": "discord-notify"},
            },
        })
        loop = AgenticLoop(
            client=client, system_prompt="test",
            tools=self._meta_tools(), executor=executor, max_turns=5,
            # Permission par defaut -> install sera gate
        )

        # 1er passage : attendre awaiting_confirmation
        async for _ in loop.run(user_message="installe discord"):
            pass
        assert loop.result.stop_reason == "awaiting_confirmation"
        assert loop.pending_confirmation is not None

        # Completer la conversation avec une reponse finale pour ne pas depasser le fake script
        client.messages._responses.append(_text_response("Merci, fait."))

        # 2e passage : user approuve, on doit voir auto_extension_start + ready
        resume_events = []
        async for ev in loop.resume_from_confirmation(
            loop.pending_confirmation,
            approvals={"tu_c": True},
        ):
            resume_events.append(ev)

        resume_types = [e.type for e in resume_events]
        assert "auto_extension_start" in resume_types
        assert "auto_extension_ready" in resume_types
        start_ev = [e for e in resume_events if e.type == "auto_extension_start"][0]
        assert start_ev.data["phase"] == "install"
        ready_ev = [e for e in resume_events if e.type == "auto_extension_ready"][0]
        assert ready_ev.data["slug"] == "discord-notify"
        assert ready_ev.data["tool_alias"] == "skill_discord_notify"
