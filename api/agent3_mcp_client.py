"""
Agent 3 — MCP Client (Model Context Protocol).

Client MCP standard (spec 2024-11-05) pour connecter Agent 3
a n'importe quel serveur MCP externe.

Le MCP est un protocole JSON-RPC 2.0 sur stdin/stdout ou SSE.
Ce client supporte :
  - Decouverte des outils (tools/list)
  - Invocation d'outils (tools/call)
  - Decouverte des resources (resources/list)
  - Lecture de resources (resources/read)
  - Prompts templates (prompts/list, prompts/get)

Inspire du MCP client de Claude Code (ClientOrchestrator + McpServer).
Reimplemente from scratch en Python async pour Sylea.

Usage :
    client = MCPClient("weather-server", command="npx", args=["-y", "@weather/mcp"])
    await client.connect()
    tools = await client.list_tools()
    result = await client.call_tool("get_weather", {"city": "Paris"})
    await client.disconnect()

Ou via le registry :
    registry = get_mcp_registry()
    registry.add_server("weather", command="npx", args=[...])
    await registry.connect_all()
    all_tools = registry.list_all_tools()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("sylea.agent3.mcp_client")


@dataclass
class MCPTool:
    """Outil expose par un serveur MCP."""

    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    server_name: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "server_name": self.server_name,
        }

    def to_agent_tool_description(self) -> str:
        """Formate pour le system prompt de l'agent."""
        params = ""
        props = self.input_schema.get("properties", {})
        if props:
            params = ", ".join(f"{k}: {v.get('type', '?')}" for k, v in list(props.items())[:5])
        return f"  - {self.server_name}/{self.name}({params}) — {self.description}"


@dataclass
class MCPResource:
    """Resource exposee par un serveur MCP."""

    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    server_name: str = ""

    def to_dict(self) -> dict:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mime_type": self.mime_type,
            "server_name": self.server_name,
        }


@dataclass
class MCPCallResult:
    """Resultat d'un appel d'outil MCP."""

    success: bool
    content: list[dict] = field(default_factory=list)  # [{type: "text", text: "..."}, ...]
    error: str = ""
    is_error: bool = False
    duration_ms: float = 0.0

    @property
    def text(self) -> str:
        """Extrait le texte de tous les content blocks."""
        return "\n".join(
            c.get("text", "") for c in self.content
            if c.get("type") == "text"
        )

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "content": self.content,
            "error": self.error,
            "is_error": self.is_error,
            "text": self.text,
            "duration_ms": round(self.duration_ms, 1),
        }


