"""virtual-flex: impersonate a FlexRadio so an Elecraft K4/K4D drives the
4O3A PGXL/TGXL/AGXL stack over the LAN — band-follow and keying, no hamlib.

The amplifier is a non-GUI *client* of the radio's TCP command port; this
package is the *server* half. It answers discovery, accepts the connection,
handles the amplifier/meter/interlock registration the PGXL performs on connect,
and streams slice frequency/mode/TX sourced natively from the K4's CAT port. A
presence supervisor tears the whole thing down when the K4 is absent, so the
stack reverts to its no-transceiver antenna, like a real Flex powering off.
"""

__version__ = "0.2.1"
