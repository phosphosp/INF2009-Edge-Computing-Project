CLOUD DEPLOYMENT & TESTING GUIDE (AWS + DOCKER)

SYSTEM OVERVIEW
The cloud system consists of the following components:

Mosquitto → MQTT broker (receives data)
Telegraf → consumes MQTT data and forwards to database
InfluxDB → time-series database
Grafana → dashboard visualization
Telegram Bridge → sends alerts to users

Data flow:
Raspberry Pi / Test Publisher → MQTT (Mosquitto) → Telegraf → InfluxDB → Grafana
→ Telegram Bridge → Telegram Alerts

START CLOUD STACK
Navigate to cloud directory:
cd cloud/aws
Start services:
docker compose up -d

Check containers:
docker compose ps

Expected services:
mosquitto
influxdb
telegraf
grafana
telegram-bridge

ACCESS GRAFANA DASHBOARD
Open browser:
http://localhost:3000

Login:
Username: admin
Password: change-this-password

You should see the Fire Detection Dashboard.

TEST MQTT DATA FLOW

OPTION A — PowerShell

$payload = @{
fire_score = 0.99
vision_confidence = 0.98
raw_avg_temp = 70.2
uptime_seconds = 300
decision = "FIRE"
door_state = "OPEN"
type = "event"
sim_active = "true"
gas_detected = "true"
temp_flagged = "true"
timestamp = "2026-03-21T15:10:00"
} | ConvertTo-Json -Compress

$payload | docker run --rm -i eclipse-mosquitto:2 --network container:fire-mosquitto
mosquitto_pub -h localhost -p 1883 `
-t fire_detection/events -s

OPTION B — Using test script

Ensure config is set:

MQTT_BROKER=host.docker.internal
MQTT_PORT=1883

Run:
python test_mqtt.py

VERIFY DASHBOARD
Open Grafana and check:
fire_score
temperature
decision

Data should update after publishing.

TEST TELEGRAM ALERTS
Ensure .env contains:

TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

Check logs:
docker compose logs -f telegram-bridge

Publish a FIRE event.
Expected log:
MQTT message received topic=fire_detection/events
Telegram send success for decision=FIRE

You should receive a Telegram message.

RATE LIMITING
Default:
TELEGRAM_RATE_LIMIT_SECONDS=60
This prevents repeated alerts within 60 seconds.

For testing:
TELEGRAM_RATE_LIMIT_SECONDS=5

DEBUGGING
No Telegram alerts:
docker compose logs -f telegram-bridge
Check for:
MQTT message received
rate-limited
duplicate payload

No dashboard updates:
docker compose logs -f telegraf

Test MQTT directly:
docker run --rm -it eclipse-mosquitto:2 mosquitto_sub -h host.docker.internal -p 1883
-t "fire_detection/#" -v

EXPECTED RESULT
After setup:

MQTT messages appear in Grafana
Telegram alerts trigger for FIRE events
System avoids duplicate/spam alerts