class MCPClient:
    """Client pour un serveur MCP unique (stdio transport)."""

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        timeout_s: float = 30.0,
    ):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.timeout_s = timeout_s

        self._process: Optional[asyncio.subprocess.Process] = None
        self._tools: list[MCPTool] = []
        self._resources: list[MCPResource] = []
        self._connected = False
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None

    @property
    def connected(self) -> bool:
        return self._connected and self._process is not None

    async def connect(self) -> bool:
        """Demarre le serveur MCP et effectue le handshake."""
        try:
            full_env = {**os.environ, **self.env}
            self._process = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
            )

            # Demarrer la lecture des reponses
            self._read_task = asyncio.create_task(self._read_loop())

            # Handshake : initialize
            resp = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "roots": {"listChanged": False},
                },
                "clientInfo": {
                    "name": "sylea-agent3",
                    "version": "1.0.0",
                },
            })

            if resp and "protocolVersion" in resp:
                # Envoyer la notification initialized
                await self._send_notification("notifications/initialized", {})
                self._connected = True
                logger.info(f"MCP server '{self.name}' connected (protocol {resp.get('protocolVersion')})")

                # Decouvrir les outils et resources
                await self._discover()
                return True

            logger.warning(f"MCP server '{self.name}' handshake failed")
            return False

        except Exception as e:
            logger.error(f"MCP server '{self.name}' connect failed: {e}")
            return False

    async def disconnect(self):
        """Arrete proprement le serveur MCP."""
        if self._read_task:
            self._read_task.cancel()
        if self._process:
            try:
                self._process.stdin.close()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except Exception:
                self._process.kill()
        self._connected = False
        self._process = None
        self._tools.clear()
        self._resources.clear()
        logger.info(f"MCP server '{self.name}' disconnected")

    async def list_tools(self) -> list[MCPTool]:
        """Retourne les outils disponibles."""
        if not self._tools:
            await self._discover_tools()
        return self._tools

    async def call_tool(self, tool_name: str, arguments: Optional[dict] = None) -> MCPCallResult:
        """Appelle un outil MCP."""
        if not self.connected:
            return MCPCallResult(success=False, error="Non connecte")

        t0 = time.perf_counter()
        try:
            resp = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments or {},
            })

            duration = (time.perf_counter() - t0) * 1000

            if resp is None:
                return MCPCallResult(success=False, error="Pas de reponse", duration_ms=duration)

            content = resp.get("content", [])
            is_error = resp.get("isError", False)

            return MCPCallResult(
                success=not is_error,
                content=content,
                is_error=is_error,
                duration_ms=duration,
            )

        except asyncio.TimeoutError:
            return MCPCallResult(
                success=False,
                error=f"Timeout ({self.timeout_s}s)",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as e:
            return MCPCallResult(
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

    async def list_resources(self) -> list[MCPResource]:
        """Retourne les resources disponibles."""
        if not self._resources:
            await self._discover_resources()
        return self._resources

    async def read_resource(self, uri: str) -> MCPCallResult:
        """Lit une resource MCP."""
        if not self.connected:
            return MCPCallResult(success=False, error="Non connecte")

        t0 = time.perf_counter()
        try:
            resp = await self._send_request("resources/read", {"uri": uri})
            duration = (time.perf_counter() - t0) * 1000
            if resp:
                contents = resp.get("contents", [])
                return MCPCallResult(
                    success=True,
                    content=[{"type": "text", "text": c.get("text", "")} for c in contents],
                    duration_ms=duration,
                )
            return MCPCallResult(success=False, error="Pas de reponse", duration_ms=duration)
        except Exception as e:
            return MCPCallResult(success=False, error=str(e), duration_ms=(time.perf_counter() - t0) * 1000)

    # ── Internal ──

    async def _discover(self):
        await self._discover_tools()
        await self._discover_resources()

    async def _discover_tools(self):
        try:
            resp = await self._send_request("tools/list", {})
            if resp and "tools" in resp:
                self._tools = [
                    MCPTool(
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                        server_name=self.name,
                    )
                    for t in resp["tools"]
                ]
                logger.info(f"MCP '{self.name}': {len(self._tools)} tools discovered")
        except Exception as e:
            logger.debug(f"MCP '{self.name}' tools/list failed: {e}")

    async def _discover_resources(self):
        try:
            resp = await self._send_request("resources/list", {})
            if resp and "resources" in resp:
                self._resources = [
                    MCPResource(
                        uri=r["uri"],
                        name=r.get("name", ""),
                        description=r.get("description", ""),
                        mime_type=r.get("mimeType", ""),
                        server_name=self.name,
                    )
                    for r in resp["resources"]
                ]
                logger.info(f"MCP '{self.name}': {len(self._resources)} resources discovered")
        except Exception as e:
            logger.debug(f"MCP '{self.name}' resources/list failed: {e}")

    async def _send_request(self, method: str, params: dict) -> Optional[dict]:
        """Envoie une requete JSON-RPC et attend la reponse."""
        if not self._process or not self._process.stdin:
            return None

        self._request_id += 1
        rid = self._request_id
        msg = json.dumps({
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params,
        }) + "\n"

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = future

        try:
            self._process.stdin.write(msg.encode())
            await self._process.stdin.drain()
            result = await asyncio.wait_for(future, timeout=self.timeout_s)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise
        except Exception as e:
            self._pending.pop(rid, None)
            raise

    async def _send_notification(self, method: str, params: dict):
        """Envoie une notification JSON-RPC (pas de reponse attendue)."""
        if not self._process or not self._process.stdin:
            return
        msg = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }) + "\n"
        self._process.stdin.write(msg.encode())
        await self._process.stdin.drain()

    async def _read_loop(self):
        """Boucle de lecture des reponses du serveur."""
        if not self._process or not self._process.stdout:
            return
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode().strip())
                    rid = msg.get("id")
                    if rid is not None and rid in self._pending:
                        future = self._pending.pop(rid)
                        if "error" in msg:
                            future.set_exception(
                                Exception(msg["error"].get("message", "MCP error"))
                            )
                        else:
                            future.set_result(msg.get("result"))
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"MCP read loop error for '{self.name}': {e}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "connected": self.connected,
            "tools_count": len(self._tools),
            "resources_count": len(self._resources),
        }


