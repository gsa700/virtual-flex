import asyncio

from virtualflex.k4 import K4Client


class MockK4:
    """A stand-in K4 CAT server: answers FA/FB/FT/MD/TQ(X) from mutable fields."""

    def __init__(self):
        self.fa = "00014213000"   # 14.213 MHz
        self.fb = "00007074000"   # 7.074 MHz
        self.ft = "0"             # TX VFO: 0=A (simplex), 1=B (split)
        self.md = "2"             # USB
        self.tq = "0"             # not keyed
        self.server = None
        self.port = None

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        buf = ""
        try:
            while True:
                data = await reader.read(256)
                if not data:
                    break
                buf += data.decode()
                while ";" in buf:
                    cmd, _, buf = buf.partition(";")
                    self._reply(writer, cmd.strip())
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass

    def _reply(self, writer, cmd):
        table = {"FA": f"FA{self.fa};", "FB": f"FB{self.fb};", "FT": f"FT{self.ft};",
                 "MD": f"MD{self.md};", "TQ": f"TQ{self.tq};", "TQX": f"TQ{self.tq};"}
        if cmd in table:
            writer.write(table[cmd].encode())

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


async def _run_briefly(client, ready, tries=100, step=0.02):
    task = asyncio.create_task(client.run())
    for _ in range(tries):
        await asyncio.sleep(step)
        if ready():
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_k4_reads_tx_freq_mode_and_ptt():
    async def scenario():
        srv = MockK4()
        await srv.start()
        tx, ptt = [], []
        client = K4Client(ip="127.0.0.1", port=srv.port,
                          on_tx=lambda f, m: tx.append((f, m)),
                          on_ptt=lambda k: ptt.append(k))
        task = asyncio.create_task(client.run())
        for _ in range(100):                       # wait for the initial FA/MD read
            await asyncio.sleep(0.02)
            if tx:
                break
        assert tx and tx[0] == (14213000, "USB")
        srv.tq = "1"                               # key up
        for _ in range(100):
            await asyncio.sleep(0.02)
            if ptt:
                break
        assert ptt and ptt[-1] is True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await srv.stop()

    asyncio.run(scenario())


def test_k4_split_follows_vfo_b():
    async def scenario():
        srv = MockK4()
        srv.ft = "1"                               # split: TX on VFO B
        await srv.start()
        tx = []
        client = K4Client(ip="127.0.0.1", port=srv.port,
                          on_tx=lambda f, m: tx.append((f, m)))
        await _run_briefly(client, lambda: bool(tx))
        assert tx and tx[0][0] == 7074000          # follows FB, not FA
        await srv.stop()

    asyncio.run(scenario())
