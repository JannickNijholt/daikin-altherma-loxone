#!/usr/bin/env python3
"""Turn a raw /v1/gateway-devices dump into a test fixture without identifying data.

Usage: python3 tools/sanitize_fixture.py onecta_devices.raw.json tests/fixtures/altherma_two_units.json
"""

from __future__ import annotations

import json
import sys

REPLACE = {
    "macAddress": "00:00:00:00:00:{n:02x}",
    "serialNumber": "000000{n}",
    "ipAddress": "192.0.2.{n}",
    "ssid": "fixture-{n}",
    "wifiConnectionSSID": "fixture-wifi",
}


def scrub(node, n):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in REPLACE and isinstance(value, dict) and "value" in value:
                value["value"] = REPLACE[key].format(n=n)
            elif key == "firmwareUpdate" and isinstance(value, dict):
                value.get("value", value).pop("id", None)
            else:
                scrub(value, n)
    elif isinstance(node, list):
        for item in node:
            scrub(item, n)


def main(source: str, target: str) -> None:
    devices = json.load(open(source))
    for n, device in enumerate(devices, start=1):
        fake = f"00000000-0000-4000-8000-{n:012d}"
        device["id"] = device["_id"] = fake
        device["embeddedId"] = str(1000 + n)
        scrub(device, n)
    with open(target, "w") as handle:
        json.dump(devices, handle, indent=1)
    text = open(target).read()
    original = json.load(open(source))
    leaks = [d["id"] for d in original if d["id"] in text]
    assert not leaks, f"gateway ids leaked: {leaks}"
    print(f"Wrote {target} ({len(devices)} devices)")


if __name__ == "__main__":
    main(*sys.argv[1:3])
