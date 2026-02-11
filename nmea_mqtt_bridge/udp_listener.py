"""Async UDP listener for NMEA data streams."""

import asyncio
import logging
import sys
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class NMEAProtocol(asyncio.DatagramProtocol):
    """UDP datagram protocol handler for NMEA data."""

    def __init__(self, source_name: str, callback: Callable[[str, str, str], None]):
        """Initialize protocol handler.

        Args:
            source_name: Identifier for this UDP source.
            callback: Called with (source_name, sender_ip, raw_sentence) for each NMEA sentence.
        """
        self.source_name = source_name
        self.callback = callback
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport
        logger.info("UDP listener '%s' ready", self.source_name)

    def datagram_received(self, data: bytes, addr: tuple):
        sender_ip = addr[0]
        try:
            text = data.decode("ascii", errors="ignore").strip()
        except Exception:
            return

        if not text:
            return

        # A single UDP packet may contain multiple NMEA sentences
        for line in text.split("\n"):
            line = line.strip()
            if line and (line.startswith("$") or line.startswith("!")):
                # Clean up any stray non-printable chars
                clean = "".join(c for c in line if 32 <= ord(c) < 127)
                if clean:
                    self.callback(self.source_name, sender_ip, clean)

    def error_received(self, exc: Exception):
        logger.error("UDP error on '%s': %s", self.source_name, exc)

    def connection_lost(self, exc: Optional[Exception]):
        if exc:
            logger.warning("UDP connection lost on '%s': %s", self.source_name, exc)


class UDPListener:
    """Manages multiple async UDP listeners for NMEA data."""

    def __init__(self):
        self.transports: list[asyncio.DatagramTransport] = []
        self._callback: Optional[Callable] = None

    def set_callback(self, callback: Callable[[str, str, str], None]):
        """Set the callback function for received NMEA sentences.

        Args:
            callback: Called with (source_name, sender_ip, raw_sentence).
        """
        self._callback = callback

    async def start(
        self,
        sources: list[dict],
        bind_address: str = "0.0.0.0",
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        """Start UDP listeners for all configured sources.

        Args:
            sources: List of source dicts with 'name', 'port', 'enabled' keys.
            bind_address: Address to bind listeners on.
            loop: Event loop (defaults to running loop).
        """
        if not self._callback:
            raise RuntimeError("No callback set. Call set_callback() first.")

        if loop is None:
            loop = asyncio.get_running_loop()

        for source in sources:
            if not source.get("enabled", True):
                logger.info("Skipping disabled source: %s", source["name"])
                continue

            port = source["port"]
            name = source["name"]
            desc = source.get("description", "")

            try:
                # reuse_port is only supported on Linux/BSD, not Windows
                reuse = sys.platform != "win32"
                transport, _ = await loop.create_datagram_endpoint(
                    lambda n=name: NMEAProtocol(n, self._callback),
                    local_addr=(bind_address, port),
                    reuse_port=reuse,
                )
                self.transports.append(transport)
                logger.info(
                    "Listening on %s:%d [%s] - %s",
                    bind_address,
                    port,
                    name,
                    desc,
                )
            except OSError as e:
                logger.error(
                    "Failed to bind %s:%d [%s]: %s", bind_address, port, name, e
                )

        if not self.transports:
            raise RuntimeError("No UDP listeners could be started")

        logger.info("Started %d UDP listener(s)", len(self.transports))

    async def stop(self):
        """Stop all UDP listeners."""
        for transport in self.transports:
            transport.close()
        self.transports.clear()
        logger.info("All UDP listeners stopped")
