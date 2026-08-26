from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import sys
import tomllib
from typing import Mapping

from .commands import RuntimePlan, build_satellite_plan, build_tater_plan
from .config import DEFAULT_CONFIG_PATH, StandaloneConfig, load_config
from .doctor import inspect_host
from .runtime import prepare_runtime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tater + Satellite1 standalone appliance launcher")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("init", help="create private runtime directories and the shared satellite token")
    subparsers.add_parser("doctor", help="check host resources and installed runtime paths")
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

    token = prepare_runtime(config.runtime)
    if args.action == "init":
        print(f"runtime initialized at {config.runtime.state_dir}")
        return

    plan = _plan(config, args.component, token)
    environment = os.environ.copy()
    environment.update(plan.environment)
    if plan.working_directory is not None:
        os.chdir(plan.working_directory)
    os.execvpe(plan.command[0], plan.command, environment)
if __name__ == "__main__":
    main()
