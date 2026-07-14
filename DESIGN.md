# virtual-flex v0.2 — design

The tightest, most transparent Elecraft **K4/K4D ↔ FlexRadio** integration for the
4O3A Genius stack (PGXL / TGXL / AGXL). Pure K4. **No hamlib, no rigctld, no
external rig dependency.** Support for other radios is expected to live in
separate forks of this codebase, not behind abstraction layers here.

## Principles
- One process; one connection to the K4's network CAT (port 9200); stdlib only.
- The virtual radio mirrors a **real Flex's presence** — it exists on the network
  only while the K4 does.
- **Zero steady-state DNS.** The K4 is reached by a cached IP; its
  `K4-SN<serial>.local` name is the durable identity and an IP-refresh
  mechanism, never a per-connect lookup.

## Presence-driven state machine (the core)
A supervisor owns everything and is driven by K4 reachability:

- **K4 PRESENT** → broadcast VITA-49 discovery, accept/serve the Genius stack,
  stream freq / mode / split / PTT from the K4 CAT.
- **K4 ABSENT** → **stop discovery AND drop all stack TCP connections**, so the
  stack sees the radio vanish (exactly like a real Flex powering off) and the
  **AGXL fails over to Dummy Load — grounding antenna inputs for lightning
  safety**. Then poll for the K4's return, backed off.

Debounce: the K4 must be gone ~N s before teardown and present ~M s before
advertising, so a brief blip doesn't chatter the AGXL relays.

> SAFETY: keeping a fake radio "present" while the K4 is off *defeats* the
> stack's dummy-load failover. Presence teardown is a safety requirement, not
> polish. (v0.1.x has this regression; v0.2 fixes it.)

## K4 addressing & IP changes (no DNS hammering)
Identity = the K4 hostname/serial (`K4-SN<serial>`, stable by Elecraft design).
Address = the IP, cached in config.

- **Steady state:** connect to the cached IP. Zero DNS.
- **Cached IP stops answering** (DHCP moved the K4): the connection fails, which
  triggers a **single** mDNS re-resolve of `K4-SN<serial>.local`, updating the
  cache and reconnecting. DHCP installs self-heal without a steady DNS stream.
- **K4 truly absent:** resolve returns nothing → supervisor tears down + backs off.

The failure-time resolve uses a **one-shot mDNS query with the unicast-response
(QU) bit set**, so the K4 answers straight back to our ephemeral socket. This
avoids both the `SOA local` unicast-DNS leak that plagued v0.1.x *and* any
conflict with the system avahi on :5353. We own the whole resolution path.
(Implementation note: must honor the QU bit; validate against a live K4.)

## Config (written by the install wizard; no hand-editing)
- `k4.serial` / `k4.hostname` — identity; pins the advertised Flex serial
- `k4.ip` — cached address, self-refreshed on failure
- `k4.cat_port` = 9200
- `network.broadcast` — auto-detected subnet broadcast
- `radio.nickname`, antenna mapping, etc.

Install wizard: mDNS-scan for `K4-SN*.local` (lists multiple K4s by serial),
user picks one, resolve to IP once, write config, pin the serial. Delivered via
debconf or a `virtual-flex setup` TUI so users never edit text files.

## Module layout
    __main__.py    entry: load config → Supervisor.run()
    supervisor.py  presence state machine (present / absent, debounce)   [NEW]
    k4.py          native K4 CAT client: connect-by-IP, poll FA/FB/MD/IF/TQX,
                   expose freq/mode/split/ptt; trigger mDNS refresh on failure  [NEW]
    mdns.py        one-shot unicast (QU) mDNS resolver, K4-SN*.local → IP   [NEW]
    state.py       Flex object model (radio/slice/interlock/transmit)   [from v0.1]
    protocol.py    Genius command/status server                         [from v0.1, trim]
    server.py      TCP listener                                         [from v0.1]
    discovery.py   VITA-49 discovery broadcaster                        [from v0.1]
    vita49.py      VITA-49 packet builder                               [from v0.1]

**Dropped from v0.1:** all of `rigsource/` (hamlib / rigctld / sim) and the
standalone `ptt.py` (folded into `k4.py`). No `libhamlib-utils` dependency, no
rigctld systemd unit. Tests use a mock K4 CAT server in place of the old sim.

## Build order
1. `k4.py` + `mdns.py` + `supervisor.py` — native path + presence/safety.
   Verify the **AGXL drops to Dummy Load** when the K4 is powered off.
2. Wire the trimmed `protocol` / `state` / `discovery` onto the supervisor;
   confirm full stack follow + keying against the live rig.
3. Install wizard + config persistence.

Keep v0.1.3 running on the station as the fallback; cut **v0.2.0** only when all
three are verified end-to-end.
