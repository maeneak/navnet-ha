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

# Maps NMEA sentence types to throttle categories (used for AIS only)
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

# Maps each sensor ID to its throttle category so sensors are
# rate-limited independently of which NMEA sentence carries them.
SENSOR_THROTTLE_MAP = {
    "latitude": "position",
    "longitude": "position",
    "heading_true": "heading",
    "heading_magnetic": "heading",
    "speed_knots": "speed",
    "speed_kmh": "speed",
    "course_true": "speed",
    "depth": "depth",
    "water_temperature": "environment",
    "altitude": "position",
    "satellites_in_use": "satellites",
    "hdop": "position",
    "rudder_angle": "rudder",
    "magnetic_variation": "heading",
    "speed_through_water": "speed",
    "fix_quality": "position",
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

        # Throttle tracking: category -> last publish timestamp (AIS only)
        self._last_publish: dict[str, float] = {}
        # Per-sensor throttle tracking: sensor_id -> last publish timestamp
        self._last_sensor_publish: dict[str, float] = {}
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

        # Handle AIS with sentence-level throttle
        if data.sentence_type == "AIS" and data.ais_messages:
            throttle_seconds = self._throttle_config.get("ais", 10)
            now = time.monotonic()
            last = self._last_publish.get("ais", 0)

            if now - last < throttle_seconds:
                return

            self._last_publish["ais"] = now
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

        # Non-AIS: per-sensor throttle applied inside _update_and_publish
        self._update_and_publish(data)

    def _update_and_publish(self, data: NMEAData):
        """Update accumulated state and publish to MQTT.

        Each sensor is throttled individually based on its category,
        so a heading value embedded in a speed sentence still respects
        the heading throttle rate.

        Args:
            data: Parsed NMEA data.
        """
        published = False
        now = time.monotonic()

        for sensor_id, sensor_def in SENSOR_DEFINITIONS.items():
            value_key = sensor_def["value_key"]
            value = getattr(data, value_key, None)

            if value is not None:
                # Always keep state fresh for device tracker / future reads
                self._state[value_key] = value

                # Per-sensor throttle check
                category = SENSOR_THROTTLE_MAP.get(sensor_id, "position")
                throttle_seconds = self._throttle_config.get(category, 5)
                last = self._last_sensor_publish.get(sensor_id, 0)

                if now - last < throttle_seconds:
                    continue

                self._last_sensor_publish[sensor_id] = now
                self.mqtt_publisher.publish_sensor(sensor_id, value)
                published = True

        # Update device tracker on the position throttle schedule only
        if self._device_tracker_enabled:
            lat = self._state.get("latitude")
            lon = self._state.get("longitude")

            if lat is not None and lon is not None:
                dt_throttle = self._throttle_config.get("position", 5)
                dt_last = self._last_sensor_publish.get("_device_tracker", 0)

                if now - dt_last >= dt_throttle:
                    self._last_sensor_publish["_device_tracker"] = now

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
