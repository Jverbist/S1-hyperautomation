# 🔦 Purple Lamp Hyperautomation Demo  
SentinelOne → n8n → Raspberry Pi → Relay → Purple Lamp

This guide explains how to build the project yourself from scratch:

1. Prepare a Raspberry Pi with a relay and lamp  
2. Run a small FastAPI service to control the relay  
3. Deploy n8n in Docker behind Traefik with HTTPS  
4. Wire SentinelOne webhooks into n8n  
5. (Optional) Add an AI-based health check for the Pi service  

## 1. Prerequisites

- **Raspberry Pi** (3B/4/5) with Raspberry Pi OS
- **2-channel 5 V relay module** (JD-VCC / VCC / GND / IN1 / IN2)
- **12 V or 230 V lamp** with PSU or power source (wired safely through the relay)
- **n8n server** (Linux VM or bare metal) with:
  - Docker + Docker Compose
  - Public DNS name for n8n webhooks, e.g. `n8n.fake-nmbs.be`
- **SentinelOne** tenant which supports outgoing webhooks
- Basic familiarity with:
  - SSH into Linux
  - Editing YAML / systemd files
  - Basic networking / DNS

---

## 2. Raspberry Pi: Lamp API Setup

The Pi will expose a small HTTP API that drives a relay connected to a purple lamp.

### 2.1. OS preparation

On the Raspberry Pi:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git
```

Create a folder for the app:

```bash
sudo mkdir -p /opt/lampapi/app
sudo chown -R $USER:$USER /opt/lampapi
cd /opt/lampapi/app
```

### 2.2 Python virtual environment & dependencies

```bash
python3 -m venv /opt/lampapi/venv
source /opt/lampapi/venv/bin/activate

pip install --upgrade pip
pip install fastapi uvicorn gpiozero
```

### 2.3 Create the API `(lamp_api.py)`

Create `/opt/lampapi/app/lamp_api.py`:
```python
from fastapi import FastAPI
from gpiozero import LED
from time import sleep

app = FastAPI()

# Relay on GPIO 17 (Pin 11), active low
relay = LED(17, active_high=False)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/lamp/on")
def lamp_on(duration: int = 8, flashes: int = 8):
    """
    Turn the lamp on in a flashing pattern.
    duration: total seconds the pattern should last
    flashes: number of on/off cycles
    """
    if flashes <= 0:
        flashes = 1
    on_time = duration / (flashes * 2)
    off_time = on_time

    for _ in range(flashes):
        relay.on()
        sleep(on_time)
        relay.off()
        sleep(off_time)

    return {"status": "ok", "duration": duration, "flashes": flashes}

@app.post("/lamp/off")
def lamp_off():
    relay.off()
    return {"status": "off"}
```

### 2.4 Test the API manually

From the Pi:
```bash
source /opt/lampapi/venv/bin/activate
python -m uvicorn lamp_api:app --host 0.0.0.0 --port 8000
```

In another terminal:
```bash
curl http://<raspberyip>:8000/health
curl -X POST "http://<raspberyip>:8000/lamp/on?duration=4&flashes=2"
```
You should see the relay click (once wiring is done).
 
### 2.5 Run as a systemd service

Create `/etc/systemd/system/lampapi.service`:
```bash
[Unit]
Description=Raspberry Pi Lamp API (FastAPI + Uvicorn)
After=network.target

