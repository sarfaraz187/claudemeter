# --- SETTINGS: edit these ---
# Filled in from .env by build_m5.py. Networks are tried in order.
WIFI_SSID = "HOME_SSID"
WIFI_PASSWORD = "HOME_PASSWORD"
HOTSPOT_SSID = "HOTSPOT_SSID"
HOTSPOT_PASSWORD = "HOTSPOT_PASSWORD"
WORKER_URL = "https://your-worker.workers.dev"
READ_SECRET = "READ_SECRET"
WIFI_NETWORKS = ((WIFI_SSID, WIFI_PASSWORD), (HOTSPOT_SSID, HOTSPOT_PASSWORD))
POLL_SECONDS = 300
# False = purple bars like Claude Code's /usage; True = green/yellow/red by percent
USE_THRESHOLD_COLORS = False
# --- END SETTINGS ---

from m5stack import lcd
import network
import time
import urequests
import machine
import neopixel

BLACK = 0x141413
WHITE = 0xFAF9F5
GREY = 0xB0AEA5
GREEN = 0x00CC00
YELLOW = 0xFFCC00
RED = 0xFF3333
PURPLE_FILL = 0xD97757
PURPLE_TRACK = 0x3A3935

BAR_X = 10
BAR_WIDTH = 220
BAR_HEIGHT = 18

LED_COUNT = 10
LED_PIN = 15
LED_BRIGHTNESS_SCALE = 0.5
LED_FLICKER_COUNT = 4
LED_FLICKER_SECONDS = 0.4
LED_GREEN = (0, 40, 0)
LED_ORANGE = (60, 20, 0)
LED_RED = (70, 0, 0)
LED_OFF = (0, 0, 0)
LED_ORANGE_ABOVE_PERCENT = 50
LED_RED_ABOVE_PERCENT = 85

led_bar = neopixel.NeoPixel(machine.Pin(LED_PIN), LED_COUNT)
last_data = None
last_flickered_timestamp = None


def fill_color_for(percent):
    if not USE_THRESHOLD_COLORS:
        return PURPLE_FILL
    if percent < 60:
        return GREEN
    if percent <= 85:
        return YELLOW
    return RED


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return True
    for network_name, network_password in WIFI_NETWORKS:
        wlan.connect(network_name, network_password)
        for _ in range(20):
            if wlan.isconnected():
                return True
            time.sleep(0.5)
        wlan.disconnect()
    return False


def fetch_usage():
    response = urequests.get(WORKER_URL, headers={"x-secret": READ_SECRET})
    try:
        return response.json()
    finally:
        response.close()


def draw_section(top, title, percent, reset_label, elapsed_percent):
    lcd.rect(0, top, 320, 80, BLACK, BLACK)
    lcd.font(lcd.FONT_DejaVu18)
    lcd.print(title, BAR_X, top, WHITE)
    lcd.rect(BAR_X, top + 28, BAR_WIDTH, BAR_HEIGHT, PURPLE_TRACK, PURPLE_TRACK)
    lcd.font(lcd.FONT_Default)
    if percent is None:
        lcd.print("n/a", BAR_X + BAR_WIDTH + 10, top + 30, GREY)
        return
    fill_width = int(BAR_WIDTH * min(percent, 100) / 100)
    if fill_width > 0:
        lcd.rect(BAR_X, top + 28, fill_width, BAR_HEIGHT, fill_color_for(percent), fill_color_for(percent))
    if elapsed_percent is not None:
        marker_x = BAR_X + int(BAR_WIDTH * min(elapsed_percent, 100) / 100)
        lcd.line(marker_x, top + 24, marker_x, top + 28 + BAR_HEIGHT + 4, WHITE)
    lcd.print("%d%% used" % int(percent), BAR_X + BAR_WIDTH + 10, top + 30, WHITE)
    lcd.print("Resets " + (reset_label or "?"), BAR_X, top + 54, GREY)


def draw_status(message, color):
    lcd.rect(0, 205, 320, 35, BLACK, BLACK)
    lcd.font(lcd.FONT_Default)
    lcd.print(message[:42], BAR_X, 215, color)


def fill_led_bar(color):
    scaled_color = tuple(int(channel * LED_BRIGHTNESS_SCALE) for channel in color)
    for led_index in range(LED_COUNT):
        led_bar[led_index] = scaled_color
    led_bar.write()


def led_color_for(session_percent):
    if session_percent is None:
        return LED_OFF
    if session_percent > LED_RED_ABOVE_PERCENT:
        return LED_RED
    if session_percent > LED_ORANGE_ABOVE_PERCENT:
        return LED_ORANGE
    return LED_GREEN


def flicker_led_bar(session_percent):
    led_color = led_color_for(session_percent)
    for _ in range(LED_FLICKER_COUNT):
        fill_led_bar(led_color)
        time.sleep(LED_FLICKER_SECONDS)
        fill_led_bar(LED_OFF)
        time.sleep(LED_FLICKER_SECONDS)


def draw_data(data):
    draw_section(8, "Current session", data.get("session_pct"),
                 data.get("session_reset_in") or data.get("session_reset_label"),
                 data.get("session_elapsed_pct"))
    draw_section(98, "Current week (all models)", data.get("week_pct"),
                 data.get("week_reset_in") or data.get("week_reset_label"),
                 data.get("week_elapsed_pct"))


def refresh():
    global last_data, last_flickered_timestamp
    if not connect_wifi():
        draw_status("WiFi not connected", RED)
        return
    try:
        data = fetch_usage()
    except Exception as fetch_error:
        draw_status("Server unreachable: " + str(fetch_error), RED)
        return
    last_data = data
    draw_data(data)
    if data.get("ts") != last_flickered_timestamp:
        last_flickered_timestamp = data.get("ts")
        flicker_led_bar(data.get("session_pct"))
    if data.get("error"):
        draw_status("Err: " + str(data["error"]), RED)
    elif data.get("stale"):
        draw_status("STALE - updated " + str(data.get("updated_ago", "?")), YELLOW)
    else:
        draw_status("OK - updated " + str(data.get("updated_ago", "?")), GREEN)


lcd.clear(BLACK)
draw_status("Connecting...", GREY)
while True:
    refresh()
    time.sleep(POLL_SECONDS)
