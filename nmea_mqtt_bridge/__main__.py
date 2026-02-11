"""Entry point for the Navnet NMEA-to-MQTT Bridge."""

import asyncio
import logging
import signal
import sys
from pathlib import Path

import yaml

from .bridge import NMEABridge


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        print(f"Config file not found: {config_path}")
        print("Create a config.yaml file. See README.md for configuration reference.")
        sys.exit(1)

    with open(path) as f:
        return yaml.safe_load(f)


def validate_config(config: dict):
    """Validate required configuration keys exist."""
    if not isinstance(config, dict):
        print("Error: config.yaml is empty or invalid.")
        sys.exit(1)

    mqtt = config.get("mqtt")
    if not mqtt or not mqtt.get("host"):
        print("Error: mqtt.host is required in config.yaml")
        sys.exit(1)

    sources = config.get("udp", {}).get("sources", [])
    for i, source in enumerate(sources):
        if "port" not in source or "name" not in source:
            print(f"Error: udp.sources[{i}] must have 'name' and 'port' keys")
            sys.exit(1)


def setup_logging(config: dict):
    """Configure logging from config."""
    log_config = config.get("logging", {})
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    fmt = log_config.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    logging.basicConfig(level=level, format=fmt)

    # Quiet down paho-mqtt unless debugging
    if level > logging.DEBUG:
        logging.getLogger("paho").setLevel(logging.WARNING)


def main():
    """Main entry point."""
    # Allow config path override via command line
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"

    config = load_config(config_path)
    validate_config(config)
    setup_logging(config)

    logger = logging.getLogger(__name__)
    logger.info("Navnet NMEA-to-MQTT Bridge starting")

    bridge = NMEABridge(config)

    # Handle graceful shutdown
    def handle_signal(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        bridge.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down...")
        bridge.stop()
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