[Service]
User=pi
WorkingDirectory=/opt/lampapi/app
Environment="GPIOZERO_PIN_FACTORY=lgpio"
ExecStart=/opt/lampapi/venv/bin/uvicorn lamp_api:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable lampapi
sudo systemctl start lampapi
sudo systemctl status lampapi
```

Verify:
```bash
curl http://<raspberryip>:8000/health
```

---

## 3. Hardware: Wiring the Relay & Lamp

### 3.1. Relay → Raspberry Pi wiring
Relay module pins (usually labeled):
* `JD-VCC`
* `VCC`
* `GND`
* `GND`
* `IN1`
* `IN2`
---
![](/media/2-channel-relay.jpg)
---

| Relay Pin | Raspberry Pi Pin | Description                 |
| --------- | ---------------- | --------------------------- |
| VCC       | 5 V (Pin 2 or 4) | Power for relay module      |
| GND       | GND (Pin 6)      | Ground                      |
| IN1       | GPIO 17 (Pin 11) | Control for relay channel 1 |
---
![](/media/IMG_1838.JPG)
---

**Make sure:**
The jumper between JD-VCC and VCC is present on the relay board.
The relay board’s PWR LED is bright when 5 V and GND are connected.

### 3.2. Lamp wiring (via relay)
**Warning**: If you are switching voltage (230 V), only do this if you know what you are doing. Otherwise use a 12 V lamp and PSU.

**Basic idea**:

Use the relay’s COM and NO terminals as a switch in series with the lamp’s power line.
Leave the neutral/ground correctly wired and only break the “live” side through the relay.
**Example (low-voltage)**:

Power supply `+` → relay COM

Relay NO → lamp `+`

Lamp `-` → power supply `-`

When the relay closes, the circuit completes and the lamp turns on.

---
## 4. n8n + Traefik Deployment
n8n will accept webhooks and call the Pi’s API.

### 4.1. Directory layout

On the n8n server `(Linux server that can access the PI)`
```bash
mkdir -p ~/n8n-compose
cd ~/n8n-compose
```
Create `.env`:
```bash
DOMAIN_NAME= public/private domain
SUBDOMAIN= n8n
GENERIC_TIMEZONE= Europe/Brussels
SSL_EMAIL= you@your-domain.tld
```
### 4.2. `docker-compose.yml` (n8n + Traefik)
Create `docker-compose.yml`:
```docker
services:
  traefik:
    image: traefik
    restart: always
    command:
      - "--api.insecure=false"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.mytlschallenge.acme.httpchallenge=true"
      - "--certificatesresolvers.mytlschallenge.acme.httpchallenge.entrypoint=web"
      - "--certificatesresolvers.mytlschallenge.acme.email=${SSL_EMAIL}"
      - "--certificatesresolvers.mytlschallenge.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - traefik_data:/letsencrypt
      - /var/run/docker.sock:/var/run/docker.sock:ro

  n8n:
    image: docker.n8n.io/n8nio/n8n
    restart: always
    ports:
      - "127.0.0.1:5678:5678"   # editor local-only
    labels:
      - traefik.enable=true

      # Public webhooks (production)
      - traefik.http.routers.n8n-webhooks.rule=Host(`${SUBDOMAIN}.${DOMAIN_NAME}`) && PathPrefix(`/webhook`)
      - traefik.http.routers.n8n-webhooks.entrypoints=websecure
      - traefik.http.routers.n8n-webhooks.tls=true
      - traefik.http.routers.n8n-webhooks.tls.certresolver=mytlschallenge

      # Public webhooks (test)
      - traefik.http.routers.n8n-webhooks-test.rule=Host(`${SUBDOMAIN}.${DOMAIN_NAME}`) && PathPrefix(`/webhook-test`)
      - traefik.http.routers.n8n-webhooks-test.entrypoints=websecure
      - traefik.http.routers.n8n-webhooks-test.tls=true
      - traefik.http.routers.n8n-webhooks-test.tls.certresolver=mytlschallenge

      # Editor (optional, via internal DNS like n8n.exn.local)
      - traefik.http.routers.n8n-editor.rule=Host(`n8n.exn.local`)
      - traefik.http.routers.n8n-editor.entrypoints=websecure
      - traefik.http.routers.n8n-editor.tls=true

      # Service port
      - traefik.http.services.n8n.loadbalancer.server.port=5678
    environment:
      - N8N_HOST=${SUBDOMAIN}.${DOMAIN_NAME}
      - N8N_PORT=5678
      - N8N_PROTOCOL=https
      - WEBHOOK_URL=https://${SUBDOMAIN}.${DOMAIN_NAME}
      - GENERIC_TIMEZONE=${GENERIC_TIMEZONE}
      - TZ=${GENERIC_TIMEZONE}
    volumes:
      - n8n_data:/home/node/.n8n
      - ./local-files:/files

volumes:
  n8n_data:
  traefik_data:
```

### 4.3. Start the stack

```bash
docker compose up -d
```
Check Traefik has a certificate:
```bash
curl -I https://n8n.fake-nmbs.be/webhook-test/healthcheck
# Expect HTTP/2 404 (from n8n) once it's up
```

### 4.4. Accessing the n8n editor

* From the n8n host: open http://127.0.0.1:5678
* Or via SSH port forwarding:
```bash
ssh -L 5678:127.0.0.1:5678 user@n8n-host
```

Then browse: `http://localhost:5678`

If you configured internal DNS for your domain pointing to the n8n server, you can also use: `https://<FQDN>` from inside the network.

---

## 5. n8n Flow: Trigger Lamp from Webhook
This workflow receives a webhook and triggers the Pi lamp.

Import the json workflows from the git repo and import them into n8n 

### 5.1 Test the workflow
With the workflow not active, click Execute Workflow.

From any machine:
```bash
curl -X POST "https://n8n.<domain>/webhook-test/s1/lamp" \
  -H "Content-Type: application/json" \
  -d '{"severity": "high"}'
```
You should see:
* n8n workflow execution
* Pi relay clicking and lamp flashing

### 5.2. Activate for production

When the workflow behaves correctly:
* Activate it in n8n
* Use the Production URL shown in the Webhook node:
```bash
https://n8n.<domain>/webhook/s1/lamp
```
---
## 6. Troubleshooting
**Relay doesn’t click:**
* Check relay VCC is on 5 V, not 3.3 V
* Check ground is shared with the Pi
* Confirm the jumper between JD-VCC and VCC
* Test manually on the Pi:
```bash
python3
>>> from gpiozero import LED
>>> r = LED(17, active_high=False)
>>> r.on()
>>> r.off()
```

**API not reachable:**
* sudo systemctl status lampapi
* Check firewall rules between n8n host and Pi
* Confirm Pi’s IP address in the HTTP Request node

**Webhook not triggering:**
* Use the Test URL when workflow is not active (/webhook-test/)
* Use the Production URL when workflow is active (/webhook/)
* Check Traefik logs and n8n logs:
    * `docker logs traefik`
    * `docker logs n8n`

