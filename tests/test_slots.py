"""Очередь с местами: порядок, приоритет админа, отмена ожидания."""
import asyncio
import contextlib

from bot.slots import SlotQueue


async def _hold(queue: SlotQueue, release: asyncio.Event) -> None:
    async with queue.slot():
        await release.wait()


def test_free_slot_is_taken_immediately():
    async def main():
        q = SlotQueue(2)
        async with q.slot():
            async with q.slot():
                assert q.active == 2 and q.busy()
        assert q.active == 0 and not q.busy()

    asyncio.run(main())


def test_waiter_sees_position_and_admin_goes_first():
    async def main():
        q = SlotQueue(1)
        release = asyncio.Event()
        order, positions = [], []

        async def on_position(pos):
            positions.append(pos)

        async def worker(name, priority, cb=None):
            async with q.slot(priority, cb, update_every=0.01):
                order.append(name)

        holder = asyncio.create_task(_hold(q, release))
        await asyncio.sleep(0)
        user = asyncio.create_task(worker("user", 1, on_position))
        await asyncio.sleep(0)
        admin = asyncio.create_task(worker("admin", 0))
        await asyncio.sleep(0.05)

        release.set()
        await asyncio.gather(holder, user, admin)
        assert order == ["admin", "user"]
        assert positions[:2] == [1, 2]     # админ встал впереди — пользователь стал вторым
        assert q.active == 0 and not q._waiters

    asyncio.run(main())


def test_cancelled_waiter_leaves_queue():
    async def main():
        q = SlotQueue(1)
        release = asyncio.Event()
        holder = asyncio.create_task(_hold(q, release))
        await asyncio.sleep(0)

        async def waiter():
            async with q.slot(update_every=0.01):
                pass

        w = asyncio.create_task(waiter())
        await asyncio.sleep(0.02)
        assert len(q._waiters) == 1
        w.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await w
        assert q._waiters == []

        release.set()
        await holder
        assert q.active == 0

    asyncio.run(main())
