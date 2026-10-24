"""Fill Wi-Fi and relay settings from .env into a gitignored copy of the M5 script."""
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
TEMPLATE_PATH = PROJECT_DIR / (sys.argv[1] if len(sys.argv) > 1 else "m5_usage_single.py")
OUTPUT_PATH = PROJECT_DIR / (sys.argv[2] if len(sys.argv) > 2 else "m5_usage_flash.py")
ENV_PATH = PROJECT_DIR / ".env"
SUBSTITUTED_KEYS = ("WIFI_SSID", "WIFI_PASSWORD", "HOTSPOT_SSID", "HOTSPOT_PASSWORD", "WORKER_URL", "READ_SECRET")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    env_values = read_env(ENV_PATH)
    script_text = TEMPLATE_PATH.read_text()
    keys_in_template = [key for key in SUBSTITUTED_KEYS if re.search(rf'^{key} = ".*"$', script_text, re.MULTILINE)]
    missing_keys = [key for key in keys_in_template if not env_values.get(key)]
    if missing_keys:
        print("Missing in .env:", ", ".join(missing_keys))
        return 1

    for key in keys_in_template:
        escaped_value = env_values[key].replace("\\", "\\\\").replace('"', '\\"')
        script_text, replacement_count = re.subn(
            rf'^{key} = ".*"$',
            lambda _match, value=escaped_value, name=key: f'{name} = "{value}"',
            script_text,
            flags=re.MULTILINE,
        )
        if replacement_count != 1:
            print(f"Could not find {key} line in template")
            return 1

    OUTPUT_PATH.write_text(script_text)
    print("Wrote", OUTPUT_PATH.name, "(contains your Wi-Fi password, do not share)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
