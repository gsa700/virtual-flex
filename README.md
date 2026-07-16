# virtual-flex

A **virtual FlexRadio**. It impersonates a FLEX‑8600 on the LAN so an **Elecraft
K4/K4D** drives the **4O3A PGXL / TGXL / AGXL** stack automatically, as if the K4
were a Flex. Band‑follow **and keying**, over the network, no station wiring — and
no hamlib.

```
 ┌──────────┐   native K4 CAT (:9200)   ┌───────────────┐  emulated Flex API   ┌───────────────┐
 │   K4 /   │ ── freq/mode/split ─────► │  virtual-flex │ ── UDP discovery ──► │  4O3A stack   │
 │   K4D    │ ── TQX fast PTT ────────► │  (supervisor) │ ── TCP :4992 ──────► │ PGXL/TGXL/AGXL │
 └──────────┘        one socket         └───────────────┘   slice/transmit/    └───────────────┘
                                                            interlock status
```

## Status: working

Shipped as **v0.2.0** and validated end‑to‑end against a real K4D **and** a real
4O3A PGXL/TGXL/AGXL stack (cross‑checked against a genuine FLEX‑8600) — including
a clean install from a bare Debian image:

- **Band‑follow** — all three boxes track the K4's frequency/mode (split follows VFO B).
- **LAN keying** — the whole stack keys over LAN, including the amp, via the
  emulated interlock handshake (`PTT_REQUESTED → TRANSMITTING`, amp handle in
  `amplifier=`). No RCA/keyline required.
- **Safe failover** — when the K4 powers off, virtual‑flex disappears like a real
  Flex would, so the **AGXL reverts to its configured "no transceiver" antenna**.
  Assign that to a dummy load (or a grounded port) and losing the radio parks the
  station there automatically — e.g. for lightning safety.
- **Fast recovery** — on K4 power‑up the stack reconnects within a couple of
  seconds; in on‑air use it's indistinguishable from a real FLEX‑8600 coming back.
- **Quiet on the network** — one CAT socket to the K4, addressed by IP, so
  steady‑state DNS traffic is zero (no repeated `.local` lookups).

## How it works

The 4O3A boxes are non‑GUI **clients** of the radio's TCP port; this daemon is the
**server** half. It answers discovery, handles the amplifier/meter/interlock
registration each box performs on connect, and streams the objects they consume
(formats captured from a real FLEX‑8600):

- `slice` — RF_frequency, mode, tx‑slice designation (the tuner/switch follow this)
- `transmit` — `freq=` / `tx_slice_mode=` (**the amp reads its band from here**)
- `interlock` — the TX state machine `READY → PTT_REQUESTED → TRANSMITTING → UNKEY_REQUESTED → READY`

Everything is sourced **natively from the K4's CAT port over a single socket** —
auto‑info (`AI2`) makes the K4 **push** `FA/FB/FT/MD` changes the instant they
happen (frequency/mode/split), with a fast `TQX` poll for low‑latency PTT.
Runtime updates go out as **terse deltas** (only the changed keys) through a
**50 ms pacing buffer**, so the stack sees an even, Flex‑like stream instead of
1 KB dumps — the Genius boxes' embedded parsers can't keep up with the latter.
A **presence supervisor** owns the lifecycle: while the K4 is reachable it
advertises and serves the stack; when the K4 goes absent it drops discovery and
every stack connection, so each 4O3A box reverts to its configured "no
transceiver" antenna.

## Requirements

