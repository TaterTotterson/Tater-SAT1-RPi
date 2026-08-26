from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tomllib
from typing import Mapping

from .commands import RuntimePlan, build_satellite_plan, build_tater_plan
from .config import DEFAULT_CONFIG_PATH, StandaloneConfig, load_config
from .doctor import inspect_host
from .identity import device_id, display_name, hostname
from .provisioning import provision_pairing
from .runtime import mark_first_boot, prepare_runtime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tater Satellite1 appliance launcher")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("init", help="create private runtime directories and the shared satellite token")
    subparsers.add_parser("firstboot", help="initialize per-device state and mark first boot complete")
    subparsers.add_parser("doctor", help="check host resources and installed runtime paths")
    identity_parser = subparsers.add_parser("identity", help="print the resolved per-device identity")
    identity_parser.add_argument("--hostname", action="store_true", help="print only the hostname")
    pair_parser = subparsers.add_parser("pair", help="pair a satellite-only appliance with its Tater server")
    pair_parser.add_argument("code", help="short pairing code shown by Tater")
    pair_parser.add_argument("--url", default="", help="Tater base URL; defaults to the configured URL")
    pair_parser.add_argument("--no-restart", action="store_true", help="write pairing state without restarting the service")
    for action in ("plan", "run"):
        child = subparsers.add_parser(action)
        child.add_argument("component", choices=("tater", "satellite"))
        if action == "plan":
            child.add_argument("--json", action="store_true")
    return parser


def _plan(config: StandaloneConfig, component: str, token: str) -> RuntimePlan:
    if component == "tater":
        return build_tater_plan(config, token)
    return build_satellite_plan(config)


def _redacted_environment(environment: Mapping[str, str]) -> dict[str, str]:
    values = dict(environment)
    for key in tuple(values):
        if "TOKEN" in key or "KEY" in key or "SECRET" in key:
            values[key] = "<redacted>"
    return values


def _show_plan(plan: RuntimePlan, as_json: bool) -> None:
    payload = {
        "command": list(plan.command),
        "environment": _redacted_environment(plan.environment),
        "working_directory": str(plan.working_directory) if plan.working_directory else None,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"working directory: {payload['working_directory'] or '<inherited>'}")
    print("command:", shlex.join(plan.command))
    print("environment:")
    for key, value in sorted(payload["environment"].items()):
        print(f"  {key}={value}")


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if args.action == "plan":
        plan = _plan(config, args.component, "<not-created>")
        _show_plan(plan, args.json)
        return
    if args.action == "doctor":
        checks = inspect_host(config)
        for check in checks:
            print(f"[{check.level.upper():5}] {check.label}: {check.detail}")
        raise SystemExit(1 if any(check.level == "error" for check in checks) else 0)

    if args.action == "identity":
        if args.hostname:
            print(hostname(config))
        else:
            print(json.dumps({"device_id": device_id(config), "hostname": hostname(config), "name": display_name(config)}))
        return

    if args.action == "pair":
        try:
            url = provision_pairing(config, args.code, args.url)
        except ValueError as exc:
            print(f"pairing error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if not args.no_restart:
            if os.geteuid() != 0:
                print("pairing requires sudo so the satellite service can be restarted", file=sys.stderr)
                raise SystemExit(2)
            subprocess.run(["systemctl", "restart", "tater-sat1-satellite.service"], check=True)
        print(f"pairing configured for {url}; the durable device token will replace the one-time code after connection")
        return

    token = prepare_runtime(config.runtime)
    if args.action == "init":
        print(f"runtime initialized at {config.runtime.state_dir}")
        return
    if args.action == "firstboot":
        mark_first_boot(config.runtime)
        print(f"first boot initialized for {device_id(config)}")
        return

    plan = _plan(config, args.component, token)
    environment = os.environ.copy()
    environment.update(plan.environment)
    if plan.working_directory is not None:
        os.chdir(plan.working_directory)
    os.execvpe(plan.command[0], plan.command, environment)
if __name__ == "__main__":
    main()
