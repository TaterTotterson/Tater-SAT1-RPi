#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tater_sat1_standalone.tater_source import (  # noqa: E402
    OLD_SETTINGS_BLOCK,
    SAT1_SETTINGS_BLOCK,
    VOICE_PIPELINE,
    prepare,
)

__all__ = ["OLD_SETTINGS_BLOCK", "SAT1_SETTINGS_BLOCK", "VOICE_PIPELINE", "prepare"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare latest Tater for the SAT1 embedded image")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    metadata = prepare(args.source, args.destination, args.revision.strip())
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
