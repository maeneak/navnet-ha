# Navnet NMEA Protocol Specification

**Document Date:** February 11, 2026  
**Network Interface:** eth4  
**Network Segment:** 172.31.0.0/16, 192.168.252.0/24  
**Protocol:** NMEA 0183 over UDP/Ethernet (not NMEA 2000)

## Overview

This document describes the **NMEA 0183** data streams discovered on the vessel's ethernet network from Navnet/Furuno marine electronics system via UDP broadcast.

### NMEA 0183 vs NMEA 2000

**This system uses NMEA 0183:**
- ✅ ASCII text sentences (human-readable)
- ✅ Sentence format: `$GPGGA,232001.00,1635.2474,S...`
- ✅ Transmitted over UDP/Ethernet
- ✅ Standard talker IDs (GP, SD, II, AI)
- ✅ Checksum format: `*XX` (hexadecimal)

**NOT NMEA 2000:**
- ❌ NMEA 2000 uses binary CAN bus protocol
- ❌ NMEA 2000 messages are PGNs (Parameter Group Numbers)
- ❌ NMEA 2000 requires physical CAN backbone
- ❌ NMEA 2000 would need a gateway to appear on Ethernet

**Note:** The binary data on ports 10024 and 10026 is proprietary Navnet/Furuno format, not NMEA 2000.

---

## Data Sources Summary

| Source IP | Port | Protocol | Data Type | Update Rate |
|-----------|------|----------|-----------|-------------|
| 172.31.252.1 | 10021 | UDP | Primary GPS/Navigation | ~1 Hz |
| 172.31.252.1 | 10036 | UDP | Heading Only | ~10 Hz |
| 172.31.92.1 | 10021 | UDP | Depth & Environment | ~1 Hz |
| 172.31.92.1 | 10026 | UDP | Binary/Proprietary | Continuous |
| 172.31.24.3 | 10021 | UDP | AIS Messages | Variable |
| 172.31.24.3 | 10033 | UDP | AIS Messages | Variable |
| 172.31.3.150 | 31000 | UDP | Integrated Feed | ~1 Hz |
| 172.31.3.233 | 10024 | UDP | Binary/Proprietary | Continuous |
| 172.31.3.233 | 10034 | UDP | ARPA Radar | Variable |
| 192.168.252.100 | 10042 | UDP | Mirrored Navigation | ~1 Hz |
| 192.168.252.100 | 10043 | UDP | Time Sync | Periodic |
| 192.168.252.100 | 10044 | UDP | Navnet Status | Variable |

---

## Detailed Source Specifications

### 1. Primary Navigation System (172.31.252.1:10021)

**Port:** 10021 (UDP broadcast to 172.31.255.255)  
**Talker ID:** GP (GPS)  
**Update Rate:** ~1 Hz (every 1 second)

#### NMEA Sentences:

**$GPGGA** - Global Positioning System Fix Data
```
$GPGGA,232001.00,1635.2474,S,14555.1765,E,1,11,0.70,11.5,M,62.6,M,,*72
```
- Time: 23:20:01.00 UTC
- Position: 16°35.2474'S, 145°55.1765'E
- Fix Quality: 1 (GPS fix)
- Satellites: 11
- HDOP: 0.70
- Altitude: 11.5M above MSL
- Geoidal Separation: 62.6M

**$GPVTG** - Track Made Good and Ground Speed
```
$GPVTG,17.6,T,10.8,M,23.6,N,43.7,K*40
```
- True Track: 17.6°
- Magnetic Track: 10.8°
- Speed: 23.6 knots / 43.7 km/h

**$GPZDA** - Date and Time
```
$GPZDA,232001.00,10,02,2026,-10,00*4D
```
- Time: 23:20:01.00
- Date: February 10, 2026
- Timezone: UTC-10:00

**$GPHDT** - True Heading
```
$GPHDT,18.2,T*0E
```
- True Heading: 18.2°

**$GPHDG** - Magnetic Heading, Deviation & Variation
```
$GPHDG,11.4,,,6.8,E*0F
```
- Magnetic Heading: 11.4°
- Deviation: (not provided)
- Variation: 6.8°E

