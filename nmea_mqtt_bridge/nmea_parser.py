"""NMEA 0183 sentence parser for marine instrument data.

Uses pynmea2 for parsing and checksum validation of standard NMEA sentences.
AIS sentences are validated manually and stored raw for pyais decoding.
Parsed data is normalized into NMEAData domain objects for the bridge.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import pynmea2

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

    Used for AIS sentences (starting with !) which pynmea2 doesn't handle.
    For standard $ sentences, pynmea2.parse() validates checksums internally.
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


def _safe_float(value: Any) -> Optional[float]:
    """Safely convert a value to float.

    Handles strings, Decimal, numeric types, empty strings, and None.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Safely convert a value to int.

    Handles strings, numeric types, empty strings, and None.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
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

    Uses pynmea2 for parsing and checksum validation of standard sentences.
    AIS sentences (starting with !) are validated and stored for pyais decoding.

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

    try:
        msg = pynmea2.parse(raw, check=True)
    except pynmea2.ParseError:
        logger.debug("Parse/checksum failed: %s", raw)
        return None
    except Exception as e:
        logger.debug("Unexpected parse error: %s - %s", raw, e)
        return None

    # type(msg).__name__ is the sentence type (e.g. "GGA", "HDT")
    # More reliable than msg.sentence_type which varies across pynmea2 versions.
    sentence_type = type(msg).__name__

    parser = _PARSERS.get(sentence_type)
    if parser:
        try:
            data = parser(msg)
            if data:
                data.sentence_type = sentence_type
            return data
        except Exception as e:
            logger.debug("Parse error for %s: %s", sentence_type, e)
            return None

    return None


def _parse_gga(msg) -> Optional[NMEAData]:
    """Parse GGA - Global Positioning System Fix Data.

    $GPGGA,232001.00,1635.2474,S,14555.1765,E,1,11,0.70,11.5,M,62.6,M,,*72
    """
    data = NMEAData()

    # Raw timestamp string (pynmea2 converts to datetime.time; keep raw)
    data.utc_time = msg.data[0] if msg.data[0] else None

    # pynmea2 .latitude/.longitude properties return signed decimal degrees
    if msg.lat and msg.lat_dir:
        try:
            data.latitude = round(msg.latitude, 6)
            data.longitude = round(msg.longitude, 6)
        except (ValueError, AttributeError, TypeError):
            pass

    data.fix_quality = _safe_int(msg.gps_qual)
    data.satellites_in_use = _safe_int(msg.num_sats)
    data.hdop = _safe_float(msg.horizontal_dil)
    data.altitude = _safe_float(msg.altitude)

    return data


def _parse_vtg(msg) -> Optional[NMEAData]:
    """Parse VTG - Track Made Good and Ground Speed.

    $GPVTG,17.6,T,10.8,M,23.6,N,43.7,K*40
    """
    data = NMEAData()
    data.course_over_ground_true = _safe_float(msg.true_track)
    data.course_over_ground_magnetic = _safe_float(msg.mag_track)
    data.speed_over_ground_knots = _safe_float(msg.spd_over_grnd_kts)
    data.speed_over_ground_kmh = _safe_float(msg.spd_over_grnd_kmph)

    return data


def _parse_hdt(msg) -> Optional[NMEAData]:
    """Parse HDT - True Heading.

    $GPHDT,18.2,T*0E
    """
    data = NMEAData()
    data.heading_true = _safe_float(msg.heading)

    return data


def _parse_hdg(msg) -> Optional[NMEAData]:
    """Parse HDG - Magnetic Heading, Deviation, Variation.

    $GPHDG,11.4,,,6.8,E*0F
    """
    data = NMEAData()
    data.heading_magnetic = _safe_float(msg.heading)

    variation = _safe_float(msg.variation)
    if variation is not None:
        if msg.var_dir == "W":
            variation = -variation
        data.magnetic_variation = variation

    return data


def _parse_zda(msg) -> Optional[NMEAData]:
    """Parse ZDA - UTC Date and Time.

    $GPZDA,232001.00,10,02,2026,-10,00*4D
    """
    data = NMEAData()

    # Raw timestamp string
    data.utc_time = msg.data[0] if msg.data[0] else None

    # pynmea2 returns int (or None if empty) for day/month/year
    day = msg.day
    month = msg.month
    year = msg.year

    if day is not None and month is not None and year is not None:
        data.utc_date = f"{year}-{str(month).zfill(2)}-{str(day).zfill(2)}"

    return data


def _parse_rsa(msg) -> Optional[NMEAData]:
    """Parse RSA - Rudder Sensor Angle.

    $GPRSA,0.6,A,,*3E
    """
    data = NMEAData()

    if msg.rsa_starboard_status == "A":
        data.rudder_angle = _safe_float(msg.rsa_starboard)

    return data


def _parse_gsv(msg) -> Optional[NMEAData]:
    """Parse GSV - Satellites in View.

    $GPGSV,3,1,11,08,09,220,38,...*73
    """
    data = NMEAData()
    data.satellites_in_view = _safe_int(msg.num_sv_in_view)

    return data


def _parse_dpt(msg) -> Optional[NMEAData]:
    """Parse DPT - Depth of Water.

    $SDDPT,0036.34,000.00
    $IIDPT,36.03,-3.2,*46
    """
    data = NMEAData()
    data.depth_meters = _safe_float(msg.depth)
    data.depth_offset = _safe_float(msg.offset)

    return data


def _parse_vhw(msg) -> Optional[NMEAData]:
    """Parse VHW - Water Speed and Heading.

    $VWVHW,,T,,M,000.00,N,,K
    $IIVHW,18.2,T,11.4,M,0.0,N,0.0,K*5A
    """
    data = NMEAData()
    data.heading_true = _safe_float(msg.heading_true)
    data.heading_magnetic = _safe_float(msg.heading_magnetic)
    data.speed_through_water_knots = _safe_float(msg.water_speed_knots)

    return data


def _parse_mtw(msg) -> Optional[NMEAData]:
    """Parse MTW - Water Temperature.

    $YXMTW,076.25,C
    """
    data = NMEAData()
    temp = _safe_float(msg.temperature)
    if temp is not None:
        units = msg.units or "C"
        if units == "C":
            # Navnet reports Fahrenheit mislabeled as Celsius (e.g. 076.25,C)
            if temp > 50:
                temp = round((temp - 32) * 5 / 9, 1)
            data.water_temperature_c = temp
        elif units == "F":
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
