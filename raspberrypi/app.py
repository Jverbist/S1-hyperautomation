from fastapi import FastAPI, BackgroundTasks
from gpiozero import LED
from time import sleep

app = FastAPI(title="Pi Lamp API")

# Use GPIO17 (pin 11) — change if needed
relay = LED(17)

@app.get("/lamp/on")
def lamp_on():
    relay.on()
    return {"status": "on"}

@app.get("/lamp/off")
def lamp_off():
    relay.off()
    return {"status": "off"}

@app.get("/lamp/flash")
def lamp_flash(duration: int = 5, flashes: int = 5, bg: BackgroundTasks = None):
    def _flash():
        for _ in range(flashes):
            relay.on()
            sleep(duration / (flashes * 2))
            relay.off()
            sleep(duration / (flashes * 2))
    bg.add_task(_flash)
    return {"status": "flashing", "duration": duration, "flashes": flashes}

@app.get("/health")
def health():
    return {"ok": True}