- Python **3.11+** (stdlib only — `asyncio` + `tomllib`, **no third‑party deps, no hamlib**)
- An Elecraft **K4/K4D** with its Ethernet CAT port reachable
- A host on the **same L2 subnet** as the 4O3A stack (discovery is a UDP
  broadcast — bridge the VM/LXC/Pi NIC onto that LAN, don't route to it)

## Install (Debian/Ubuntu — VM, LXC, or Pi)

Each version tag publishes a **`.deb`** and a source **`.zip`** on the
[Releases](https://github.com/gsa700/virtual-flex/releases) page.

```bash
sudo apt install ./virtual-flex_<version>_all.deb   # depends only on python3 (>= 3.11)
sudo virtual-flex setup                             # interactive: finds your K4, writes config, starts it
```

`virtual-flex setup` resolves your K4 by serial over mDNS (or takes an IP),
auto‑detects the subnet broadcast, **pins** the advertised Flex serial so a K4
rename can never force a stack re‑pair, writes `/etc/virtual-flex/config.toml`,
and offers to enable + start the service. Re‑run it any time to change settings —
no TOML editing. Then pair the 4O3A boxes to the serial it prints.

Watch it: `journalctl -u virtual-flex -f`.

### Updating

```bash
sudo virtual-flex update            # fetch + install the latest release, restart if running
virtual-flex update --check         # just report whether an update exists
```

Your config is untouched by updates (it's generated, not packaged), and the
service is only restarted if it was already running.

## Run from source (dev / other platforms)

```bash
python -m virtualflex setup                          # or hand-write config.toml from config.example.toml
python -m virtualflex --config config.toml --log-level INFO
```

## Configuration

The wizard writes a minimal `/etc/virtual-flex/config.toml`; everything it omits
(ports, poll intervals, presence debounce) inherits built‑in defaults, so future
default improvements apply without re‑running setup. See `config.example.toml`
for the full set of keys.

The K4 is addressed by **cached IP** (zero steady‑state DNS). Its
`K4-SN<serial>.local` name is kept as identity and an **IP self‑heal** hook: if
the cached IP ever stops answering (e.g. DHCP moved it), virtual‑flex re‑resolves
the name once via a self‑contained unicast‑mDNS query and reconnects — so DHCP
installs recover on their own, and reserved‑IP installs never touch DNS at all.

## Keying & PTT

LAN keying works for the whole stack, but there's an unavoidable nuance: a real
Flex is the **exciter** and holds its own RF until the stack reports ready
(closed‑loop, zero gap). The K4 emits RF on its own schedule and doesn't listen
for confirmation, so we detect its key a few ms late — leaving a small blind spot
at key‑onset (a brief TGXL "No PTT" flash). It's benign: the PGXL won't pass RF to
its output until its own relays are set regardless of trigger, so blind LAN keying
doesn't hot‑switch the amp.

| Approach | Wire‑free? | Closes the loop? | Works for all keying? |
|---|---|---|---|
| LAN keying (current) | ✅ | ✗ (few‑ms blind spot) | ✅ |
| PGXL PTT‑OUT → K4 TX‑INHIBIT | ✗ (one wire) | ✅ | ✅ |
| CAT‑sequenced PTT (`TX;`) | ✅ | ✅ | ✗ software‑PTT only |

The wire‑free LAN path is the intended product; the flash is the accepted cost.

## Layout

| File | Role |
|------|------|
| `virtualflex/supervisor.py` | Presence state machine: K4 present → serve; absent → tear down (stack reverts to its no-transceiver antenna) |
| `virtualflex/k4.py`         | Native K4 CAT client — freq/mode/split + fast PTT on one socket |
| `virtualflex/mdns.py`       | Self‑contained unicast‑mDNS resolver (IP self‑heal) |
| `virtualflex/discovery.py`  | VITA‑49 discovery broadcaster |
| `virtualflex/vita49.py`     | VITA‑49 discovery packet builder |
| `virtualflex/server.py`     | TCP command/status server (:4992) |
| `virtualflex/protocol.py`   | Per‑client handshake + command dispatch |
| `virtualflex/state.py`      | Radio state: slice / transmit / interlock objects |
| `virtualflex/setup.py`      | `virtual-flex setup` config wizard |
| `virtualflex/config.py`     | TOML config + defaults |

## Test

```bash
pip install pytest && pytest
```
