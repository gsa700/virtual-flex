# virtual-flex

A **virtual FlexRadio**. It impersonates a FLEX‑6000/8000 on the LAN so a
non‑Flex rig — an Elecraft K4, or anything [Hamlib](https://hamlib.github.io/)
supports — drives the **4O3A PGXL / TGXL / AGXL** stack automatically, as if the
rig were a Flex. Band‑follow **and keying**, over the network, no station wiring.

```
 ┌──────────┐  hamlib CAT (freq/mode)  ┌───────────────┐  emulated Flex API   ┌───────────────┐
 │  K4D /   │ ───────────────────────► │  virtual-flex │ ── UDP discovery ──► │  4O3A stack   │
 │ any rig  │  direct CAT (TX detect)  │    daemon     │ ── TCP :4992 ──────► │ PGXL/TGXL/AGXL │
 └──────────┘ ───────────────────────► └───────────────┘   slice/transmit/    └───────────────┘
                                                            interlock status
```

## Status: working

Validated end‑to‑end against a real K4D **and** a real 4O3A PGXL/TGXL/AGXL stack
(cross‑checked against a genuine FLEX‑8600):

- **Band‑follow** — all three boxes track the rig's frequency/mode.
- **LAN keying** — the whole stack keys over LAN, including the amp, via the
  emulated interlock handshake (`PTT_REQUESTED → TRANSMITTING`, with the amp's
  handle in `amplifier=`). No RCA/keyline required.

The one cosmetic artifact: a brief "No PTT" flash on the TGXL at key‑onset —
see [Keying & PTT](#keying--ptt).

## How it works

The 4O3A boxes are non‑GUI **clients** of the radio's TCP port. This daemon is
the **server** half: it answers discovery, handles the amplifier/meter/interlock
object registration each box performs on connect, and streams the objects they
consume. The key ones (formats captured from a real FLEX‑8600):

- `slice` — RF_frequency, mode, tx‑slice designation (the tuner/switch follow this)
- `transmit` — `freq=` / `tx_slice_mode=` (**the amp reads its band from here**)
- `interlock` — the TX state machine `READY → PTT_REQUESTED → TRANSMITTING → UNKEY_REQUESTED → READY`

Frequency/mode come from Hamlib (portable to any rig). Transmit is detected on a
**separate, direct CAT connection** to the K4 (`TQX;` fast‑poll), independent of
the slower freq/mode loop, so keying latency isn't tied to it.

## Requirements

- Python **3.11+** (stdlib only — `asyncio` + `tomllib`, no third‑party deps)
- [Hamlib](https://hamlib.github.io/) (`rigctld`) for the frequency/mode path
- An Elecraft K4 for the native TX‑detection path (other rigs: fall back to
  Hamlib PTT — not yet implemented)
- On Linux, `libnss-mdns` + `avahi-daemon` to reach the K4 by its
  `K4-SN<serial>.local` mDNS name instead of an IP (the `.deb` pulls these in;
  the name is DHCP‑proof). Windows resolves `.local` natively.

## Run

The daemon needs `rigctld` running for freq/mode. For the K4D (Hamlib model
**2047**) over its Ethernet CAT port:

```bash
# Terminal 1 — bridge the K4 to rigctld
"C:\Program Files\hamlib-w64-4.7.2\bin\rigctld.exe" -m 2047 -r K4-SN<serial>.local:9200 -t 4532

# Terminal 2 — the virtual radio
cd path/to/virtual-flex
python -m virtualflex --config config.toml --log-level INFO
```

Then in the 4O3A utilities, pair each box's FlexRadio to the serial in
`config.toml` (`radio.serial`). With the default `serial = "auto"`, virtual-flex
derives that serial from the K4's hostname (`K4-SN01234` → `8600-0000-0000-1234`)
and logs it at startup — pair the stack to whatever it logs. Pin an explicit
serial once paired so a later K4 rename can't change it (re-pairing is keyed to
the serial). Config lives in `config.toml` (copy from `config.example.toml`); it
selects the rig source (`hamlib`) and the PTT source (`k4cat`, pointed at the
K4's CAT host).

For a bench test with no radio, set `[rig] source = "sim"` and `[ptt] source =
"none"`.

## Deploy (always-on)

To run it as boot-persistent systemd services on a Debian 12+ box (VM, LXC, or
Pi) that shares the 4O3A stack's subnet:

```bash
git clone https://github.com/gsa700/virtual-flex ~/virtual-flex
cd ~/virtual-flex
K4_HOST=K4-SN<serial>.local BROADCAST_ADDR=<your subnet bcast> sudo -E bash deploy/install.sh
```

It installs Hamlib and an mDNS resolver, generates `config.toml`, writes the
`rigctld` + `virtual-flex` services, and enables them. Addressing the K4 by its
`K4-SN<serial>.local` name means no static IP or DHCP reservation — it resolves
over mDNS wherever the K4 lands. **The host must be on the same L2 segment as the
stack** — discovery is a UDP broadcast, so bridge the VM/LXC NIC onto that LAN
(don't route to it). See `deploy/install.sh` for all overridable settings.

### If mDNS doesn't resolve (IP fallback)

Some networks block multicast (isolated VLANs, certain APs / guest networks), so
`K4-SN<serial>.local` may not resolve. Check on the host:

```bash
getent hosts K4-SN<serial>.local     # should print the K4's IP
```

If it's empty even with `libnss-mdns` + `avahi-daemon` installed, just use the
K4's **IP** anywhere a host is expected — the installer, `K4_HOST`, `rigctld.env`,
and `config.toml` all take an IP interchangeably. A DHCP reservation keeps it
stable:

```bash
K4_HOST=<your-K4-IP> sudo -E bash deploy/install.sh   # or edit /etc/virtual-flex/rigctld.env + config.toml
```

## Releases

Each version tag publishes a **`.deb`** and a source **`.zip`** on the
[Releases](https://github.com/gsa700/virtual-flex/releases) page.

**Debian/Ubuntu (VM, LXC, Pi):**
```bash
sudo apt install ./virtual-flex_<version>_all.deb   # pulls python3, libhamlib-utils, libnss-mdns, avahi
sudoedit /etc/virtual-flex/rigctld.env              # set K4_HOST (K4-SN<serial>.local), RIG_MODEL
sudoedit /etc/virtual-flex/config.toml              # serial, broadcast, ptt K4 host
sudo systemctl start virtual-flex-rigctld virtual-flex
```

**Windows / anything else:** download the `.zip`, install Python 3.11+ and Hamlib
yourself, then run as in [Run](#run).

**Cutting a release (maintainer):** the workflow builds and publishes both assets
on a version tag —
```bash
git tag v0.1.0 && git push --tags
```

Build the artifacts locally with `bash deploy/build-deb.sh` / `bash deploy/build-zip.sh`.

## Keying & PTT

LAN keying works for the whole stack, but there's an unavoidable nuance: a real
Flex is the **exciter** and holds its own RF until the stack reports ready
(closed‑loop, zero gap). The K4 emits RF on its own fixed 25 ms schedule and
doesn't listen for confirmation, so we detect its key a few ms late and relay it
— leaving a small blind spot at key‑onset (the TGXL "No PTT" flash). It's benign:
the PGXL won't pass RF to its output until its own relays are set regardless of
trigger, so blind LAN keying doesn't hot‑switch the amp.

Closing that gap costs one of the things this project set out to avoid:

| Approach | Wire‑free? | Closes the loop? | Works for all keying? |
|---|---|---|---|
| LAN keying (current) | ✅ | ✗ (few‑ms blind spot) | ✅ |
| PGXL PTT‑OUT → K4 TX‑INHIBIT | ✗ (one wire) | ✅ | ✅ |
| CAT‑sequenced PTT (`TX;`) | ✅ | ✅ | ✗ software‑PTT only |

The wire‑free LAN path is the intended product; the flash is the accepted cost.
A future **CAT‑sequenced PTT** mode (route software PTT through the bridge →
interlock → `TX;`) would close the loop wire‑free for software‑initiated PTT
(WSJT-X, etc.), but not for mic PTT or a CW paddle.

## Layout

| File | Role |
|------|------|
| `virtualflex/vita49.py`   | VITA‑49 discovery packet builder |
| `virtualflex/discovery.py`| UDP discovery broadcaster |
| `virtualflex/server.py`   | TCP command/status server (:4992) |
| `virtualflex/protocol.py` | Per‑client handshake + command dispatch |
| `virtualflex/state.py`    | Radio state: slice / transmit / interlock objects |
| `virtualflex/ptt.py`      | Direct‑CAT K4 transmit detection (`TQX;`) |
| `virtualflex/rigsource/`  | Rig data sources: `sim`, `hamlib` |
| `virtualflex/config.py`   | TOML config + defaults |

## Test

```bash
pip install pytest && pytest
```