**$GPRSA** - Rudder Sensor Angle
```
$GPRSA,0.6,A,,*3E
```
- Rudder Angle: 0.6°
- Status: A (data valid)

**$GPGSV** - GPS Satellites in View (multi-part message)
```
$GPGSV,3,1,11,08,09,220,38,10,47,203,40,16,19,286,37,18,39,106,42*73
$GPGSV,3,2,11,23,30,154,39,24,08,113,35,26,15,321,38,27,38,228,41*73
$GPGSV,3,3,11,28,10,001,36,29,12,031,38,32,65,348,47,,,,*49
```
- Total satellites in view: 11
- Shows: PRN, elevation, azimuth, SNR for each satellite

---

### 2. High-Rate Heading Data (172.31.252.1:10036)

**Port:** 10036 (UDP broadcast to 172.31.255.255)  
**Talker ID:** GP (GPS)  
**Update Rate:** ~10 Hz (10 times per second)

#### NMEA Sentences:

**$GPHDG** - Magnetic Heading
```
$GPHDG,11.7,,,6.8,E*0C
```

**$GPHDT** - True Heading
```
$GPHDT,18.5,T*09
```

**Purpose:** High-frequency heading updates for autopilot and heading-critical applications.

---

### 3. Depth Sounder & Environmental (172.31.92.1:10021)

**Port:** 10021 (UDP broadcast to 172.31.255.255)  
**Update Rate:** ~1 Hz

#### NMEA Sentences:

**$SDDPT** - Depth Below Transducer
```
$SDDPT,0036.34,000.00
```
- Depth: 36.34 meters
- Offset: 0.00 meters

**$VWVHW** - Water Speed and Heading
```
$VWVHW,,T,,M,000.00,N,,K
```
- Speed through water: 0.00 knots (vessel stationary or sensor not working)

**$YXMTW** - Water Temperature
```
$YXMTW,076.25,C
```
- Water Temperature: 76.25°C (likely misformatted, should be °F = ~24.6°C)

---

### 4. AIS System (172.31.24.3:10021, 10033)

**Ports:** 10021, 10033 (UDP broadcast to 172.31.255.255)  
**Talker ID:** AI (Automatic Identification System)  
**Update Rate:** Variable (based on traffic)

#### NMEA Sentences:

**!AIVDM** - AIS VHF Data-link Message
```
!AIVDM,1,1,,A,404k0a1v`UGD0bKV4qnE0uG00H1;,0*3C
```
- Multipart message: part 1 of 1
- Channel: A
- Encapsulated AIS binary data

**!AIVDO** - AIS VHF Data-link Own-vessel Message
```
!AIVDO,1,1,,,B7Ofdl00sJVwMqu`8cp;08Q5WP06,0*7D
```
- Own vessel AIS data transmission

**Purpose:** Receive and transmit AIS vessel traffic data for collision avoidance.

---

### 5. Integrated Instrument Feed (172.31.3.150:31000)

**Port:** 31000 (UDP broadcast to 172.31.255.255)  
**Talker ID:** II (Integrated Instrumentation)  
**Update Rate:** ~1 Hz

#### NMEA Sentences:

**Consolidated Feed:**
```
$IIGGA,232001.0,1635.2474,S,14555.1765,E,1,11,0.7,11.5,M,62.6,M,,*65
$IIVTG,17.6,T,10.8,M,23.6,N,43.71,K,A*0B
$IIHDT,18.2,T*19
$IIDPT,36.03,-3.2,*46
$IIMTW,75.95,C*2D
$IIVHW,18.2,T,11.4,M,0.0,N,0.0,K*5A
```

**Description:** This appears to be a Navnet integration server (possibly TZ Professional based on UDP 33000 sync messages seen) that consolidates all instrument data into a single authenticated feed with II talker ID.

**Contains:**
- Position (IIGGA)
- Track & Speed (IIVTG)
- True Heading (IIHDT)
- Depth (IIDPT)
- Water Temperature (IIMTW)
- Water Speed & Heading (IIVHW)

