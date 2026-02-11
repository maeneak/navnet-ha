"""NMEA 0183 sentence parser for marine instrument data."""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NMEAData:
    """Parsed NMEA data container."""

    # Position
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None

    # Navigation
    heading_true: Optional[float] = None
    heading_magnetic: Optional[float] = None
    magnetic_variation: Optional[float] = None
    course_over_ground_true: Optional[float] = None
    course_over_ground_magnetic: Optional[float] = None
    speed_over_ground_knots: Optional[float] = None
    speed_over_ground_kmh: Optional[float] = None

    # Depth & Environment
    depth_meters: Optional[float] = None
    depth_offset: Optional[float] = None
    water_temperature_c: Optional[float] = None
    speed_through_water_knots: Optional[float] = None

    # GPS Quality
    fix_quality: Optional[int] = None
    satellites_in_use: Optional[int] = None
    hdop: Optional[float] = None

    # Rudder
    rudder_angle: Optional[float] = None

    # Time
    utc_time: Optional[str] = None
    utc_date: Optional[str] = None

    # AIS
    ais_messages: list = field(default_factory=list)

    # Satellites detail
    satellites_in_view: Optional[int] = None

    # Raw sentence type for tracking
    sentence_type: Optional[str] = None


def validate_checksum(sentence: str) -> bool:
    """Validate NMEA 0183 checksum.

    Checksum is XOR of all characters between $ (or !) and *.
    """
    try:
        if "*" not in sentence:
            return False

        # Find start delimiter
        start = sentence.find("$")
        if start == -1:
            start = sentence.find("!")
        if start == -1:
            return False

        body = sentence[start + 1 : sentence.index("*")]
        expected = sentence[sentence.index("*") + 1 :].strip()

        calculated = 0
        for char in body:
            calculated ^= ord(char)

        return f"{calculated:02X}" == expected.upper()
    except (ValueError, IndexError):
        return False


def _parse_coordinate(value: str, direction: str) -> Optional[float]:
    """Parse NMEA coordinate (DDMM.MMMM or DDDMM.MMMM) to decimal degrees."""
    if not value or not direction:
        return None
    try:
        # Determine degrees width (2 for lat, 3 for lon)
        if direction in ("N", "S"):
            deg_width = 2
        else:
            deg_width = 3

        degrees = int(value[:deg_width])
        minutes = float(value[deg_width:])
        decimal = degrees + minutes / 60.0

        if direction in ("S", "W"):
            decimal = -decimal

        return round(decimal, 6)
    except (ValueError, IndexError):
        return None


def _safe_float(value: str) -> Optional[float]:
    """Safely convert string to float."""
    if not value or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _safe_int(value: str) -> Optional[int]:
    """Safely convert string to int."""
    if not value or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


_PARSERS: dict = {}


def _init_parsers():
    """Initialize parsers dict. Called after parser functions are defined."""
    global _PARSERS
    _PARSERS = {
        "GGA": _parse_gga,
        "VTG": _parse_vtg,
        "HDT": _parse_hdt,
        "HDG": _parse_hdg,
        "ZDA": _parse_zda,
        "RSA": _parse_rsa,
        "GSV": _parse_gsv,
        "DPT": _parse_dpt,
        "VHW": _parse_vhw,
        "MTW": _parse_mtw,
    }


def parse_sentence(raw: str) -> Optional[NMEAData]:
    """Parse a single NMEA 0183 sentence.

    Supports:
        GGA - Position fix
        VTG - Track and speed
        HDT - True heading
        HDG - Magnetic heading
        ZDA - Date and time
        RSA - Rudder sensor angle
        GSV - Satellites in view
        DPT - Depth
        VHW - Water speed and heading
        MTW - Water temperature
        AIVDM/AIVDO - AIS messages
    """
    raw = raw.strip()

    if not raw:
        return None

    # Handle AIS messages (start with !)
    if raw.startswith("!"):
        return _parse_ais(raw)

    # Standard NMEA sentences (start with $)
    if not raw.startswith("$"):
        return None

    if not validate_checksum(raw):
        logger.debug("Checksum failed: %s", raw)
        return None

    # Remove checksum for parsing
    sentence = raw.split("*")[0]
    parts = sentence.split(",")

    if len(parts) < 2:
        return None

    # Extract sentence type (last 3 chars of talker+type field)
    sentence_id = parts[0]
    # Handle $GPGGA, $IIGGA, $SDGGA etc - get the sentence type
    sentence_type = sentence_id[-3:] if len(sentence_id) >= 4 else sentence_id[1:]

    parser = _PARSERS.get(sentence_type)
    if parser:
        try:
            data = parser(parts)
            if data:
                data.sentence_type = sentence_type
            return data
        except Exception as e:
            logger.debug("Parse error for %s: %s", sentence_type, e)
            return None

    return None


