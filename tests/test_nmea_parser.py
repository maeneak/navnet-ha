"""Tests for the NMEA 0183 sentence parser."""

import pytest

from nmea_mqtt_bridge.nmea_parser import (
    NMEAData,
    parse_sentence,
    validate_checksum,
    _safe_float,
    _safe_int,
)


# --- Checksum validation ---


class TestValidateChecksum:
    def test_valid_gga(self):
        assert validate_checksum(
            "$GPGGA,232001.00,1635.2474,S,14555.1765,E,1,11,0.70,11.5,M,62.6,M,,*72"
        )

    def test_valid_vtg(self):
        assert validate_checksum("$GPVTG,17.6,T,10.8,M,23.6,N,43.7,K*40")

    def test_valid_hdt(self):
        assert validate_checksum("$GPHDT,18.2,T*0E")

    def test_valid_ais(self):
        assert validate_checksum(
            "!AIVDM,1,1,,A,404k0a1v`UGD0bKV4qnE0uG00H1;,0*3C"
        )

    def test_invalid_checksum(self):
        assert not validate_checksum("$GPHDT,18.2,T*FF")

    def test_missing_asterisk(self):
        assert not validate_checksum("$GPHDT,18.2,T")

    def test_no_start_delimiter(self):
        assert not validate_checksum("GPHDT,18.2,T*0E")

    def test_empty_string(self):
        assert not validate_checksum("")


# --- Safe conversion helpers ---


class TestSafeFloat:
    def test_valid(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_integer_string(self):
        assert _safe_float("42") == pytest.approx(42.0)

    def test_empty(self):
        assert _safe_float("") is None

    def test_whitespace(self):
        assert _safe_float("  ") is None

    def test_invalid(self):
        assert _safe_float("abc") is None

    def test_none(self):
        assert _safe_float(None) is None


class TestSafeInt:
    def test_valid(self):
        assert _safe_int("11") == 11

    def test_empty(self):
        assert _safe_int("") is None

    def test_float_string(self):
        assert _safe_int("3.14") is None

    def test_none(self):
        assert _safe_int(None) is None


# --- Full sentence parsing ---


class TestParseGGA:
    def test_standard_gga(self):
        raw = "$GPGGA,232001.00,1635.2474,S,14555.1765,E,1,11,0.70,11.5,M,62.6,M,,*72"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "GGA"
        assert data.latitude == pytest.approx(-16.587457, abs=1e-5)
        assert data.longitude == pytest.approx(145.919608, abs=1e-5)
        assert data.fix_quality == 1
        assert data.satellites_in_use == 11
        assert data.hdop == pytest.approx(0.70)
        assert data.altitude == pytest.approx(11.5)

    def test_gga_with_different_talker(self):
        # $IIGGA should also parse as GGA
        raw = "$IIGGA,232001.00,1635.2474,S,14555.1765,E,1,11,0.70,11.5,M,62.6,M,,*65"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "GGA"


class TestParseVTG:
    def test_standard_vtg(self):
        raw = "$GPVTG,17.6,T,10.8,M,23.6,N,43.7,K*40"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "VTG"
        assert data.course_over_ground_true == pytest.approx(17.6)
        assert data.course_over_ground_magnetic == pytest.approx(10.8)
        assert data.speed_over_ground_knots == pytest.approx(23.6)
        assert data.speed_over_ground_kmh == pytest.approx(43.7)


class TestParseHDT:
    def test_standard_hdt(self):
        raw = "$GPHDT,18.2,T*0E"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "HDT"
        assert data.heading_true == pytest.approx(18.2)


class TestParseHDG:
    def test_standard_hdg(self):
        raw = "$GPHDG,11.4,,,6.8,E*0F"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "HDG"
        assert data.heading_magnetic == pytest.approx(11.4)
        assert data.magnetic_variation == pytest.approx(6.8)

    def test_west_variation(self):
        raw = "$GPHDG,11.4,,,6.8,W*1D"
        data = parse_sentence(raw)
        assert data is not None
        assert data.magnetic_variation == pytest.approx(-6.8)


class TestParseZDA:
    def test_standard_zda(self):
        raw = "$GPZDA,232001.00,10,02,2026,-10,00*4D"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "ZDA"
        assert data.utc_date == "2026-02-10"
        assert data.utc_time == "232001.00"


class TestParseRSA:
    def test_valid_rudder(self):
        raw = "$GPRSA,0.6,A,,*3E"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "RSA"
        assert data.rudder_angle == pytest.approx(0.6)

    def test_invalid_status(self):
        raw = "$GPRSA,0.6,V,,*29"
        data = parse_sentence(raw)
        assert data is not None
        # Status V means invalid, rudder_angle should be None
        assert data.rudder_angle is None


class TestParseDPT:
    def test_standard_dpt(self):
        raw = "$IIDPT,36.03,-3.2,*46"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "DPT"
        assert data.depth_meters == pytest.approx(36.03)
        assert data.depth_offset == pytest.approx(-3.2)


class TestParseMTW:
    def test_celsius(self):
        raw = "$YXMTW,25.5,C*10"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "MTW"
        assert data.water_temperature_c == pytest.approx(25.5)

    def test_fahrenheit_mislabeled_as_celsius(self):
        # Values > 50 labeled C are treated as Fahrenheit
        raw = "$YXMTW,076.25,C*14"
        data = parse_sentence(raw)
        assert data is not None
        # 76.25F -> ~24.6C
        assert data.water_temperature_c == pytest.approx(24.6, abs=0.1)


class TestParseAIS:
    def test_valid_ais(self):
        raw = "!AIVDM,1,1,,A,404k0a1v`UGD0bKV4qnE0uG00H1;,0*3C"
        data = parse_sentence(raw)
        assert data is not None
        assert data.sentence_type == "AIS"
        assert len(data.ais_messages) == 1
        assert data.ais_messages[0] == raw

    def test_invalid_ais_checksum(self):
        raw = "!AIVDM,1,1,,A,404k0a1v`UGD0bKV4qnE0uG00H1;,0*FF"
        data = parse_sentence(raw)
        assert data is None


# --- Edge cases ---


class TestEdgeCases:
    def test_empty_string(self):
        assert parse_sentence("") is None

    def test_whitespace_only(self):
        assert parse_sentence("   ") is None

    def test_no_dollar_or_bang(self):
        assert parse_sentence("GPGGA,1,2,3") is None

    def test_bad_checksum(self):
        assert parse_sentence("$GPHDT,18.2,T*FF") is None

    def test_unknown_sentence_type(self):
        # Valid checksum but unknown type
        raw = "$GPXYZ,1,2,3*49"
        assert parse_sentence(raw) is None

    def test_too_few_fields(self):
        raw = "$GP*00"
        assert parse_sentence(raw) is None
