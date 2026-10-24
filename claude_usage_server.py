#!/usr/bin/env python3
"""
Polls Claude Code's undocumented usage endpoint and serves a small flat JSON
on your LAN, so a small device (e.g. M5Go) can display it.

Usage:
  python3 claude_usage_server.py --once        # fetch once, print the flat JSON, exit
  python3 claude_usage_server.py --once --raw  # fetch once, print the raw API response
  python3 claude_usage_server.py               # poll + serve on port 8080

Standard library only (uses certifi for CA certs if it is importable).
The OAuth token is read locally and NEVER served, printed, or logged.
"""
import ipaddress
import json
import os
import platform
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
POLL_SECONDS = 1200
MAX_BACKOFF_SECONDS = 7200
CACHE_PATH = Path(__file__).parent / ".usage_cache.json"
ENV_PATH = Path(__file__).parent / ".env"
STALE_AFTER_SECONDS = 3 * POLL_SECONDS
PORT = 8080

# Observed field names (undocumented endpoint, may change)
SESSION_KEY = "five_hour"
WEEK_KEY = "seven_day"
SESSION_WINDOW_SECONDS = 5 * 3600
WEEK_WINDOW_SECONDS = 7 * 86400

TOKEN_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")

state_lock = threading.Lock()
last_good: Optional[dict[str, Any]] = None  # parsed values + "ok_ts"
last_error: Optional[str] = "no data yet"


def build_ssl_context() -> ssl.SSLContext:
    """Verified TLS; prefer certifi's CA bundle (python.org builds ship without system CAs)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = build_ssl_context()


def scrub(message: str) -> str:
    return TOKEN_PATTERN.sub("[REDACTED]", message)


def read_credentials_json() -> dict[str, Any]:
    """Return the parsed credentials JSON that Claude Code stores."""
    if platform.system() == "Darwin":
        completed = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=15,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return json.loads(completed.stdout)
    path = os.path.join(os.path.expanduser("~"), ".claude", ".credentials.json")
    with open(path) as credentials_file:
        return json.load(credentials_file)


def get_token() -> str:
    credentials = read_credentials_json()
    try:
        return credentials["claudeAiOauth"]["accessToken"]
    except KeyError:
        raise RuntimeError(
            "accessToken not found; top-level keys are: " + ", ".join(credentials.keys())
        )


def fetch_usage() -> dict[str, Any]:
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {get_token()}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10, context=SSL_CONTEXT) as response:
        return json.load(response)


def parse_window(raw: dict[str, Any], key: str) -> tuple[float, float]:
    """Return (percent, reset_epoch) for a usage window, or raise if missing/malformed."""
    window = raw.get(key)
    if not isinstance(window, dict):
        raise ValueError(f"'{key}' missing in API response")
    utilization = window.get("utilization")
    resets_at = window.get("resets_at")
    if not isinstance(utilization, (int, float)) or not isinstance(resets_at, str):
        raise ValueError(f"'{key}' has unexpected shape")
    return float(utilization), datetime.fromisoformat(resets_at).timestamp()


def parse_usage(raw: dict[str, Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for prefix, key in (("session", SESSION_KEY), ("week", WEEK_KEY)):
        try:
            percent, reset_epoch = parse_window(raw, key)
            parsed[f"{prefix}_pct"] = round(percent, 1)
            parsed[f"{prefix}_reset"] = int(reset_epoch)
        except ValueError:
            parsed[f"{prefix}_pct"] = None
            parsed[f"{prefix}_reset"] = None
    if parsed["session_pct"] is None and parsed["week_pct"] is None:
        raise ValueError("no usage windows found in API response")
    return parsed


def format_remaining(reset_epoch: Optional[int], now: float) -> Optional[str]:
    if reset_epoch is None:
        return None
    seconds = int(reset_epoch - now)
    if seconds <= 0:
        return "now"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"in {days}d {hours}h"
    if hours:
        return f"in {hours}h {minutes}m"
    return f"in {minutes}m"


def elapsed_percent(reset_epoch: Optional[int], window_seconds: int, now: float) -> Optional[float]:
    """How far through the usage window we are; the M5 draws it as a pace marker."""
    if reset_epoch is None:
        return None
    elapsed_seconds = now - (reset_epoch - window_seconds)
    return round(min(max(elapsed_seconds / window_seconds * 100, 0), 100), 1)


def local_timezone_name() -> str:
    resolved = os.path.realpath("/etc/localtime")
    marker = "zoneinfo/"
    if marker in resolved:
        return resolved.split(marker, 1)[1]
    return time.tzname[0]


def format_reset_label(reset_epoch: Optional[int]) -> Optional[str]:
    """Mirrors Claude Code's /usage text: '5:19pm (Europe/Berlin)' today, 'Oct 28 at 3:59am (...)' otherwise."""
    if reset_epoch is None:
        return None
    reset_time = datetime.fromtimestamp(reset_epoch)
    clock = reset_time.strftime("%I:%M%p").lstrip("0").lower()
    if reset_time.date() == datetime.now().date():
        label = clock
    else:
        label = f"{reset_time.strftime('%b')} {reset_time.day} at {clock}"
    return f"{label} ({local_timezone_name()})"


