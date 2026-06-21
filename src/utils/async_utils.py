import asyncio
import threading
from typing import Coroutine


def run_async(coro: Coroutine):
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
        loop.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
