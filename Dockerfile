FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY nmea_mqtt_bridge/ nmea_mqtt_bridge/

# Run as non-root
RUN useradd -r -s /bin/false navnet
USER navnet

CMD ["python", "-m", "nmea_mqtt_bridge"]
