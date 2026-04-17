"""
Thread dedie pour Playwright avec ProactorEventLoop.

Probleme resolu :
  Python 3.13 sur Windows utilise SelectorEventLoop par defaut,
  qui ne supporte pas asyncio.create_subprocess_exec().
  Playwright a besoin de ca pour lancer son driver node.js.

Solution :
  Un thread dedie fait tourner un ProactorEventLoop (Windows) pour Playwright.
  Le code async normal de FastAPI/uvicorn (main loop) continue d'utiliser
  SelectorEventLoop. On bridge les deux via asyncio.run_coroutine_threadsafe.

Usage :
    pw = get_playwright_thread()
    async for event in pw.bridge_async_gen(lambda: my_playwright_async_gen()):
        yield event  # Sur le main loop, alimente par le thread Playwright
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any, AsyncGenerator, Callable, Coroutine

_SENTINEL = object()


class PlaywrightThread:
    """Thread singleton avec ProactorEventLoop pour heberger Playwright."""

    _instance: "PlaywrightThread | None" = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._init_once()
                cls._instance = instance
        return cls._instance

    def _init_once(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="playwright-proactor-loop",
        )
        self._thread.start()
        self._ready.wait()

    def _run(self):
        if sys.platform == "win32":
            self.loop = asyncio.ProactorEventLoop()
        else:
            self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    async def bridge_async_gen(
        self,
        async_gen_factory: Callable[[], AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        """
        Lance un async generator dans le thread Playwright et yield ses items
        dans le main loop. Les events sont passes via une asyncio.Queue (main loop)
        alimentee cross-thread via run_coroutine_threadsafe.
        """
        main_loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        async def producer():
            try:
                agen = async_gen_factory()
                async for item in agen:
                    # Push cross-thread : main_loop.queue depuis playwright thread
                    fut = asyncio.run_coroutine_threadsafe(queue.put(item), main_loop)
                    # Pas besoin d'attendre — on continue juste a produire
                    # (le futur se resoudra tot ou tard sur le main loop)
                    fut.add_done_callback(lambda _f: None)
            except Exception as e:
                fut = asyncio.run_coroutine_threadsafe(
                    queue.put(("__PW_ERROR__", e)), main_loop,
                )
                fut.add_done_callback(lambda _f: None)
            finally:
                fut = asyncio.run_coroutine_threadsafe(
                    queue.put(_SENTINEL), main_loop,
                )
                fut.add_done_callback(lambda _f: None)

        # Lance producer dans le thread Playwright
        asyncio.run_coroutine_threadsafe(producer(), self.loop)

        while True:
            item = await queue.get()
            if item is _SENTINEL:
                return
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "__PW_ERROR__":
                raise item[1]
            yield item

    def run_coro(self, coro: Coroutine[Any, Any, Any]):
        """Execute un coroutine dans le thread et retourne un awaitable main-loop-compatible."""
        concurrent_future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return asyncio.wrap_future(concurrent_future)


_singleton: PlaywrightThread | None = None


def get_playwright_thread() -> PlaywrightThread:
    global _singleton
    if _singleton is None:
        _singleton = PlaywrightThread()
    return _singleton
