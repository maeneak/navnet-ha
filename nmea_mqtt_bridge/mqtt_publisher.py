"""MQTT publisher with Home Assistant MQTT Discovery support."""

import json
import logging
from typing import Any, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# HA MQTT Discovery sensor definitions
SENSOR_DEFINITIONS = {
    "latitude": {
        "name": "Latitude",
        "unit": "°",
        "icon": "mdi:crosshairs-gps",
        "value_key": "latitude",
        "suggested_display_precision": 6,
    },
    "longitude": {
        "name": "Longitude",
        "unit": "°",
        "icon": "mdi:crosshairs-gps",
        "value_key": "longitude",
        "suggested_display_precision": 6,
    },
    "heading_true": {
        "name": "Heading (True)",
        "unit": "°",
        "icon": "mdi:compass",
        "value_key": "heading_true",
        "suggested_display_precision": 1,
    },
    "heading_magnetic": {
        "name": "Heading (Magnetic)",
        "unit": "°",
        "icon": "mdi:compass",
        "value_key": "heading_magnetic",
        "suggested_display_precision": 1,
    },
    "speed_knots": {
        "name": "Speed (SOG)",
        "unit": "kn",
        "icon": "mdi:speedometer",
        "value_key": "speed_over_ground_knots",
        "suggested_display_precision": 1,
    },
    "speed_kmh": {
        "name": "Speed (SOG km/h)",
        "unit": "km/h",
        "icon": "mdi:speedometer",
        "value_key": "speed_over_ground_kmh",
        "suggested_display_precision": 1,
    },
    "course_true": {
        "name": "Course Over Ground",
        "unit": "°",
        "icon": "mdi:navigation",
        "value_key": "course_over_ground_true",
        "suggested_display_precision": 1,
    },
    "depth": {
        "name": "Depth",
        "unit": "m",
        "icon": "mdi:waves",
        "value_key": "depth_meters",
        "device_class": "distance",
        "suggested_display_precision": 1,
    },
    "water_temperature": {
        "name": "Water Temperature",
        "unit": "°C",
        "icon": "mdi:thermometer-water",
        "value_key": "water_temperature_c",
        "device_class": "temperature",
        "suggested_display_precision": 1,
    },
    "altitude": {
        "name": "Altitude",
        "unit": "m",
        "icon": "mdi:altimeter",
        "value_key": "altitude",
        "suggested_display_precision": 1,
    },
    "satellites_in_use": {
        "name": "Satellites",
        "unit": "",
        "icon": "mdi:satellite-variant",
        "value_key": "satellites_in_use",
    },
    "hdop": {
        "name": "GPS Accuracy (HDOP)",
        "unit": "",
        "icon": "mdi:crosshairs-question",
        "value_key": "hdop",
        "suggested_display_precision": 2,
    },
    "rudder_angle": {
        "name": "Rudder Angle",
        "unit": "°",
        "icon": "mdi:ship-wheel",
        "value_key": "rudder_angle",
        "suggested_display_precision": 1,
    },
    "magnetic_variation": {
        "name": "Magnetic Variation",
        "unit": "°",
        "icon": "mdi:magnet",
        "value_key": "magnetic_variation",
        "suggested_display_precision": 1,
    },
    "speed_through_water": {
        "name": "Speed Through Water",
        "unit": "kn",
        "icon": "mdi:speedometer-slow",
        "value_key": "speed_through_water_knots",
        "suggested_display_precision": 1,
    },
    "fix_quality": {
        "name": "GPS Fix Quality",
        "unit": "",
        "icon": "mdi:satellite-uplink",
        "value_key": "fix_quality",
    },
}


