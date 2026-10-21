#!/usr/bin/env python3
"""Read-only probe of a Daikin BRP069A78 (Altherma WLAN cartridge) for local APIs.

Usage: python3 tools/probe_brp069a78.py 192.168.10.7 [192.168.10.3 ...]

Only GET requests and UDP discovery queries are sent; nothing is written to the unit.
Identifiers (MAC, serial, cloud ids) are redacted in the output.
"""

from __future__ import annotations

import json
import re
import socket
import sys
import urllib.error
import urllib.request

HTTP_PATHS = [
    "/",
    "/common/basic_info",
    "/aircon/get_control_info",
    "/aircon/get_sensor_info",
    "/mca",
    "/config/adapter/info",
    "/config/firmware/info",
    "/config/wlan/info",
    "/config/adapter/product_info",
]
TCP_PORTS = [80, 443, 8080, 8443, 1883, 8883, 5683, 30050]
UDP_PATHS = ["/common/basic_info", "/aircon/get_control_info", "/aircon/get_sensor_info"]
DSIOT_READ = {
    "requests": [
        {"op": 2, "to": "/dsiot/edge/adr_0100.dgc_status?filter=pv,pt,md"},
        {"op": 2, "to": "/dsiot/edge.adp_i"},
    ]
}

REDACT_KEYS = {"udid", "gatewayDeviceId", "macAddress", "serial_number", "device_id"}
MAC_RE = re.compile(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", re.IGNORECASE)


def redact(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        return MAC_RE.sub("<mac>", text)
    if isinstance(data, dict):
        data = {k: ("<redacted>" if k in REDACT_KEYS else v) for k, v in data.items()}
    return json.dumps(data)


def http(ip: str, path: str, body: dict | None = None) -> str:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://{ip}{path}", data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return f"{resp.status} {redact(resp.read(600).decode(errors='replace'))}"
    except urllib.error.HTTPError as err:
        return f"{err.code} {err.read(100).decode(errors='replace').strip()}"
    except OSError as err:
        return f"error: {err}"


def tcp_open(ip: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(2)
        return sock.connect_ex((ip, port)) == 0


def udp(ip: str, path: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        sock.sendto(f"DAIKIN_UDP{path}".encode(), (ip, 30050))
        try:
            return redact(sock.recvfrom(2048)[0].decode(errors="replace"))
        except OSError:
            return "(no reply)"


def probe(ip: str) -> None:
    print(f"== {ip}")
    open_ports = [p for p in TCP_PORTS if tcp_open(ip, p)]
    print(f"open tcp ports: {open_ports}")
    for path in HTTP_PATHS:
        print(f"GET  {path:32} {http(ip, path)}")
    print(f"POST {'/dsiot/multireq':32} {http(ip, '/dsiot/multireq', DSIOT_READ)}")
    for path in UDP_PATHS:
        print(f"UDP  {path:32} {udp(ip, path)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for host in sys.argv[1:]:
        probe(host)
