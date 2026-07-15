import asyncio

from virtualflex.config import Config
from virtualflex.server import CommandServer
from virtualflex.state import Radio


def test_stop_closes_listener_and_drops_clients():
    async def scenario():
        radio = Radio(Config.load(None))
        server = CommandServer(radio)
        await server.start("127.0.0.1", 0)          # ephemeral port
        port = server.port

        # a stack client connects and gets the V/H handshake
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        data = await asyncio.wait_for(reader.read(64), timeout=2)
        assert data.startswith(b"V")
        assert len(radio.clients) == 1

        # going offline: listener closed AND the client connection severed
        await server.stop()
        assert len(radio.clients) == 0
        assert not radio.amplifiers and not radio.meters and not radio.interlocks

        # the port now refuses connections (the stack sees the radio gone)
        refused = False
        try:
            _, w2 = await asyncio.open_connection("127.0.0.1", port)
            w2.close()
        except OSError:
            refused = True
        assert refused
        writer.close()

    asyncio.run(scenario())
