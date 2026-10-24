"""Очередь с местами: несколько задач одновременно, остальные ждут и видят свой номер.

Админ встаёт в начало очереди (priority=0), остальные — по порядку прихода.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
from typing import Awaitable, Callable

PositionCb = Callable[[int], Awaitable[None]]


class SlotQueue:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.active = 0
        self._waiters: list[tuple[int, int, asyncio.Future]] = []
        self._seq = itertools.count()

    def busy(self) -> bool:
        """Свободного места нет — новая задача встанет в очередь."""
        return self.active >= self.capacity or bool(self._waiters)

    def _position(self, fut: asyncio.Future) -> int:
        for i, (_, _, f) in enumerate(self._waiters):
            if f is fut:
                return i + 1
        return 0

    def _release(self) -> None:
        while self._waiters:
            _, _, fut = self._waiters.pop(0)
            if not fut.done():
                fut.set_result(None)   # место переходит следующему, active не меняется
                return
        self.active -= 1

    @contextlib.asynccontextmanager
    async def slot(self, priority: int = 1, on_position: PositionCb | None = None,
                   update_every: float = 5.0):
        if not self.busy():
            self.active += 1
        else:
            fut = asyncio.get_running_loop().create_future()
            entry = (priority, next(self._seq), fut)
            self._waiters.append(entry)
            self._waiters.sort(key=lambda e: (e[0], e[1]))
            last = None
            try:
                while not fut.done():
                    pos = self._position(fut)
                    if on_position and pos != last:
                        last = pos
                        await on_position(pos)
                    try:
                        await asyncio.wait_for(asyncio.shield(fut), update_every)
                    except asyncio.TimeoutError:
                        pass
            except BaseException:
                if fut.done() and not fut.cancelled():
                    self._release()           # место уже выдали — отдаём следующему
                else:
                    fut.cancel()
                    with contextlib.suppress(ValueError):
                        self._waiters.remove(entry)
                raise
        try:
            yield
        finally:
            self._release()
