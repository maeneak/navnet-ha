# Navnet NMEA-to-MQTT Bridge

Lightweight bridge that listens for Furuno Navnet NMEA 0183 data over UDP and publishes it to MQTT with Home Assistant auto-discovery.

## What It Does

```
┌──────────────┐     UDP      ┌──────────────┐     MQTT      ┌──────────────┐
│  Navnet      │─────────────▶│  This Bridge │──────────────▶│  Home        │
│  Electronics │  Broadcast   │  (Python)    │  Discovery    │  Assistant   │
└──────────────┘              └──────────────┘               └──────────────┘
```

- Listens for NMEA 0183 UDP broadcasts from Navnet marine electronics
- Parses GPS, heading, depth, speed, AIS, water temp, rudder, and satellite data
- Publishes to MQTT with HA auto-discovery (sensors appear automatically)
- Creates a device tracker so your vessel shows up on the HA map
- Throttles high-frequency data (10Hz heading → configurable rate) to avoid flooding HA

## Sensors Created in Home Assistant

| Sensor | Unit | Source |
|--------|------|--------|
| Latitude | ° | GGA |
| Longitude | ° | GGA |
| Heading (True) | ° | HDT |
| Heading (Magnetic) | ° | HDG |
| Speed (SOG) | kn | VTG |
| Speed (SOG km/h) | km/h | VTG |
| Course Over Ground | ° | VTG |
| Depth | m | DPT |
| Water Temperature | °C | MTW |
| Altitude | m | GGA |
| Satellites | count | GGA |
| GPS Accuracy (HDOP) | | GGA |
| Rudder Angle | ° | RSA |
| Magnetic Variation | ° | HDG |
| Speed Through Water | kn | VHW |
| GPS Fix Quality | | GGA |
| Vessel Position | device_tracker | GGA |
| AIS Last Message | raw | AIVDM |

## Quick Start

### Prerequisites

- Docker and Docker Compose on a machine that can receive UDP broadcasts from the Navnet network
- MQTT broker (e.g., Mosquitto add-on in Home Assistant)
- HA MQTT integration configured

### 1. Clone and Configure

```bash
git clone https://github.com/maeneak/navnet-ha.git
cd navnet-ha
```

Edit `config.yaml`:

```yaml
mqtt:
  host: "homeassistant.local"   # Your HA/MQTT broker IP
  port: 1883
  username: "mqtt_user"         # Your MQTT credentials
  password: "mqtt_password"
```

### 2. Run with Docker Compose

```bash
docker compose up -d
```

The container uses `network_mode: host` so it can receive UDP broadcasts on the vessel's network.

### 3. Check Logs

```bash
docker compose logs -f
```

You should see:
```
Connecting to MQTT broker at homeassistant.local:1883
Connected to MQTT broker
HA MQTT Discovery sent for 16 sensors + device tracker
Listening on 0.0.0.0:10021 [primary_nav] - Primary GPS/Navigation & Depth
Listening on 0.0.0.0:10036 [heading_fast] - High-rate heading data (10Hz)
Listening on 0.0.0.0:31000 [integrated] - Integrated instrument feed
Listening on 0.0.0.0:10033 [ais] - AIS vessel traffic
Bridge is running.
```

### 4. Check Home Assistant

Go to **Settings → Devices & Services → MQTT**. You should see a new **Navnet** device with all sensors.

## Running Standalone (without Docker)

```bash
pip install -r requirements.txt
python -m nmea_mqtt_bridge
```

Or with a custom config path:

```bash
python -m nmea_mqtt_bridge /path/to/config.yaml
```

## Configuration Reference

See `config.yaml` for all options. Key settings:

### UDP Sources

Enable/disable specific data streams:

```yaml
udp:
  sources:
    - name: "primary_nav"
      port: 10021
      enabled: true        # Primary GPS data
    - name: "heading_fast"
      port: 10036
      enabled: true        # 10Hz heading
    - name: "integrated"
      port: 31000
      enabled: true        # All-in-one feed
    - name: "ais"
      port: 10033
      enabled: true        # AIS traffic
```

### Throttle Rates

Control how often data is published to HA (prevents flooding):

```yaml
sensors:
  throttle:
    position: 5        # GPS every 5 seconds
    heading: 2         # Heading every 2 seconds
    speed: 5           # Speed every 5 seconds
    depth: 5           # Depth every 5 seconds
    environment: 30    # Water temp every 30 seconds
    satellites: 30     # Satellite info every 30 seconds
    rudder: 2          # Rudder every 2 seconds
    ais: 10            # AIS every 10 seconds
```

## Network Architecture

The bridge listens for UDP broadcast NMEA 0183 data. Configure the ports in `config.yaml` to match your Navnet network. Typical data sources include:

| Data | Source Sentence | Notes |
|------|----------------|-------|
| GPS position, satellites, altitude | GGA | Primary navigation fix |
| Heading (10Hz) | HDT, HDG | True and magnetic heading |
| Speed and course | VTG | Speed/course over ground |
| Depth | DPT | Water depth |
| Water temperature | MTW | Sea temperature |
| Water speed | VHW | Speed through water |
| AIS traffic | AIVDM/AIVDO | Vessel traffic |
| Rudder angle | RSA | Rudder sensor |

The host running this bridge must be on the same network as the Navnet electronics to receive UDP broadcasts. The Docker container uses `network_mode: host` for this reason.

## MQTT Topics

All topics are prefixed with `navnet/` (configurable):

```
navnet/bridge/status              → online/offline
navnet/sensor/latitude/state      → <decimal degrees>
navnet/sensor/longitude/state     → <decimal degrees>
navnet/sensor/heading_true/state  → <degrees>
navnet/sensor/depth/state         → <meters>
navnet/sensor/speed_knots/state   → <knots>
navnet/device_tracker/state       → not_home
navnet/device_tracker/attributes  → {"latitude": ..., "longitude": ..., "heading": ...}
navnet/ais/last_message           → <raw NMEA AIS sentence>
navnet/ais/stream                 → (all AIS messages, not retained)
```

## License

MIT
