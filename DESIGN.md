# virtual-flex — architecture

*Shipped in v0.2.0.* The tightest, most transparent Elecraft **K4/K4D ↔
FlexRadio** integration for the 4O3A Genius stack (PGXL / TGXL / AGXL). Pure K4.
**No hamlib, no rigctld, no external rig dependency.** Support for other radios
would live in separate forks of this codebase, not behind abstraction layers here.

## Principles
- One process; one connection to the K4's network CAT (port 9200); stdlib only.
- The virtual radio mirrors a **real Flex's presence** — it exists on the network
  only while the K4 does.
- **Zero steady-state DNS.** The K4 is reached by a cached IP; its
  `K4-SN<serial>.local` name is the durable identity and an IP-refresh
  mechanism, never a per-connect lookup.

## Presence-driven state machine (the core)
The supervisor owns everything and is driven by K4 reachability:

- **K4 PRESENT** → broadcast VITA-49 discovery, accept/serve the Genius stack,
  stream freq / mode / split / PTT from the K4 CAT.
- **K4 ABSENT** → **stop discovery AND drop all stack TCP connections**, so the
  stack sees the radio vanish (exactly like a real Flex powering off) and each box
  **reverts to its configured "no transceiver" antenna**. Set the AGXL's to a
  dummy load (or a grounded port) and losing the radio parks the station there —
  e.g. for lightning safety. Then poll for the K4's return.

Debounce: the K4 must be gone `absent_after` s before teardown and present
`present_after` s before advertising, so a brief blip doesn't chatter the AGXL
relays. Reconnect uses a short fixed poll with a bounded connect timeout, so
power-up recovery is a couple of seconds (a dead host would otherwise stall the
connect on SYN-retransmit).

> SAFETY: keeping a fake radio "present" while the K4 is off *defeats* the
> stack's no-transceiver failover. Presence teardown is a safety requirement, not
> polish. (v0.1.x had this regression; v0.2 fixed it.)

## K4 addressing & IP changes (no DNS hammering)
Identity = the K4 hostname/serial (`K4-SN<serial>`, stable by Elecraft design).
Address = the IP, cached in config.

- **Steady state:** connect to the cached IP. Zero DNS.
- **Cached IP stops answering** (DHCP moved the K4): the connection fails, which
  triggers a **single** mDNS re-resolve of `K4-SN<serial>.local`, updating the
  cache and reconnecting. DHCP installs self-heal without a steady DNS stream.
- **K4 truly absent:** resolve returns nothing → supervisor tears down + retries.

The resolve uses a **one-shot mDNS query with the unicast-response (QU) bit set**,
so the K4 answers straight back to our ephemeral socket. This avoids both the
`SOA local` unicast-DNS leak that plagued v0.1.x *and* any conflict with the
system avahi on :5353 — we own the whole resolution path. Validated live: it
resolves the K4 on a bare Debian with **no avahi/libnss-mdns installed**.

## Config & install
The install wizard (`sudo virtual-flex setup`) writes a minimal
`/etc/virtual-flex/config.toml`; anything it omits inherits the built-in defaults
in `config.py`. It finds the hardware itself: Enter at the serial prompt scans
the /24 for radios with the CAT port open and reads each hit's serial over CAT
(`SN;`); a typed serial (zero-padded) does a targeted mDNS resolve instead. It
then scans for the Genius boxes' management ports (9007 AGXL / 9008 PGXL /
9010 TGXL — all three live-confirmed) and offers the found IPs as the
unicast-discovery default. It auto-detects the /24 subnet broadcast, **pins**
the derived Flex serial (`radio.serial`, so a K4 rename can never force a stack
re-pair), and offers to enable + start the service. Re-running setup pre-fills
every prompt from the existing config ('none' clears the unicast list, since
blank means keep).

Meaningful keys: `radio.serial`/`radio.nickname`/`radio.callsign`,
`network.broadcast_address`, `k4.ip` (cached address), `k4.hostname` (identity +
mDNS self-heal). The `.deb` depends only on `python3 (>= 3.11)` and ships a
`/usr/bin/virtual-flex` wrapper so the wizard is on PATH, plus a man page
(`deploy/pkg/virtual-flex.1` → `/usr/share/man/man1/`); `--help` documents the
setup/update commands (they dispatch before argparse, so the epilog carries
them). The config is generated, not a dpkg conffile, so upgrades never prompt
or clobber it.

## Module layout
    __main__.py    entry: `setup` subcommand -> wizard; else load config -> Supervisor
    supervisor.py  presence state machine (present / absent, debounce)
    k4.py          native K4 CAT client: connect-by-IP; AI2 push mode for
                   FA/FB/FT/MD (event-driven dial follow, slow poll = resync
                   only), fast TQX poll for PTT; mDNS IP-refresh on failure
    mdns.py        one-shot unicast (QU) mDNS resolver, K4-SN*.local -> IP
    setup.py       `virtual-flex setup` config wizard
    update.py      `virtual-flex update` self-updater (GitHub latest release -> apt)
    state.py       Flex object model (radio/slice/interlock/transmit); runtime
                   changes emit terse deltas (changed keys only) through a 50 ms
                   pacing buffer — full dumps only at subscribe/structural changes
                   (fast-poll hybrid tried live: stale interleaves = jerky follow)
    protocol.py    per-client handshake + Genius command/status dispatch
    server.py      TCP listener (:4992), start/stop with presence
    discovery.py   VITA-49 discovery broadcaster
    vita49.py      VITA-49 packet builder
    config.py      TOML config + defaults; K4-hostname -> Flex-serial derivation

**Not present (removed from the v0.1 lineage):** `rigsource/` (hamlib / rigctld /
sim) and the standalone `ptt.py` (folded into `k4.py`). No `libhamlib-utils`
dependency, no rigctld systemd unit. Tests use a mock K4 CAT server.

## GUI clients (Maestro / SmartSDR)
The discovery card carries the full 8600-style field set — a Maestro-class GUI
client parses far more of it than the Genius boxes do, and missing keys wedged
the 8600M's built-in panel at "please wait..." during its boot-time radio scan.
We also advertise as a **single-seat radio whose seat is taken** (station
"K4D-Bridge") with **`status=In_Use`** + the `inuse_ip`/`inuse_host` fields
populated — `status` is the field SmartSDR's picker actually prints, and with
it the radio lists as "In Use" rather than "Available (MultiFLEX)". The Genius
boxes ignore all of it (verified: they pair, follow, and key with In_Use on
the air).

If an operator connects anyway, nothing breaks: they get slice/transmit status
but no panadapter/DAX streams (an empty radio), and the Genius connections are
unaffected. SmartSDR's "Disconnect" sends `client disconnect` for the advertised
station handle — a no-op here, since that station is a fixture of the discovery
card, not a real connection. The picker keeps showing K4D-Bridge seated: the
occupant can't be kicked, by design. (Verified live against SmartSDR while the
stack streamed on 80 m.)

## Possible future work
- **CAT-sequenced PTT** (route software PTT through the bridge → interlock →
  `TX;`) to close the keying loop wire-free for software-initiated modes.
- **Passive mDNS-announcement listener** to detect K4 power-up the instant it
  announces, trimming the last couple seconds off recovery.
- **Non-K4 rigs** via a downstream fork that re-adds a rig-source abstraction.
