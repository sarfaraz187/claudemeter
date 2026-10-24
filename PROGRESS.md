# ClaudeMeter — progress

Goal: show Claude Code session % and weekly % on an M5GO IoT Kit (ESP32, 320x240, UIFlow1 firmware v1.11.5), at home and away (library, phone hotspot).

```
Anthropic API <-(20 min)- Mac server --POST--> Cloudflare Worker (+KV) <--GET (60s)-- M5GO
                          (also serves LAN /usage as a backup)
```

## Status (2026-10-24): working, including on the phone hotspot

- M5 reads from the Cloudflare Worker over HTTPS (tested: HTTPS works on firmware 1.11.5).
- Wi-Fi list on the M5: home first, then hotspot. On the hotspot the bars can take a few minutes to appear after boot.
- Script is saved on the M5 with UIFlow **Download**, so it starts at every power-up.

## Components

### Mac server (`claude_usage_server.py`, stdlib only)
- Polls `GET https://api.anthropic.com/api/oauth/usage` every 20 min (`POLL_SECONDS = 1200`) using the Claude Code token from the keychain.
- On HTTP 429: backs off (honors `Retry-After` if > 0, else doubles, max 2 h).
- Saves the last good data to `.usage_cache.json`, so restarts don't blank the screen. After a restart it waits until the cache is a full poll interval old before polling again.
- After each good poll it POSTs the JSON to the Worker (`push_to_relay`, uses `WORKER_URL` and `PUSH_SECRET` from `.env`). Needs a custom `user-agent`, otherwise Cloudflare may block Python's default.
- Still serves the same JSON on the LAN at `:8080/usage` (not used by the M5 anymore).
- `stale` is true after 3 missed polls (60 min).
- Auto-start: launchd agent `~/Library/LaunchAgents/com.user.claude-usage.plist` (RunAtLoad + KeepAlive). Restart with `launchctl kickstart -k gui/$(id -u)/com.user.claude-usage`. Error log: `/tmp/claude-usage.err`.

### Cloudflare Worker (`worker/`)
- A Worker (serverless function, no server to manage) named `claude-usage-relay`, plus one KV namespace `USAGE` holding one key (`latest`).
- `POST` with header `x-secret: <PUSH_SECRET>` stores the JSON and adds `pushed_at`.
- `GET` with header `x-secret: <READ_SECRET>` returns it, recomputing `stale` (true if `pushed_at` is older than 60 min, i.e. the Mac stopped pushing).
- Any other request gets 403. The `*.workers.dev` URL is public; the secrets are the protection.
- Only usage percentages and reset times are stored. The Claude token never leaves the Mac.
- Deploy: `cd worker && wrangler deploy`. Secrets: pipe the value into `wrangler secret put PUSH_SECRET` / `READ_SECRET`.
- Free tier is far above our traffic (about 1,500 requests/day).

### M5 script (`m5_usage_single.py` = template)
- Template holds placeholders. `python3 build_m5.py` fills them from `.env` and writes `m5_usage_flash.py` (gitignored). Paste that file into UIFlow (Python mode): **Run** to try, **Download** to keep.
- `build_m5.py <template> <output>` also accepts other template and output names.
- Layout mimics Claude Code's `/usage`: two bars, "NN% used", reset label, white pace marker (time elapsed in the window = vertical line; fill left of it means under pace).
- Anthropic dark palette: bg `0x141413`, text `0xFAF9F5`, secondary `0xB0AEA5`, bar `0xD97757`, track `0x3A3935`.
- LED bar (10 LEDs, pin 15): flickers 4 times when new data arrives, then off. Color follows the 5-hour session %: green <= 50, orange > 50, red > 85. Brightness scale 0.5.
- Status line: WiFi not connected / Server unreachable / STALE / Err: ... / OK.

## `.env` (gitignored)

`WIFI_SSID`, `WIFI_PASSWORD`, `HOTSPOT_SSID`, `HOTSPOT_PASSWORD`, `WORKER_URL`, `PUSH_SECRET`, `READ_SECRET`. `API_KEY` (old UIFlow key) is unused by the scripts.
- Values must be **unquoted**. Quoted secrets once broke the relay: the Worker secret was uploaded with the quotes, while the Python code strips them, so every push got 403.

## Lessons / gotchas

- **HTTP 429** from the usage endpoint at 120 s polling; undocumented limits, `Retry-After: 0`. 20 min works. Maybe try 15 min after a few hours without a 429.
- **UIFlow shows Disconnected** while Setup > **Switch mode** is USB. It must be **Internet mode**. Also check **Server Select** (global) and **Wi-Fi Select**.
- Hold **Button A** at power-on to open Setup (Startup Hold(1s) is ON). Download makes the script run at boot, so Setup is the way back in.
- Old UIFlow app `apps/Hello Prof.py` was removed in the UIFlow file manager.
- M5 needs a **2.4 GHz** hotspot; on Android set AP band 2.4 GHz and WPA2-Personal.
- A power cycle after only **Run** (no Download) leaves the M5 blank.
- Setup menu Wi-Fi (UIFlow cloud link) stores one network; the script's Wi-Fi list is separate. Away from home, Run/Download don't work unless Setup Wi-Fi points at the hotspot.

## Legacy files

- `main.py` + `config.py` (old two-file version reading the Mac's LAN IP) were deleted.
- `m5_https_test.py`: throwaway HTTPS check on the M5 (passed), deleted afterwards.

## Remaining

1. First git commit (nothing committed yet).
2. Edge cases to test: Mac asleep (Worker should flip to STALE after 60 min), expired token (401), Wi-Fi drop.
3. Reboot test: after a Mac reboot and login, check `launchctl list | grep claude-usage` and that the Worker's `pushed_at` advances. The service starts at login, not boot.
4. Optional: shorten the boot delay on the hotspot (shorter per-network timeout or hotspot first).

## Notes

- The usage endpoint is undocumented and may change. 401 means the token expired: open Claude Code once to refresh it.
- Reviewed two similar projects: `oauramos/claude-usage-stick` (standalone, reads rate-limit headers, token on device) and `yh1224/m5-claude-usage` (standalone, same endpoint, Core2/CoreS3 only). We kept the Mac-server approach so no token lives on the device. The pace marker came from the second one.
- Fallback if 429 persists: read `anthropic-ratelimit-unified-*` headers from a tiny Messages API call (header names unverified on this account).