**Advantages:**
- Single port to monitor
- Pre-integrated data
- Consistent timing

---

### 6. ARPA Radar Data (172.31.3.233:10034)

**Port:** 10034 (UDP broadcast to 172.31.255.255)  
**Update Rate:** Variable

#### NMEA Sentences:

**$ARPA** - ARPA Target Data
```
$ARPA,0,0,0032,0000,0032,................................
```
- Radar tracking and automatic radar plotting aid data

---

### 7. Mirrored Data Streams (192.168.252.100)

**Network:** 192.168.252.0/24 (separate VLAN)  
**IP:** 192.168.252.100  
**Ports:** 10042 (navigation), 10043 (time sync), 10044 (status)

These appear to be duplicate/mirrored streams of the primary 172.31.x.x network data, possibly for a redundant system or gateway.

---

## Binary/Proprietary Protocols

### Port 10024 (172.31.3.233 → Multicast 239.255.0.2)
- Binary format (not NMEA ASCII)
- Continuous high-frequency updates
- Likely proprietary Navnet/Furuno radar or chart plotter data
- Not suitable for standard NMEA parsing

### Port 10026 (172.31.92.1 & 172.31.252.1)
- Binary format with some ASCII markers
- 868-byte packets
- Likely sonar/fish finder data or detailed sensor telemetry

---

## Network Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Marine Electronics Network                │
│                         (172.31.0.0/16)                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  GPS/Autopilot (172.31.252.1)                                │
│  ├─ Port 10021: Full GPS data @ 1Hz                          │
│  ├─ Port 10036: High-rate heading @ 10Hz                     │
│  ├─ Port 10026: Binary data                                  │
│  └─ Port 10010: Status messages                              │
│                                                               │
│  Depth/Sounder (172.31.92.1)                                 │
│  ├─ Port 10021: Depth & environment @ 1Hz                    │
│  └─ Port 10026: Binary sonar data                            │
│                                                               │
│  AIS Transceiver (172.31.24.3)                               │
│  ├─ Port 10021: AIS messages                                 │
│  └─ Port 10033: AIS messages                                 │
│                                                               │
│  Navnet Integration (172.31.3.150)                           │
│  ├─ Port 31000: Integrated NMEA feed                         │
│  └─ Port 33000: TZ sync messages                             │
│                                                               │
│  Radar/Chart (172.31.3.233)                                  │
│  ├─ Port 10024: Binary radar (multicast 239.255.0.2)         │
│  └─ Port 10034: ARPA target data                             │
│                                                               │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│              Gateway/Mirror Network (192.168.252.0/24)       │
│                    Device: 192.168.252.100                   │
│  ├─ Port 10042: Mirrored navigation data                     │
│  ├─ Port 10043: Time sync (TZT14)                            │
│  └─ Port 10044: Navnet status                                │
└─────────────────────────────────────────────────────────────┘
```

---

## Integration Strategy: NMEA-to-MQTT Bridge

Home Assistant does not natively support UDP NMEA ingestion. The solution is a lightweight
Python bridge that listens for NMEA UDP broadcasts and publishes to MQTT with HA auto-discovery.

**Repository:** [maeneak/navnet-ha](https://github.com/maeneak/navnet-ha)

### Architecture

```
┌──────────────┐     UDP       ┌──────────────┐     MQTT      ┌──────────────┐
│  Navnet      │──────────────▶│  NMEA-MQTT   │──────────────▶│  Home        │
│  Electronics │  Broadcast    │  Bridge      │  Discovery    │  Assistant   │
└──────────────┘               └──────────────┘               └──────────────┘
                                (Synology NAS)