def _parse_gga(parts: list) -> Optional[NMEAData]:
    """Parse GGA - Global Positioning System Fix Data.

    $GPGGA,232001.00,1635.2474,S,14555.1765,E,1,11,0.70,11.5,M,62.6,M,,*72
    """
    if len(parts) < 15:
        return None

    data = NMEAData()
    data.utc_time = parts[1] if parts[1] else None
    data.latitude = _parse_coordinate(parts[2], parts[3])
    data.longitude = _parse_coordinate(parts[4], parts[5])
    data.fix_quality = _safe_int(parts[6])
    data.satellites_in_use = _safe_int(parts[7])
    data.hdop = _safe_float(parts[8])
    data.altitude = _safe_float(parts[9])

    return data


def _parse_vtg(parts: list) -> Optional[NMEAData]:
    """Parse VTG - Track Made Good and Ground Speed.

    $GPVTG,17.6,T,10.8,M,23.6,N,43.7,K*40
    """
    if len(parts) < 9:
        return None

    data = NMEAData()
    data.course_over_ground_true = _safe_float(parts[1])
    data.course_over_ground_magnetic = _safe_float(parts[3])
    data.speed_over_ground_knots = _safe_float(parts[5])
    data.speed_over_ground_kmh = _safe_float(parts[7])

    return data


def _parse_hdt(parts: list) -> Optional[NMEAData]:
    """Parse HDT - True Heading.

    $GPHDT,18.2,T*0E
    """
    if len(parts) < 3:
        return None

    data = NMEAData()
    data.heading_true = _safe_float(parts[1])

    return data


def _parse_hdg(parts: list) -> Optional[NMEAData]:
    """Parse HDG - Magnetic Heading, Deviation, Variation.

    $GPHDG,11.4,,,6.8,E*0F
    """
    if len(parts) < 6:
        return None

    data = NMEAData()
    data.heading_magnetic = _safe_float(parts[1])

    variation = _safe_float(parts[4])
    if variation is not None and len(parts) > 5:
        direction = parts[5].strip()
        if direction == "W":
            variation = -variation
        data.magnetic_variation = variation

    return data


def _parse_zda(parts: list) -> Optional[NMEAData]:
    """Parse ZDA - UTC Date and Time.

    $GPZDA,232001.00,10,02,2026,-10,00*4D
    """
    if len(parts) < 5:
        return None

    data = NMEAData()
    data.utc_time = parts[1] if parts[1] else None

    day = parts[2]
    month = parts[3]
    year = parts[4]
    if day and month and year:
        data.utc_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    return data


def _parse_rsa(parts: list) -> Optional[NMEAData]:
    """Parse RSA - Rudder Sensor Angle.

    $GPRSA,0.6,A,,*3E
    """
    if len(parts) < 3:
        return None

    data = NMEAData()
    if len(parts) > 2 and parts[2] == "A":
        data.rudder_angle = _safe_float(parts[1])

    return data


def _parse_gsv(parts: list) -> Optional[NMEAData]:
    """Parse GSV - Satellites in View.

    $GPGSV,3,1,11,08,09,220,38,...*73
    """
    if len(parts) < 4:
        return None

    data = NMEAData()
    data.satellites_in_view = _safe_int(parts[3])

    return data


def _parse_dpt(parts: list) -> Optional[NMEAData]:
    """Parse DPT - Depth of Water.

    $SDDPT,0036.34,000.00
    $IIDPT,36.03,-3.2,*46
    """
    if len(parts) < 3:
        return None

    data = NMEAData()
    data.depth_meters = _safe_float(parts[1])
    data.depth_offset = _safe_float(parts[2])

    return data


def _parse_vhw(parts: list) -> Optional[NMEAData]:
    """Parse VHW - Water Speed and Heading.

    $VWVHW,,T,,M,000.00,N,,K
    $IIVHW,18.2,T,11.4,M,0.0,N,0.0,K*5A
    """
    if len(parts) < 9:
        return None

    data = NMEAData()
    data.heading_true = _safe_float(parts[1])
    data.heading_magnetic = _safe_float(parts[3])
    data.speed_through_water_knots = _safe_float(parts[5])

    return data


def _parse_mtw(parts: list) -> Optional[NMEAData]:
    """Parse MTW - Water Temperature.

    $YXMTW,076.25,C
    """
    if len(parts) < 3:
        return None

    data = NMEAData()
    temp = _safe_float(parts[1])
    if temp is not None:
        unit = parts[2].strip()
        if unit == "C":
            # Navnet reports Fahrenheit mislabeled as Celsius (e.g. 076.25,C)
            if temp > 50:
                temp = round((temp - 32) * 5 / 9, 1)
            data.water_temperature_c = temp
        elif unit == "F":
            data.water_temperature_c = round((temp - 32) * 5 / 9, 1)

    return data


def _parse_ais(raw: str) -> Optional[NMEAData]:
    """Parse AIS messages - store raw for forwarding.

    !AIVDM,1,1,,A,404k0a1v`UGD0bKV4qnE0uG00H1;,0*3C
    """
    if not validate_checksum(raw):
        return None

    data = NMEAData()
    data.sentence_type = "AIS"
    data.ais_messages = [raw]

    return data


# Initialize parser dispatch table now that all functions are defined
_init_parsers()
