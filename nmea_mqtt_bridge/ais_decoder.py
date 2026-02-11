"""AIS message decoder and vessel tracker using pyais."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from pyais import decode
from pyais.exceptions import (
    InvalidNMEAMessageException,
    UnknownMessageException,
)

logger = logging.getLogger(__name__)

# AIS message types that contain position data
POSITION_MSG_TYPES = {1, 2, 3, 18, 19}

# AIS message types that contain static/voyage data
STATIC_MSG_TYPES = {5, 24}

# Ship type descriptions (subset of common types)
SHIP_TYPE_NAMES = {
    0: "Not available",
    20: "Wing in ground",
    30: "Fishing",
    31: "Towing",
    32: "Towing (large)",
    33: "Dredging",
    34: "Diving ops",
    35: "Military ops",
    36: "Sailing",
    37: "Pleasure craft",
    40: "High speed craft",
    50: "Pilot vessel",
    51: "Search & rescue",
    52: "Tug",
    53: "Port tender",
    55: "Law enforcement",
    60: "Passenger",
    70: "Cargo",
    80: "Tanker",
    90: "Other",
}


def _ship_type_name(ship_type: Any) -> str:
    """Get human-readable ship type name."""
    if ship_type is None:
        return "Unknown"
    try:
        type_int = int(ship_type)
    except (ValueError, TypeError):
        return str(ship_type)

    # Check exact match first, then category (tens digit)
    if type_int in SHIP_TYPE_NAMES:
        return SHIP_TYPE_NAMES[type_int]
    category = (type_int // 10) * 10
    if category in SHIP_TYPE_NAMES:
        return SHIP_TYPE_NAMES[category]
    return f"Type {type_int}"


@dataclass
class AISVessel:
    """Tracked AIS vessel."""

    mmsi: int
    name: str = ""
    callsign: str = ""
    ship_type: str = "Unknown"
    ship_type_id: Optional[int] = None
    destination: str = ""

    # Position
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    course: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[int] = None
    status: str = ""

    # Dimensions
    to_bow: Optional[int] = None
    to_stern: Optional[int] = None
    to_port: Optional[int] = None
    to_starboard: Optional[int] = None
    draught: Optional[float] = None

    # Tracking
    last_seen: float = 0.0
    message_count: int = 0

    @property
    def length(self) -> Optional[int]:
        if self.to_bow is not None and self.to_stern is not None:
            return self.to_bow + self.to_stern
        return None

    @property
    def beam(self) -> Optional[int]:
        if self.to_port is not None and self.to_starboard is not None:
            return self.to_port + self.to_starboard
        return None

    def to_dict(self) -> dict:
        """Convert to dict for MQTT publishing."""
        d = {
            "mmsi": self.mmsi,
            "name": self.name or f"MMSI {self.mmsi}",
            "callsign": self.callsign,
            "ship_type": self.ship_type,
            "destination": self.destination,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "course": self.course,
            "speed": self.speed,
            "heading": self.heading,
            "status": self.status,
            "message_count": self.message_count,
        }
        if self.length is not None:
            d["length"] = self.length
        if self.beam is not None:
            d["beam"] = self.beam
        if self.draught is not None:
            d["draught"] = self.draught
        return d


class AISDecoder:
    """Decodes AIS messages and tracks vessels."""

    def __init__(self, vessel_timeout: int = 600):
        """Initialize AIS decoder.

        Args:
            vessel_timeout: Remove vessels not seen for this many seconds.
        """
        self.vessels: dict[int, AISVessel] = {}
        self.vessel_timeout = vessel_timeout

        # Buffer for multipart messages: seq_id -> (part1_raw, timestamp)
        self._multipart_buffer: dict[str, tuple[str, float]] = {}
        self._multipart_timeout = 5.0  # seconds to wait for part 2

    def decode_message(self, raw: str) -> Optional[tuple[AISVessel, bool]]:
        """Decode an AIS message and update vessel tracking.

        Args:
            raw: Raw AIS NMEA sentence (e.g. !AIVDM,1,1,,A,...).

        Returns:
            Tuple of (vessel, is_new_vessel) if decoded successfully, None otherwise.
        """
        try:
            parts = raw.split(",")
            if len(parts) < 7:
                return None

            frag_count = int(parts[1])
            frag_num = int(parts[2])
            seq_id = parts[3] if parts[3] else None

            # Single-part message
            if frag_count == 1:
                return self._process_decoded(raw)

            # Multipart message handling
            if frag_num == 1:
                # Store first part, wait for second
                key = seq_id or "default"
                self._multipart_buffer[key] = (raw, time.monotonic())
                return None

            elif frag_num == 2 and frag_count == 2:
                # Look for matching first part
                key = seq_id or "default"
                if key in self._multipart_buffer:
                    part1_raw, ts = self._multipart_buffer.pop(key)
                    if time.monotonic() - ts < self._multipart_timeout:
                        return self._process_decoded(part1_raw, raw)

            return None

        except (ValueError, IndexError) as e:
            logger.debug("AIS parse error: %s", e)
            return None

    def _process_decoded(self, *raw_parts: str) -> Optional[tuple[AISVessel, bool]]:
        """Decode raw message(s) and update vessel state.

        Args:
            raw_parts: One or more raw NMEA sentences.

        Returns:
            Tuple of (vessel, is_new) or None.
        """
        try:
            decoded = decode(*raw_parts).asdict()
        except (
            InvalidNMEAMessageException,
            UnknownMessageException,
            Exception,
        ) as e:
            logger.debug("AIS decode failed: %s", e)
            return None

        mmsi = decoded.get("mmsi")
        if not mmsi:
            return None

        msg_type = decoded.get("msg_type")

        is_new = mmsi not in self.vessels
        vessel = self.vessels.setdefault(mmsi, AISVessel(mmsi=mmsi))
        vessel.last_seen = time.monotonic()
        vessel.message_count += 1

        # Update position data (message types 1-3, 18, 19)
        if msg_type in POSITION_MSG_TYPES:
            lat = decoded.get("lat")
            lon = decoded.get("lon")
            # Filter invalid/default positions
            if lat is not None and lon is not None:
                if abs(lat) <= 90 and abs(lon) <= 180:
                    vessel.latitude = round(lat, 6)
                    vessel.longitude = round(lon, 6)

            speed = decoded.get("speed")
            if speed is not None and speed < 102.3:  # 102.3 = not available
                vessel.speed = speed

            course = decoded.get("course")
            if course is not None and course < 360:
                vessel.course = round(course, 1)

            heading = decoded.get("heading")
            if heading is not None and heading < 511:  # 511 = not available
                vessel.heading = heading

            status = decoded.get("status")
            if status is not None:
                try:
                    vessel.status = str(status.name) if hasattr(status, "name") else str(status)
                except Exception:
                    vessel.status = str(status)

        # Update static/voyage data (message types 5, 19, 24)
        if msg_type in STATIC_MSG_TYPES or msg_type == 19:
            shipname = decoded.get("shipname", "")
            if shipname and shipname.strip() and shipname.strip("@"):
                vessel.name = shipname.strip().strip("@").strip()

            callsign = decoded.get("callsign", "")
            if callsign and callsign.strip() and callsign.strip("@"):
                vessel.callsign = callsign.strip().strip("@").strip()

            ship_type = decoded.get("ship_type")
            if ship_type is not None:
                vessel.ship_type_id = int(ship_type) if ship_type else None
                vessel.ship_type = _ship_type_name(ship_type)

            destination = decoded.get("destination", "")
            if destination and destination.strip() and destination.strip("@"):
                vessel.destination = destination.strip().strip("@").strip()

            draught = decoded.get("draught")
            if draught is not None and draught > 0:
                vessel.draught = draught

            for dim in ("to_bow", "to_stern", "to_port", "to_starboard"):
                val = decoded.get(dim)
                if val is not None and val > 0:
                    setattr(vessel, dim, val)

        return vessel, is_new

    def cleanup_stale_vessels(self) -> list[int]:
        """Remove vessels not seen within the timeout period.

        Returns:
            List of removed MMSIs.
        """
        now = time.monotonic()
        stale = [
            mmsi
            for mmsi, v in self.vessels.items()
            if now - v.last_seen > self.vessel_timeout
        ]
        for mmsi in stale:
            del self.vessels[mmsi]

        # Also clean up stale multipart buffer entries
        stale_parts = [
            key
            for key, (_, ts) in self._multipart_buffer.items()
            if now - ts > self._multipart_timeout
        ]
        for key in stale_parts:
            del self._multipart_buffer[key]

        return stale

    @property
    def vessel_count(self) -> int:
        return len(self.vessels)

    def get_all_vessels_json(self) -> str:
        """Get all tracked vessels as JSON."""
        return json.dumps(
            [v.to_dict() for v in self.vessels.values()],
            default=str,
        )