```

### Deployment

Run on the Synology NAS (already on the network via eth4) using Docker:

```bash
docker compose up -d
```

### Sensors Auto-Created in HA

| Entity | Sensor ID | Source |
|--------|-----------|--------|
| Latitude | `sensor.navnet_latitude` | GGA |
| Longitude | `sensor.navnet_longitude` | GGA |
| Heading (True) | `sensor.navnet_heading_true` | HDT |
| Heading (Magnetic) | `sensor.navnet_heading_magnetic` | HDG |
| Speed (SOG) | `sensor.navnet_speed_knots` | VTG |
| Depth | `sensor.navnet_depth` | DPT |
| Water Temperature | `sensor.navnet_water_temperature` | MTW |
| Rudder Angle | `sensor.navnet_rudder_angle` | RSA |
| Vessel Position | `device_tracker.navnet_vessel_tracker` | GGA |

See [README.md](README.md) for full setup instructions.

---

## NMEA Sentence Reference

### Position & Navigation
- **GGA** - GPS Fix Data (position, altitude, satellites)
- **VTG** - Track & Ground Speed
- **HDT** - True Heading
- **HDG** - Magnetic Heading with Deviation & Variation
- **ZDA** - UTC Date & Time

### Depth & Environment  
- **DPT** - Depth of Water
- **MTW** - Water Temperature
- **VHW** - Water Speed & Heading

### Speed & Course
- **RSA** - Rudder Sensor Angle

### Satellites
- **GSV** - GPS Satellites in View (detailed satellite info)

### AIS
- **AIVDM** - AIS Messages from other vessels
- **AIVDO** - AIS Messages from own vessel

### Radar
- **ARPA** - Automatic Radar Plotting Aid

---

## Data Samples

### GPS Position
```
Latitude:  16°35.2474' S  (16.587456°S)
Longitude: 145°55.1765' E (145.919608°E)
Location: Great Barrier Reef, Queensland, Australia
```

### Navigation Status (at capture time)
```
Speed Over Ground: 23.6 knots (43.7 km/h)
Course Over Ground: 17.6°T / 10.8°M
True Heading: 18.2°T
Magnetic Heading: 11.4°M
Magnetic Variation: 6.8°E
Depth: 36.3 meters
Water Temperature: ~76°F (~24°C)
Satellites in View: 11
Position Accuracy (HDOP): 0.70 (Excellent)
Date/Time: 2026-02-10 23:20:01 UTC
```

---

## Notes

1. **Timestamp Format**: All times in UTC (10 hours ahead of local Queensland time)
2. **Coordinate Format**: NMEA uses DDMM.MMMM format (degrees + decimal minutes)
3. **Magnetic Variation**: 6.8°E needs to be applied when converting between true and magnetic headings
4. **High Update Rates**: Port 10036 provides 10Hz heading updates for autopilot smoothness
5. **Binary Data**: Ports 10024 and 10026 carry proprietary data - ignore for standard NMEA integration
6. **Multicast**: Some radar data uses multicast address 239.255.0.2
7. **Water Temperature**: Sensor appears to report in Celsius but value suggests Fahrenheit scale issue

---

## Testing Commands

**Monitor specific port:**
```bash
sudo tcpdump -i eth4 -A -n udp port 31000
```

**Listen for NMEA sentences:**
```bash
sudo tcpdump -i eth4 -A -n udp port 10021 | grep '^\$GP'
```

**Capture AIS traffic:**
```bash
sudo tcpdump -i eth4 -A -n 'udp and (port 10021 or port 10033)' | grep '!AIV'
```

**Test UDP listener:**
```bash
nc -ul 31000
```

---

## Integration Checklist

- [ ] Verify network connectivity to 172.31.0.0/16 from Synology NAS
- [ ] Confirm MQTT broker running (Mosquitto add-on in HA)
- [ ] Configure HA MQTT integration
- [ ] Edit `config.yaml` with MQTT broker credentials
- [ ] Deploy bridge: `docker compose up -d`
- [ ] Verify sensors appear in HA under MQTT → Navnet device
- [ ] Confirm vessel position on HA map
- [ ] Test depth and speed data accuracy
- [ ] Configure depth alarms (if required)
- [ ] Set up AIS target tracking (if required)
- [ ] Create automations and dashboards

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-11  
**Network Capture Date:** 2026-02-10 23:20:02 UTC
