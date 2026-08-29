from __future__ import annotations

import argparse
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable, Mapping, Sequence
from urllib.parse import parse_qs

from .config import DEFAULT_CONFIG_PATH, StandaloneConfig, load_config
from .identity import display_name, hostname
from .provisioning import provision_pairing, validate_server_url


MAX_REQUEST_BYTES = 8192
NETWORK_CONNECTION_NAME = "tater-sat1-wifi"
CAPTIVE_PATHS = {
    "/",
    "/canonical.html",
    "/connecttest.txt",
    "/generate_204",
    "/gen_204",
    "/hotspot-detect.html",
    "/ncsi.txt",
    "/redirect",
    "/success.txt",
}

Runner = Callable[..., subprocess.CompletedProcess[object]]


def _reject_controls(value: str, label: str) -> None:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} contains unsupported control characters")


def validate_fields(config: StandaloneConfig, fields: Mapping[str, str]) -> dict[str, str]:
    values = {
        "ssid": fields.get("ssid", "").strip(),
        "wifi_password": fields.get("wifi_password", ""),
        "tater_server": fields.get("tater_server", "").strip(),
        "pairing_code": fields.get("pairing_code", "").strip(),
    }
    for key, label in (
        ("ssid", "Wi-Fi network name"),
        ("wifi_password", "Wi-Fi password"),
        ("tater_server", "Tater server"),
        ("pairing_code", "Pairing code"),
    ):
        _reject_controls(values[key], label)

    ssid_length = len(values["ssid"].encode("utf-8"))
    if not 1 <= ssid_length <= 32:
        raise ValueError("Wi-Fi network name must be 1 to 32 bytes")

    password_length = len(values["wifi_password"].encode("utf-8"))
    if password_length and not 8 <= password_length <= 63:
        raise ValueError("Wi-Fi password must be blank or 8 to 63 bytes")

    if config.runtime.flavor == "satellite":
        values["tater_server"] = validate_server_url(values["tater_server"])
        if not values["pairing_code"] or any(character.isspace() for character in values["pairing_code"]):
            raise ValueError("Pairing code must be a non-empty value without whitespace")
        if len(values["pairing_code"].encode("utf-8")) > 512:
            raise ValueError("Pairing code must be at most 512 bytes")
    else:
        values["tater_server"] = ""
        values["pairing_code"] = ""
    return values


def networkmanager_commands(ssid: str, password: str) -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = [
        ("nmcli", "connection", "delete", NETWORK_CONNECTION_NAME),
        (
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            "wlan0",
            "con-name",
            NETWORK_CONNECTION_NAME,
            "ssid",
            ssid,
        ),
        (
            "nmcli",
            "connection",
            "modify",
            NETWORK_CONNECTION_NAME,
            "connection.autoconnect",
            "yes",
            "connection.autoconnect-priority",
            "100",
            "802-11-wireless.powersave",
            "2",
            "ipv4.method",
            "auto",
            "ipv6.method",
            "auto",
        ),
    ]
    if password:
        commands.append(
            (
                "nmcli",
                "connection",
                "modify",
                NETWORK_CONNECTION_NAME,
                "802-11-wireless-security.key-mgmt",
                "wpa-psk",
                "802-11-wireless-security.psk",
                password,
            )
        )
    return tuple(commands)