class MQTTPublisher:
    """MQTT publisher with Home Assistant auto-discovery."""

    def __init__(self, config: dict, device_config: dict):
        """Initialize MQTT publisher.

        Args:
            config: MQTT configuration dict.
            device_config: Device info for HA discovery.
        """
        self.config = config
        self.device_config = device_config
        self.topic_prefix = config.get("topic_prefix", "navnet")
        self.discovery_prefix = config.get("discovery_prefix", "homeassistant")
        self.client: Optional[mqtt.Client] = None
        self._connected = False
        self._discovery_sent = False
        self._last_values: dict[str, Any] = {}
        self._ais_discovered_mmsis: set[int] = set()

    def connect(self):
        """Connect to MQTT broker."""
        client_id = self.config.get("client_id", "navnet-nmea-bridge")
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )

        username = self.config.get("username", "")
        password = self.config.get("password", "")
        if username:
            self.client.username_pw_set(username, password)

        # Set LWT (Last Will and Testament) for availability tracking
        availability_topic = f"{self.topic_prefix}/bridge/status"
        self.client.will_set(availability_topic, "offline", retain=True)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        host = self.config.get("host", "localhost")
        port = self.config.get("port", 1883)
        keepalive = self.config.get("keepalive", 60)

        logger.info("Connecting to MQTT broker at %s:%d", host, port)
        self.client.connect_async(host, port, keepalive)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            self._connected = True

            # Publish online status
            availability_topic = f"{self.topic_prefix}/bridge/status"
            self.client.publish(availability_topic, "online", retain=True)

            # Send HA discovery configs
            self._send_discovery()
        else:
            logger.error("MQTT connection failed with code %d", rc)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self._connected = False
        self._discovery_sent = False
        if rc != 0:
            logger.warning("Unexpected MQTT disconnect (rc=%d), will retry", rc)

    def _device_payload(self) -> dict:
        """Build the HA device payload for discovery."""
        return {
            "identifiers": [self.device_config.get("identifiers", "navnet_bridge")],
            "name": self.device_config.get("name", "Navnet"),
            "manufacturer": self.device_config.get("manufacturer", "Furuno"),
            "model": self.device_config.get("model", "NavNet"),
        }

    def _send_discovery(self):
        """Publish HA MQTT Discovery config messages for all sensors."""
        if self._discovery_sent:
            return

        availability_topic = f"{self.topic_prefix}/bridge/status"
        device = self._device_payload()

        # Sensor discovery
        for sensor_id, sensor_def in SENSOR_DEFINITIONS.items():
            object_id = f"navnet_{sensor_id}"
            discovery_topic = (
                f"{self.discovery_prefix}/sensor/{object_id}/config"
            )
            state_topic = f"{self.topic_prefix}/sensor/{sensor_id}/state"

            payload = {
                "name": sensor_def["name"],
                "unique_id": object_id,
                "state_topic": state_topic,
                "availability_topic": availability_topic,
                "device": device,
                "icon": sensor_def.get("icon"),
            }

            if sensor_def.get("unit"):
                payload["unit_of_measurement"] = sensor_def["unit"]
            if sensor_def.get("device_class"):
                payload["device_class"] = sensor_def["device_class"]
            if sensor_def.get("suggested_display_precision") is not None:
                payload["suggested_display_precision"] = sensor_def[
                    "suggested_display_precision"
                ]

            self.client.publish(discovery_topic, json.dumps(payload), retain=True)
            logger.debug("Discovery sent: %s", discovery_topic)

        # Device tracker discovery for vessel position on HA map
        dt_discovery_topic = (
            f"{self.discovery_prefix}/device_tracker/navnet_vessel/config"
        )
        dt_state_topic = f"{self.topic_prefix}/device_tracker/state"
        dt_json_topic = f"{self.topic_prefix}/device_tracker/attributes"

        dt_payload = {
            "name": "Vessel Position",
            "unique_id": "navnet_vessel_tracker",
            "state_topic": dt_state_topic,
            "json_attributes_topic": dt_json_topic,
            "availability_topic": availability_topic,
            "device": device,
            "icon": "mdi:ferry",
            "source_type": "gps",
            "payload_home": "home",
            "payload_not_home": "not_home",
        }

        self.client.publish(dt_discovery_topic, json.dumps(dt_payload), retain=True)

        # AIS vessel count sensor
        ais_count_topic = (
            f"{self.discovery_prefix}/sensor/navnet_ais_vessel_count/config"
        )
        ais_count_payload = {
            "name": "AIS Vessels Tracked",
            "unique_id": "navnet_ais_vessel_count",
            "state_topic": f"{self.topic_prefix}/ais/vessel_count",
            "availability_topic": availability_topic,
            "device": device,
            "icon": "mdi:ferry",
            "unit_of_measurement": "vessels",
            "state_class": "measurement",
        }
        self.client.publish(
            ais_count_topic, json.dumps(ais_count_payload), retain=True
        )

        self._discovery_sent = True
        logger.info(
            "HA MQTT Discovery sent for %d sensors + device tracker + AIS",
            len(SENSOR_DEFINITIONS),
        )

    def publish_sensor(self, sensor_id: str, value: Any):
        """Publish a sensor value.

        Args:
            sensor_id: The sensor identifier (must match SENSOR_DEFINITIONS key).
            value: The sensor value to publish.
        """
        if not self._connected or value is None:
            return

        # Skip if value hasn't changed
        if self._last_values.get(sensor_id) == value:
            return

        self._last_values[sensor_id] = value
        topic = f"{self.topic_prefix}/sensor/{sensor_id}/state"
        self.client.publish(topic, str(value), retain=True)

    def publish_device_tracker(self, latitude: float, longitude: float, **attrs):
        """Publish device tracker position.

        Args:
            latitude: Vessel latitude.
            longitude: Vessel longitude.
            **attrs: Additional attributes (heading, speed, etc.)
        """
        if not self._connected:
            return

        state_topic = f"{self.topic_prefix}/device_tracker/state"
        attrs_topic = f"{self.topic_prefix}/device_tracker/attributes"

        self.client.publish(state_topic, "not_home", retain=True)

        attributes = {
            "latitude": latitude,
            "longitude": longitude,
            "gps_accuracy": attrs.pop("gps_accuracy", 10),
            "source_type": "gps",
        }
        attributes.update(attrs)
        self.client.publish(attrs_topic, json.dumps(attributes), retain=True)

    def publish_ais_vessel(self, vessel, is_new: bool):
        """Publish AIS vessel data with per-vessel HA discovery.

        Creates a device_tracker and attribute sensors for each vessel
        on first appearance.

        Args:
            vessel: AISVessel dataclass instance.
            is_new: Whether this is a newly discovered vessel.
        """
        if not self._connected:
            return

        mmsi = vessel.mmsi

        # Send HA discovery for new vessels
        if mmsi not in self._ais_discovered_mmsis:
            self._send_ais_vessel_discovery(vessel)
            self._ais_discovered_mmsis.add(mmsi)

        # Publish device tracker state + attributes
        vessel_name = vessel.name or f"MMSI {mmsi}"
        state_topic = f"{self.topic_prefix}/ais/vessels/{mmsi}/state"
        attrs_topic = f"{self.topic_prefix}/ais/vessels/{mmsi}/attributes"

        self.client.publish(state_topic, "not_home", retain=True)

        attributes = {
            "latitude": vessel.latitude,
            "longitude": vessel.longitude,
            "source_type": "gps",
            "gps_accuracy": 50,
            "friendly_name": vessel_name,
        }

        if vessel.speed is not None:
            attributes["speed"] = vessel.speed
        if vessel.course is not None:
            attributes["heading"] = vessel.course
        if vessel.heading is not None:
            attributes["true_heading"] = vessel.heading
        if vessel.callsign:
            attributes["callsign"] = vessel.callsign
        if vessel.ship_type:
            attributes["ship_type"] = vessel.ship_type
        if vessel.destination:
            attributes["destination"] = vessel.destination
        if vessel.status:
            attributes["nav_status"] = vessel.status
        if vessel.length is not None:
            attributes["length"] = vessel.length
        if vessel.beam is not None:
            attributes["beam"] = vessel.beam
        if vessel.draught is not None:
            attributes["draught"] = vessel.draught
        attributes["mmsi"] = mmsi
        attributes["message_count"] = vessel.message_count

        self.client.publish(attrs_topic, json.dumps(attributes), retain=True)

    def _send_ais_vessel_discovery(self, vessel):
        """Send HA MQTT Discovery config for an AIS vessel.

        Args:
            vessel: AISVessel dataclass instance.
        """
        mmsi = vessel.mmsi
        vessel_name = vessel.name or f"MMSI {mmsi}"
        availability_topic = f"{self.topic_prefix}/bridge/status"

        # AIS vessel device - separate from the bridge device
        ais_device = {
            "identifiers": [f"ais_vessel_{mmsi}"],
            "name": vessel_name,
            "manufacturer": "AIS",
            "model": vessel.ship_type or "Vessel",
            "via_device": self.device_config.get("identifiers", "navnet_nmea_bridge"),
        }

        object_id = f"ais_{mmsi}"

        # Device tracker for vessel position on map
        dt_disc_topic = (
            f"{self.discovery_prefix}/device_tracker/{object_id}/config"
        )
        dt_payload = {
            "name": "Position",
            "unique_id": f"ais_{mmsi}_tracker",
            "state_topic": f"{self.topic_prefix}/ais/vessels/{mmsi}/state",
            "json_attributes_topic": f"{self.topic_prefix}/ais/vessels/{mmsi}/attributes",
            "availability_topic": availability_topic,
            "device": ais_device,
            "icon": "mdi:ferry",
            "source_type": "gps",
            "payload_home": "home",
            "payload_not_home": "not_home",
        }
        self.client.publish(dt_disc_topic, json.dumps(dt_payload), retain=True)

        logger.info(
            "AIS discovery sent for vessel %s (MMSI %d, %s)",
            vessel_name, mmsi, vessel.ship_type,
        )

    def publish_ais_vessel_count(self, count: int):
        """Publish the number of tracked AIS vessels.

        Args:
            count: Number of currently tracked vessels.
        """
        if not self._connected:
            return

        topic = f"{self.topic_prefix}/ais/vessel_count"
        self.client.publish(topic, str(count), retain=True)

    def remove_ais_vessel(self, mmsi: int):
        """Remove HA discovery for a stale AIS vessel.

        Args:
            mmsi: MMSI of the vessel to remove.
        """
        if not self._connected:
            return

        if mmsi in self._ais_discovered_mmsis:
            self._ais_discovered_mmsis.discard(mmsi)

            # Send empty payload to remove discovery
            object_id = f"ais_{mmsi}"
            dt_disc_topic = (
                f"{self.discovery_prefix}/device_tracker/{object_id}/config"
            )
            self.client.publish(dt_disc_topic, "", retain=True)

            logger.info("AIS discovery removed for MMSI %d", mmsi)

    def disconnect(self):
        """Disconnect from MQTT broker."""
        if self.client:
            availability_topic = f"{self.topic_prefix}/bridge/status"
            self.client.publish(availability_topic, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("Disconnected from MQTT broker")

    @property
    def is_connected(self) -> bool:
        return self._connected
