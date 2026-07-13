"""virtual-flex: impersonate a FlexRadio so a hamlib-driven rig can drive the
4O3A PGXL/TGXL/AGXL stack over the LAN.

The amplifier is a non-GUI *client* of the radio's TCP command port; this
package is the *server* half — it answers discovery, accepts the connection,
handles the amplifier/meter/interlock object registration the PGXL performs on
connect, and streams slice frequency/mode/TX status sourced from a real rig.
"""

__version__ = "0.1.0"
