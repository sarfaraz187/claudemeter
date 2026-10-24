<div align="center">

# ClaudeMeter

### Your Claude limits, on your desk.

ClaudeMeter shows your Claude Code **5-hour session** and **weekly** usage on an M5Stack M5GO. Two bars with a pace marker tell you whether you're burning through your limit too fast, and the side LEDs flicker green, orange or red as you approach it. It works at home and on a phone hotspot, so you can glance at it in a library or office without opening a terminal.

![device](https://img.shields.io/badge/device-M5GO-orange)
![firmware](https://img.shields.io/badge/firmware-UIFlow%201.11-blue)
![relay](https://img.shields.io/badge/relay-Cloudflare%20Workers-f38020)
![server](https://img.shields.io/badge/server-Python%203-3776ab)
![network](https://img.shields.io/badge/works%20on-phone%20hotspot-success)

</div>

> Unofficial hobby project. Not affiliated with or endorsed by Anthropic.

## Screenshots

<!-- Add photos to an assets/ folder, then link them here, e.g.
![ClaudeMeter on an M5GO](assets/device.jpg)
Check photos for your Wi-Fi name or API key before committing. -->

## How it works

```
Anthropic API <-- Mac server --POST--> Cloudflare Worker + KV <--GET-- M5GO
```

- The **Mac server** reads usage with your Claude Code login (kept in the keychain) every 20 minutes and pushes the percentages to the Worker.
- The **Worker** stores the latest numbers and serves them over HTTPS to the M5.
- The **M5** polls the Worker every minute and draws two bars plus a pace marker. The side LEDs flicker 4 times on each new update: green up to 50%, orange above 50%, red above 85% (session usage).
- Your Claude token never leaves the Mac. Cloudflare only holds percentages and reset times.

## Files

| File | Purpose |
|---|---|
| `claude_usage_server.py` | Mac server: polls Anthropic, pushes to the Worker, serves LAN `/usage` |
| `worker/` | Cloudflare Worker (`index.js`, `wrangler.toml`) |
| `m5_usage_single.py` | M5 script template (placeholders only, safe to commit) |
| `build_m5.py` | Fills the template from `.env` into `m5_usage_flash.py` |
| `PROGRESS.md` | Status, decisions, gotchas |
| `.env.example` | Template for your local `.env` |

## Setup

### What you need

- An **M5Stack M5GO** (or any ESP32 Core running **UIFlow 1.x** firmware) and a USB power source. No data cable is needed for this setup.
- A Mac with **Claude Code installed and logged in**, and **Python 3**. The server only uses the standard library.
- A free **Cloudflare** account and **Node.js** (for the `wrangler` CLI).
- A **2.4 GHz** Wi-Fi network. The ESP32 can't join 5 GHz. A phone hotspot works as a second network.

### 1. Get the code

```bash
git clone https://github.com/<your-user>/claudemeter.git
cd claudemeter
cp .env.example .env
```

Fill in `.env` as you go. Values must be unquoted, and `.env` is gitignored.

### 2. Deploy the Cloudflare Worker

The Worker is the relay between your Mac and the M5, so the M5 works on any network without knowing your Mac's IP.

```bash
npm install -g wrangler
wrangler login

cd worker
wrangler kv namespace create USAGE
```

Copy the printed namespace `id` into `worker/wrangler.toml`. Then generate two random secrets and put them in `.env` as `PUSH_SECRET` and `READ_SECRET`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # run twice
```

Deploy and upload the secrets:

```bash
wrangler deploy
printf '%s' "<your PUSH_SECRET>" | wrangler secret put PUSH_SECRET
printf '%s' "<your READ_SECRET>" | wrangler secret put READ_SECRET
cd ..
```

`wrangler deploy` prints your Worker URL (`https://claude-usage-relay.<subdomain>.workers.dev`). Put it in `.env` as `WORKER_URL`. Check it:

```bash
curl -i https://<your-worker-url>        # expect 403 (no secret)
```

### 3. Run the Mac server

Make sure Claude Code is logged in, then test one poll:

```bash
python3 claude_usage_server.py --once
```

You should see JSON with `session_pct` and `week_pct`, and `"error": null`. Then run the server:

```bash
python3 claude_usage_server.py
```

It polls Anthropic every 20 minutes and pushes each result to your Worker. Confirm the relay got it:

```bash
curl -s -H "x-secret: <your READ_SECRET>" https://<your-worker-url>
```

**Start at login (optional):** create `~/Library/LaunchAgents/com.user.claude-usage.plist` that runs `python3 /path/to/claude_usage_server.py` with `RunAtLoad` and `KeepAlive` set to true, then `launchctl load` it. If Python can't verify TLS certificates, add `SSL_CERT_FILE` (the `certifi` bundle path) to its `EnvironmentVariables`. The server must be running whenever you want fresh numbers. If the Mac sleeps, the M5 shows STALE after an hour.

### 4. Set up the M5GO

1. **Setup menu:** power the M5 on while holding **Button A** (left). In the menu, use left = up, middle = enter, right = down.
2. **Switch mode** to **Internet mode**. USB mode disables the cloud link.
3. **Wi-Fi via AP:** the M5 creates a network named `M5-xxxx`. Join it from your laptop, open `http://192.168.4.1`, enter your Wi-Fi name and password, and submit.
4. **Generate new apikey**, then **Reboot**. The screen shows an 8-character **API KEY**.
5. Open https://flow.m5stack.com, choose **UIFlow 1.0** and the Core device, click the key area at the bottom left, and enter the API KEY. Wait for the status to show **Connected**. Refresh the page if it doesn't.

### 5. Flash ClaudeMeter

Add your Wi-Fi details to `.env` (`WIFI_SSID`, `WIFI_PASSWORD`, and optionally a second network as `HOTSPOT_SSID` and `HOTSPOT_PASSWORD`), then generate the script:

```bash
python3 build_m5.py
```

This writes `m5_usage_flash.py` with your Wi-Fi details and Worker URL filled in. The file contains secrets, is gitignored, and should never be shared.

1. In UIFlow, switch the editor to **Python**, delete the existing code, and paste the contents of `m5_usage_flash.py`.
2. Click **Run**. After a few seconds you should see the bars and the LEDs flicker once.
3. Click **Download** to save the script on the M5, so it starts at every power-up. Without Download, a power cycle leaves the M5 blank.

To change anything later, edit `m5_usage_single.py` (never put secrets in it), run `build_m5.py` again, and paste, Run and Download. If the app starts at boot and blocks you, hold **Button A** at power-on to return to the Setup menu.

### Tuning

Settings are at the top of `m5_usage_single.py` and `claude_usage_server.py`:

| Setting | Default | Meaning |
|---|---|---|
| `POLL_SECONDS` (server) | 1200 | How often the Mac asks Anthropic. Lower values risk HTTP 429. |
| `POLL_SECONDS` (M5) | 60 | How often the M5 asks the Worker |
| `LED_ORANGE_ABOVE_PERCENT` / `LED_RED_ABOVE_PERCENT` | 50 / 85 | LED color thresholds for the session |
| `LED_FLICKER_COUNT` | 4 | Blinks per update |
| `LED_BRIGHTNESS_SCALE` | 0.5 | LED brightness |

## Troubleshooting

| Symptom | Fix |
|---|---|
| UIFlow says **Disconnected** | Setup > Switch mode must be Internet; check Server Select and Wi-Fi Select |
| Can't reach Setup (app starts at boot) | Hold **Button A** while powering on |
| "WiFi not connected" on a hotspot | 2.4 GHz band, WPA2-Personal, exact SSID; allow a few minutes at boot |
| HTTP 429 on screen | Anthropic rate limit; the server backs off automatically |
| Push gets 403 | Secrets in `.env` must match the Worker's and be unquoted; re-upload with `wrangler secret put` |
| STALE | The Mac hasn't pushed for over an hour (asleep or offline) |
| Blank screen after power cycle | The script wasn't saved with **Download** |
| 401 from Anthropic | Token expired; open Claude Code once |

## Security notes

- The Worker URL is public; requests without the right `x-secret` get 403. Keep `.env` and `*_flash.py` out of git (already in `.gitignore`).
- The generated `m5_usage_flash.py` and the M5 itself hold your Wi-Fi password in plain text; UIFlow's cloud also sees it when you push code.
- The usage endpoint is undocumented and rate limited; it may change.