def save_configuration(
    config: StandaloneConfig,
    fields: Mapping[str, str],
    *,
    runner: Runner = subprocess.run,
) -> dict[str, str]:
    values = validate_fields(config, fields)
    commands = networkmanager_commands(values["ssid"], values["wifi_password"])
    runner(commands[0], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for command in commands[1:]:
        runner(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if config.runtime.flavor == "satellite":
        provision_pairing(config, values["pairing_code"], values["tater_server"])
    os.sync()
    return values


def build_page(config: StandaloneConfig) -> str:
    name = html.escape(display_name(config))
    resolved_hostname = html.escape(hostname(config))
    if config.runtime.flavor == "satellite":
        tater_fields = """
    <label>Main Tater address
      <input name="tater_server" maxlength="255" required
        value="http://tater.local:8501" autocapitalize="none" spellcheck="false">
      <small>The address of the Tater that will manage this satellite.</small>
    </label>
    <label>Pairing code
      <input name="pairing_code" type="password" maxlength="512" required>
      <small>Create this in Tater under Satellites &rarr; Add Satellite.</small>
    </label>"""
        next_step = "After restarting, this SAT1 will join Wi-Fi and connect to your main Tater."
    else:
        tater_fields = ""
        next_step = f"After restarting, open http://{resolved_hostname}.local:8501 to finish Tater setup."

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Tater SAT1 Setup</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
    body {{ margin: 0; background: radial-gradient(circle at 50% -10%, #3b2416, #0b0f10 44%); color: #f4f1e9; }}
    main {{ max-width: 34rem; margin: auto; padding: 2rem 1.2rem 3rem; }}
    h1 {{ margin-bottom: .25rem; color: #ffc07f; }}
    p {{ color: #cbd7cb; line-height: 1.45; }}
    form {{ display: grid; gap: 1rem; margin-top: 1.5rem; }}
    label {{ display: grid; gap: .35rem; font-weight: 650; }}
    small {{ color: #9cab9d; font-weight: 400; }}
    input {{ box-sizing: border-box; width: 100%; padding: .8rem; border: 1px solid #38464b;
      border-radius: .55rem; background: #0f1416; color: white; font: inherit; }}
    input:focus {{ outline: 2px solid #ffc07f; border-color: transparent; }}
    button {{ padding: .9rem; border: 0; border-radius: .55rem;
      background: linear-gradient(135deg, #ff8a2a, #ffc07f);
      color: #1d0e03; font: inherit; font-weight: 800; cursor: pointer; }}
    .notice {{ padding: .85rem; border-left: .25rem solid #ff8a2a; background: #192023; }}
  </style>
</head>
<body><main>
  <small>TATER NATIVE</small><h1>{name}</h1>
  <p>Connect this SAT1 to Wi-Fi. Everything entered here stays on this device;
     the setup hotspot has no internet route.</p>
  <p class="notice">The open setup network is available only while this SAT1
     is waiting for a working Wi-Fi connection.</p>
  <form method="post" action="/save" autocomplete="off">
    <label>Wi-Fi network name
      <input name="ssid" maxlength="32" required autocapitalize="none" spellcheck="false">
    </label>
    <label>Wi-Fi password
      <input name="wifi_password" type="password" maxlength="63">
      <small>Leave blank only for an open Wi-Fi network.</small>
    </label>{tater_fields}
    <button type="submit">Save and restart</button>
  </form>
  <p><small>{html.escape(next_step)}</small></p>
</main></body></html>"""


def _reboot() -> None:
    time.sleep(2)
    subprocess.run(["/bin/sync"], check=False)
    subprocess.run(["/usr/bin/systemctl", "reboot"], check=False)


class ProvisioningHandler(BaseHTTPRequestHandler):
    server_version = "TaterSAT1Setup/1.0"
    config: StandaloneConfig

    def _send_html(self, status: HTTPStatus, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0]
        if path not in CAPTIVE_PATHS:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send_html(HTTPStatus.OK, build_page(self.config))

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.split("?", 1)[0] != "/save":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            raw_fields = parse_qs(
                self.rfile.read(length).decode("utf-8"),
                keep_blank_values=True,
                strict_parsing=True,
            )
            fields = {key: values[-1] for key, values in raw_fields.items()}
            save_configuration(self.config, fields)
        except (UnicodeDecodeError, ValueError, OSError, subprocess.SubprocessError) as error:
            escaped = html.escape(str(error))
            self._send_html(
                HTTPStatus.BAD_REQUEST,
                f"<h1>Setup was not saved</h1><p>{escaped}</p><p><a href='/'>Try again</a></p>",
            )
            return
        self._send_html(
            HTTPStatus.OK,
            "<h1>Setup saved</h1><p>This SAT1 is restarting and will join your Wi-Fi network.</p>",
        )
        threading.Thread(target=_reboot, daemon=True).start()

    def log_message(self, message: str, *args: object) -> None:
        print(f"tater-sat1-provisioning: {self.address_string()} - {message % args}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local captive setup portal for Tater SAT1 images")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--bind", default="192.168.4.1")
    parser.add_argument("--port", type=int, default=80)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    config = load_config(args.config)
    ProvisioningHandler.config = config
    server = ThreadingHTTPServer((args.bind, args.port), ProvisioningHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
