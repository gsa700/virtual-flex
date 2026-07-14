import asyncio

from virtualflex.supervisor import Supervisor


def _recorder(events, name):
    async def hook():
        events.append(name)
    return hook


def test_supervisor_debounced_online_offline():
    async def scenario():
        present = {"v": False}
        events = []
        sup = Supervisor(
            is_present=lambda: present["v"],
            go_online=_recorder(events, "online"),
            go_offline=_recorder(events, "offline"),
            present_after=0.05, absent_after=0.05, poll_interval=0.01)
        task = asyncio.create_task(sup.run())

        # sustained presence -> ONLINE after the debounce
        present["v"] = True
        await asyncio.sleep(0.15)
        assert events == ["online"] and sup.online

        # a blip shorter than absent_after must NOT flap us offline
        present["v"] = False
        await asyncio.sleep(0.02)
        present["v"] = True
        await asyncio.sleep(0.1)
        assert events == ["online"]

        # sustained absence -> OFFLINE (stack dropped -> AGXL to Dummy Load)
        present["v"] = False
        await asyncio.sleep(0.15)
        assert events == ["online", "offline"] and not sup.online

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
