# virtual-flex

A **virtual FlexRadio**. It impersonates a FLEX‑6000/8000 on the LAN so a
non‑Flex rig — an Elecraft K4, or anything [Hamlib](https://hamlib.github.io/)
supports — can drive the **4O3A PGXL / TGXL / AGXL** stack automatically, as if
the rig were a Flex.

```
 ┌──────────┐  hamlib CAT (rigctld)  ┌───────────────┐  emulated Flex API   ┌───────────────┐
 │  K4D /   │ ─────────────────────► │  virtual-flex │ ── UDP discovery ──► │  4O3A stack   │
 │ any rig  │   freq / mode / TX     │    daemon     │ ── TCP :4992 ──────► │ PGXL/TGXL/AGXL │
 └──────────┘                        └───────────────┘   slice status       └───────────────┘
```

## Why

The 4O3A "Genius" stack follows a FlexRadio over the LAN: the **PGXL is a
non‑GUI client** that discovers the radio, registers itself as an amplifier, and
subscribes to slice frequency/mode/TX so it can pre‑select band filters. This
daemon provides the *server* half of that conversation, fed by a real rig.

Actual keying stays on the **hardwired PTT line** — per FlexRadio's PGXL API
docs, *"the amplifier will not enable PTT via the LAN mechanism if paired with a
FLEX transceiver."* The LAN link is band/frequency data only. So you keep your
existing RCA PTT cable; this just replaces the (buggy) serial‑CAT band‑data path
with a clean network Flex pairing.

## Status

Phase 1–2 (bring‑up): discovery broadcast, TCP handshake, and the
amplifier/meter/interlock/keepalive object registration the PGXL performs on
connect, plus slice status streaming. Fed by a **sim** source today; the
**hamlib** source (K4 via rigctld) is written but not yet validated on hardware.

Two things are marked to confirm against a real FLEX‑8600 packet capture:
the discovery UDP port (4992 vs 4991) and the exact discovery field strings /
`amplifier create` response format. Search the code for `confirm` / `capture`.

## Requirements

Python **3.11+** (stdlib only — `asyncio` + `tomllib`, no third‑party deps).

## Run

```bash
cp config.example.toml config.toml   # then edit: set radio.serial to match the PGXL pairing
python -m virtualflex --config config.toml --log-level DEBUG
```

With no real radio, the default `sim` source advertises a static 20 m frequency;
set `[rig.sim] sweep_hz_per_sec` to watch the stack follow a moving frequency.

To follow a real K4 over Ethernet CAT, start rigctld first, then switch the
source to `hamlib`:

```bash
rigctld -m <K4_model> -r <k4_ip>:9200 -t 4532     # find <K4_model> via: rigctl -l | grep -i K4
# set [rig] source = "hamlib" in config.toml
```

## Test

```bash
pip install pytest && pytest
```

## Layout

| File | Role |
|------|------|
| `virtualflex/vita49.py`   | VITA‑49 discovery packet builder |
| `virtualflex/discovery.py`| UDP discovery broadcaster |
| `virtualflex/server.py`   | TCP command/status server (:4992) |
| `virtualflex/protocol.py` | Per‑client handshake + command dispatch |
| `virtualflex/state.py`    | Shared radio state (slices, objects, clients) |
| `virtualflex/rigsource/`  | Rig data sources: `sim`, `hamlib` |
| `virtualflex/config.py`   | TOML config + defaults |