class MCPRegistry:
    """Registre de serveurs MCP configures."""

    def __init__(self):
        self._servers: dict[str, MCPClient] = {}

    def add_server(
        self,
        name: str,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        timeout_s: float = 30.0,
    ) -> MCPClient:
        """Ajoute un serveur MCP au registre."""
        client = MCPClient(name, command, args, env, timeout_s)
        self._servers[name] = client
        return client

    def remove_server(self, name: str) -> bool:
        client = self._servers.pop(name, None)
        if client and client.connected:
            asyncio.create_task(client.disconnect())
        return client is not None

    def get(self, name: str) -> Optional[MCPClient]:
        return self._servers.get(name)

    async def connect_all(self) -> dict[str, bool]:
        """Connecte tous les serveurs enregistres."""
        results = {}
        for name, client in self._servers.items():
            if not client.connected:
                results[name] = await client.connect()
            else:
                results[name] = True
        return results

    async def disconnect_all(self):
        """Deconnecte tous les serveurs."""
        for client in self._servers.values():
            if client.connected:
                await client.disconnect()

    def list_all_tools(self) -> list[MCPTool]:
        """Retourne tous les outils de tous les serveurs connectes."""
        tools = []
        for client in self._servers.values():
            if client.connected:
                tools.extend(client._tools)
        return tools

    def list_all_resources(self) -> list[MCPResource]:
        """Retourne toutes les resources de tous les serveurs connectes."""
        resources = []
        for client in self._servers.values():
            if client.connected:
                resources.extend(client._resources)
        return resources

    async def call_tool(self, server_name: str, tool_name: str, arguments: Optional[dict] = None) -> MCPCallResult:
        """Appelle un outil sur un serveur specifique."""
        client = self._servers.get(server_name)
        if not client:
            return MCPCallResult(success=False, error=f"Serveur MCP '{server_name}' inconnu")
        if not client.connected:
            return MCPCallResult(success=False, error=f"Serveur MCP '{server_name}' non connecte")
        return await client.call_tool(tool_name, arguments)

    async def call_tool_auto(self, tool_name: str, arguments: Optional[dict] = None) -> MCPCallResult:
        """Appelle un outil en trouvant automatiquement le bon serveur."""
        for client in self._servers.values():
            if client.connected:
                for tool in client._tools:
                    if tool.name == tool_name:
                        return await client.call_tool(tool_name, arguments)
        return MCPCallResult(success=False, error=f"Outil MCP '{tool_name}' introuvable")

    def build_prompt_block(self) -> str:
        """Genere le bloc pour le system prompt de l'agent."""
        tools = self.list_all_tools()
        if not tools:
            return ""
        lines = ["\n=== OUTILS MCP EXTERNES ==="]
        lines.append("Outils disponibles via MCP (Model Context Protocol) :")
        for tool in tools:
            lines.append(tool.to_agent_tool_description())
        lines.append(
            "\nPour invoquer : [ACTION:MCP_TOOL]{\"server\": \"nom\", \"tool\": \"nom_outil\", \"arguments\": {...}}[/ACTION]"
        )
        return "\n".join(lines)

    def list_servers(self) -> list[dict]:
        return [c.to_dict() for c in self._servers.values()]

    @property
    def count(self) -> int:
        return len(self._servers)

    @property
    def connected_count(self) -> int:
        return sum(1 for c in self._servers.values() if c.connected)

    def load_from_config(self, config: dict) -> int:
        """Charge les serveurs depuis un dict de config (format Claude Code).

        config: {
            "mcpServers": {
                "weather": {"command": "npx", "args": ["-y", "@weather/mcp"]},
                "db": {"command": "python", "args": ["mcp_db.py"], "env": {"DB_URL": "..."}},
            }
        }
        """
        servers = config.get("mcpServers", config.get("mcp_servers", {}))
        count = 0
        for name, spec in servers.items():
            if "command" in spec:
                self.add_server(
                    name=name,
                    command=spec["command"],
                    args=spec.get("args", []),
                    env=spec.get("env", {}),
                    timeout_s=spec.get("timeout", 30),
                )
                count += 1
        return count


# ── Singleton ──

_registry: Optional[MCPRegistry] = None


def get_mcp_registry() -> MCPRegistry:
    """Retourne le registre MCP singleton."""
    global _registry
    if _registry is None:
        _registry = MCPRegistry()
        # Charger la config si elle existe
        config_paths = [
            os.path.expanduser("~/.sylea/mcp_servers.json"),
            os.path.join(os.path.dirname(__file__), "..", "mcp_servers.json"),
        ]
        for path in config_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    loaded = _registry.load_from_config(config)
                    logger.info(f"MCP: loaded {loaded} servers from {path}")
                except Exception as e:
                    logger.warning(f"MCP config load failed ({path}): {e}")
    return _registry
