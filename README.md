# Fire Detection System - INF2009

## Project Structure

```
INF2009-Edge-Computing-Project/
├── main.py                        # Orchestrator
├── config.py                      # All pins, thresholds, timing
│
├── sensors/
│   ├── gas_sensor.py              # MQ2 digital read + debounce
│   └── temp_sensor.py             # DHT22 background thread + averaging
│
├── actuators/
│   ├── alarm.py                   # LED + buzzer (CLEAR / WARNING / FIRE states)
│   └── smart_door.py              # RFID reader + servo (normal / fire modes)
│
├── utils/
│   └── fusion.py                  # Weighted score engine + sim override injection
│
├── comms/
│   └── mqtt_client.py             # Non-blocking MQTT publisher
│
├── sim/
│   ├── sim_flags.py               # Flag file read/write API
│   └── sim_gui.py                 # Demo GUI - run in separate terminal
│
├── tests/
│   ├── test_sensors.py
│   ├── test_actuators.py
│   ├── test_fusion.py
│   └── test_mqtt.py
```

---

## Hardware Pin Reference (BCM / Physical)

![Breadboard Wiring Diagram](readme_images/wiring.png)

| Component     | Signal        | GPIO (BCM) | Physical Pin |
|---------------|---------------|------------|--------------|
| MQ2           | DO            | GPIO 17    | Pin 11       |
| DHT22         | DAT           | GPIO 4     | Pin 7        |
| LED           | Signal        | GPIO 24    | Pin 18       |
| Buzzer        | PWM           | GPIO 23    | Pin 16       |
| Servo         | PWM signal    | GPIO 18    | Pin 12       |
| RFID SDA      | SPI CE0       | GPIO 8     | Pin 24       |
| RFID SCK      | SPI CLK       | GPIO 11    | Pin 23       |
| RFID MOSI     | SPI MOSI      | GPIO 10    | Pin 19       |
| RFID MISO     | SPI MISO      | GPIO 9     | Pin 21       |
| RFID RST      | Reset         | GPIO 25    | Pin 22       |
| RFID VCC      | 3.3V only     | -          | Pin 1        |
| GND           | Ground        | -          | Pin 6        |
| 5V VCC        | 5V            | -          | Pin 4        |

---

## Setup

### 1. Enable SPI (for RFID)
```bash
sudo raspi-config
# Interface Options -> SPI -> Enable -> Reboot
```

### 2. Install dependencies
```bash
sudo apt update
sudo apt install python3-pip mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto

python -m pip install --upgrade pip setuptools wheel
python -m pip install rpi-lgpio gpiozero mfrc522 spidev adafruit-circuitpython-dht paho-mqtt python-dotenv
```

### 3. 
```bash
Transfer code over to RPI:

scp -r "C:\Users\example\INF2009-Edge-Computing-Project" <Raspberry Pi Name>@:<Raspberry Pi IP>/home/<Raspberry Pi Name>/
```

### 4. 
```bash
Create Virtual Environment in RPI:

cd INF2009-Edge-Computing-Project
python -m venv venv

Activate venv:
source venv/bin/activate
```

---

## Running the System

### Full system
```bash
# Terminal 1 - main system
python main.py

# Terminal 2 - simulation GUI (optional, for demos)
python sim/sim_gui.py

# Terminal 3 - watch MQTT messages (optional)
mosquitto_sub -h localhost -t "fire_detection/#" -v
```

### Individual component tests
```bash
python test_sensors.py      # gas + temp only
python test_actuators.py    # LED, buzzer, servo, RFID only
python test_fusion.py       # scoring logic, no hardware needed
python test_mqtt.py         # MQTT publish/subscribe
```

---

## Fusion Score Reference

| Sensors triggered         | Score | Decision |
|---------------------------|-------|----------|
| None                      | 0.0   | CLEAR    |
| Temp only                 | 0.2   | WARNING  |
| Gas only                  | 0.4   | WARNING  |
| Gas + Temp                | 0.6   | FIRE     |
| Gas + Temp + Vision (1.0) | 1.0   | FIRE     |

Weights: Gas=0.4, Temp=0.2, Vision=0.4 (Vision=0.0 until Jetson integrated)
Fire threshold: 0.5 - tune in config.py

---

## Demo Guide (Simulation GUI)

| Button        | What it does                                          |
|---------------|-------------------------------------------------------|
|  Full Fire    | Injects gas+temp+vision - triggers FIRE state         |
|  Gas Only     | Injects gas only - triggers WARNING (LED on, no buzz) |
|  Temp Only    | Injects temp only - triggers WARNING                  |
|  Clear        | Resets all scenarios - system returns to sensor reads |
|  Force Alarm  | Bypasses score - forces buzzer+LED on immediately     |
|  Lock Door    | Forces servo to locked position                       |
|  Unlock Door  | Forces servo to unlocked position                     |

---

## Integrating Jetson AI (future)

In `main.py`, replace:
```python
result = evaluate(gas_detected, temp_flagged, vision_confidence=0.0)
```
With:
```python
vision_conf = jetson_client.get_latest_confidence()
result = evaluate_with_vision(gas_detected, temp_flagged, vision_conf)
```

Import `evaluate_with_vision` from `utils.fusion` - the function already exists,
weights are already allocated, no other changes needed.