def build_response() -> dict[str, Any]:
    """Flat JSON for the M5. Values come from the last good poll; staleness is computed per request."""
    now = time.time()
    with state_lock:
        good = dict(last_good) if last_good else None
        error = last_error
    if good is None:
        return {
            "session_pct": None, "week_pct": None,
            "session_reset": None, "week_reset": None,
            "session_reset_in": None, "week_reset_in": None,
            "session_elapsed_pct": None, "week_elapsed_pct": None,
            "session_reset_label": None, "week_reset_label": None,
            "ts": None, "stale": True, "error": error,
        }
    return {
        "session_pct": good["session_pct"],
        "week_pct": good["week_pct"],
        "session_reset": good["session_reset"],
        "week_reset": good["week_reset"],
        "session_reset_in": format_remaining(good["session_reset"], now),
        "week_reset_in": format_remaining(good["week_reset"], now),
        "session_elapsed_pct": elapsed_percent(good["session_reset"], SESSION_WINDOW_SECONDS, now),
        "week_elapsed_pct": elapsed_percent(good["week_reset"], WEEK_WINDOW_SECONDS, now),
        "session_reset_label": format_reset_label(good["session_reset"]),
        "week_reset_label": format_reset_label(good["week_reset"]),
        "ts": int(good["ok_ts"]),
        "stale": (now - good["ok_ts"]) > STALE_AFTER_SECONDS,
        "error": error,
    }


def read_env_value(name: str) -> Optional[str]:
    try:
        for line in ENV_PATH.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == name:
                return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def push_to_relay(usage_snapshot: dict[str, Any]) -> None:
    relay_url = read_env_value("WORKER_URL")
    push_secret = read_env_value("PUSH_SECRET")
    if not relay_url or not push_secret:
        return
    request = urllib.request.Request(
        relay_url,
        data=json.dumps(usage_snapshot).encode(),
        headers={"x-secret": push_secret, "content-type": "application/json", "user-agent": "claude-usage-server/1.0"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=10, context=SSL_CONTEXT).close()
    except Exception as push_error:  # relay is optional; local /usage keeps working
        print("relay push failed:", scrub(f"{type(push_error).__name__}: {push_error}"), file=sys.stderr)


def save_cache(good_data: dict[str, Any]) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(good_data))
    except OSError:
        pass  # cache is best-effort; losing it only blanks the screen after a restart


def load_cache() -> None:
    global last_good, last_error
    try:
        cached = json.loads(CACHE_PATH.read_text())
    except (OSError, ValueError):
        return
    if isinstance(cached, dict) and isinstance(cached.get("ok_ts"), (int, float)):
        with state_lock:
            last_good = cached
            last_error = None


def poll_once() -> Optional[int]:
    """Poll once; return a server-requested retry delay in seconds on HTTP 429."""
    global last_good, last_error
    try:
        parsed = parse_usage(fetch_usage())
        with state_lock:
            last_good = {**parsed, "ok_ts": time.time()}
            last_error = None
        save_cache(last_good)
        push_to_relay(build_response())
    except urllib.error.HTTPError as http_error:
        message = f"HTTP {http_error.code}"
        retry_after_seconds: Optional[int] = None
        if http_error.code == 401:
            message += " (token expired; open Claude Code once to refresh it)"
        elif http_error.code == 429:
            message += " (rate limited, backing off)"
            retry_after_header = http_error.headers.get("Retry-After", "")
            retry_after_seconds = int(retry_after_header) if retry_after_header.isdigit() else 0
        with state_lock:
            last_error = message
        return retry_after_seconds
    except Exception as unexpected_error:  # keep serving the last good data
        with state_lock:
            last_error = scrub(f"{type(unexpected_error).__name__}: {unexpected_error}")
    return None


def poll_loop() -> None:
    backoff_seconds = POLL_SECONDS
    load_cache()
    with state_lock:
        cache_age_seconds = time.time() - last_good["ok_ts"] if last_good else None
    if cache_age_seconds is not None and cache_age_seconds < POLL_SECONDS:
        time.sleep(POLL_SECONDS - cache_age_seconds)
    while True:
        retry_after_seconds = poll_once()
        if retry_after_seconds is None:
            backoff_seconds = POLL_SECONDS
        else:
            backoff_seconds = min(max(retry_after_seconds, backoff_seconds * 2), MAX_BACKOFF_SECONDS)
        time.sleep(backoff_seconds)


def is_lan_client(address: str) -> bool:
    client_ip = ipaddress.ip_address(address)
    return client_ip.is_private or client_ip.is_loopback


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not is_lan_client(self.client_address[0]):
            self.send_response(403)
            self.end_headers()
            return
        if self.path.split("?")[0] != "/usage":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(build_response()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # silence request logging
        pass


def main() -> None:
    if "--once" in sys.argv:
        if "--raw" in sys.argv:
            print(json.dumps(fetch_usage(), indent=2))
        else:
            poll_once()
            response = build_response()
            print(json.dumps(response, indent=2))
            if response["error"]:
                sys.exit(1)
        return
    threading.Thread(target=poll_loop, daemon=True).start()
    print(f"Serving http://0.0.0.0:{PORT}/usage (LAN clients only, poll every {POLL_SECONDS}s). Ctrl+C to stop.")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
