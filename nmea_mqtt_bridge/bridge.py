"""Main bridge orchestrator - connects UDP listeners to MQTT publisher."""

import asyncio
import logging
import time
from typing import Any, Optional

from .ais_decoder import AISDecoder
from .mqtt_publisher import MQTTPublisher, SENSOR_DEFINITIONS
from .nmea_parser import NMEAData, parse_sentence
from .udp_listener import UDPListener

logger = logging.getLogger(__name__)

# Maps NMEA sentence types to throttle categories
SENTENCE_THROTTLE_MAP = {
    "GGA": "position",
    "VTG": "speed",
    "HDT": "heading",
    "HDG": "heading",
    "DPT": "depth",
    "MTW": "environment",
    "VHW": "speed",
    "RSA": "rudder",
    "GSV": "satellites",
    "ZDA": "position",
    "AIS": "ais",
}


class NMEABridge:
    """Orchestrates NMEA UDP reception and MQTT publishing."""

    def __init__(self, config: dict):
        """Initialize the bridge.

        Args:
            config: Full configuration dictionary.
        """
        self.config = config
        self.udp_listener = UDPListener()
        self.mqtt_publisher = MQTTPublisher(
            config.get("mqtt", {}),
            config.get("device", {}),
        )

        # Throttle tracking: category -> last publish timestamp
        self._last_publish: dict[str, float] = {}
        self._throttle_config = config.get("sensors", {}).get("throttle", {})

        # Device tracker config
        self._device_tracker_enabled = (
            config.get("sensors", {}).get("device_tracker", {}).get("enabled", True)
        )

        # AIS decoder
        ais_config = config.get("ais", {})
        self.ais_decoder = AISDecoder(
            vessel_timeout=ais_config.get("vessel_timeout", 600),
        )
        self._ais_cleanup_interval = ais_config.get("cleanup_interval", 60)
        self._last_ais_cleanup = 0.0
        self._last_ais_vessel_count = -1

        # Current state - accumulated from multiple sentences
        self._state: dict[str, Any] = {}

        # Shutdown event
        self._stop_event: Optional[asyncio.Event] = None

        # Stats
        self._stats = {
            "sentences_received": 0,
            "sentences_parsed": 0,
            "sentences_published": 0,
            "errors": 0,
        }
        self._stats_interval = 60  # Log stats every 60 seconds
        self._last_stats_log = 0.0

    def _on_nmea_received(self, source_name: str, sender_ip: str, raw: str):
        """Callback for received NMEA sentences from UDP listeners.

        Args:
            source_name: Name of the UDP source that received the data.
            sender_ip: IP address of the sender.
            raw: Raw NMEA sentence string.
        """
        self._stats["sentences_received"] += 1

        # Parse the sentence
        data = parse_sentence(raw)
        if data is None:
            return

        self._stats["sentences_parsed"] += 1

        # Check throttle
        category = SENTENCE_THROTTLE_MAP.get(data.sentence_type, "position")
        throttle_seconds = self._throttle_config.get(category, 5)
        now = time.monotonic()
        last = self._last_publish.get(category, 0)

        if now - last < throttle_seconds:
            return

        self._last_publish[category] = now

        # Handle AIS separately
        if data.sentence_type == "AIS" and data.ais_messages:
            for msg in data.ais_messages:
                # Publish raw message
                self.mqtt_publisher.publish_ais(msg)

                # Decode and track vessel
                result = self.ais_decoder.decode_message(msg)
                if result is not None:
                    vessel, is_new = result
                    if vessel.latitude is not None and vessel.longitude is not None:
                        self.mqtt_publisher.publish_ais_vessel(vessel, is_new)

                    # Update vessel count if changed
                    count = self.ais_decoder.vessel_count
                    if count != self._last_ais_vessel_count:
                        self.mqtt_publisher.publish_ais_vessel_count(count)
                        self._last_ais_vessel_count = count

            # Periodic cleanup of stale vessels
            now = time.monotonic()
            if now - self._last_ais_cleanup > self._ais_cleanup_interval:
                self._last_ais_cleanup = now
                stale = self.ais_decoder.cleanup_stale_vessels()
                for mmsi in stale:
                    self.mqtt_publisher.remove_ais_vessel(mmsi)
                    logger.info("Removed stale AIS vessel MMSI %d", mmsi)
                if stale:
                    self.mqtt_publisher.publish_ais_vessel_count(
                        self.ais_decoder.vessel_count
                    )

            self._stats["sentences_published"] += 1
            return

        # Update state and publish sensors
        self._update_and_publish(data)

    def _update_and_publish(self, data: NMEAData):
        """Update accumulated state and publish to MQTT.

        Args:
            data: Parsed NMEA data.
        """
        published = False

        for sensor_id, sensor_def in SENSOR_DEFINITIONS.items():
            value_key = sensor_def["value_key"]
            value = getattr(data, value_key, None)

            if value is not None:
                self._state[value_key] = value
                self.mqtt_publisher.publish_sensor(sensor_id, value)
                published = True

        # Update device tracker if position available
        if self._device_tracker_enabled:
            lat = self._state.get("latitude")
            lon = self._state.get("longitude")

            if lat is not None and lon is not None:
                attrs = {}
                heading = self._state.get("heading_true")
                speed = self._state.get("speed_over_ground_knots")
                hdop = self._state.get("hdop")
                if heading is not None:
                    attrs["heading"] = heading
                if speed is not None:
                    attrs["speed"] = speed
                if hdop is not None:
                    attrs["gps_accuracy"] = round(hdop * 5)

                self.mqtt_publisher.publish_device_tracker(lat, lon, **attrs)

        if published:
            self._stats["sentences_published"] += 1

    async def _log_stats_periodically(self):
        """Log bridge statistics periodically."""
        while True:
            await asyncio.sleep(self._stats_interval)
            logger.info(
                "Bridge stats: received=%d parsed=%d published=%d errors=%d ais_vessels=%d",
                self._stats["sentences_received"],
                self._stats["sentences_parsed"],
                self._stats["sentences_published"],
                self._stats["errors"],
                self.ais_decoder.vessel_count,
            )

    async def run(self):
        """Start the bridge - runs until interrupted."""
        logger.info("Starting Navnet NMEA-to-MQTT Bridge")

        # Connect to MQTT (retry until connected or stopped)
        self.mqtt_publisher.connect()

        max_wait = 30  # seconds
        waited = 0.0
        while not self.mqtt_publisher.is_connected and waited < max_wait:
            await asyncio.sleep(0.5)
            waited += 0.5

        if not self.mqtt_publisher.is_connected:
            logger.error(
                "Failed to connect to MQTT broker after %ds. "
                "Check broker address and credentials.",
                max_wait,
            )
            return

        # Set up UDP callback
        self.udp_listener.set_callback(self._on_nmea_received)

        # Start UDP listeners
        udp_config = self.config.get("udp", {})
        sources = udp_config.get("sources", [])
        bind_address = udp_config.get("bind_address", "0.0.0.0")

        await self.udp_listener.start(sources, bind_address)

        # Start stats logging
        stats_task = asyncio.create_task(self._log_stats_periodically())

        logger.info("Bridge is running. Press Ctrl+C to stop.")

        self._stop_event = asyncio.Event()
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            stats_task.cancel()
            await self.udp_listener.stop()
            self.mqtt_publisher.disconnect()
            logger.info("Bridge stopped")

    def stop(self):
        """Signal the bridge to stop."""
        logger.info("Stop requested")
        if self._stop_event is not None:
            self._stop_event.set()
