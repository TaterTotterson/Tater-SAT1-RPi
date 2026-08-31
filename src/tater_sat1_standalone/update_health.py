from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.request import urlopen

from .update_installer import Layout, _service_names, _systemctl, restore_backup


def _service_active(name: str) -> bool:
    if os.getenv("TATER_SAT1_UPDATE_NO_SYSTEMD") == "1":
        return True
    completed = subprocess.run(
        ["systemctl", "is-active", "--quiet", name],
        check=False,
    )
    return completed.returncode == 0


def _standalone_health() -> bool:
    if os.getenv("TATER_SAT1_UPDATE_SKIP_HTTP_HEALTH") == "1":
        return True
    try:
        with urlopen("http://127.0.0.1:8501/api/health", timeout=5) as response:
            return 200 <= int(response.status) < 300
    except Exception:  # pylint: disable=broad-except
        return False


def appliance_healthy(layout: Layout, marker: dict[str, object]) -> bool:
    flavor = str(marker.get("flavor") or "")
    expected_version = str(marker.get("version") or "")
    try:
        actual_version = layout.version.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not expected_version or actual_version != expected_version:
        return False
    if any(not _service_active(service) for service in _service_names(flavor)):
        return False
    return flavor != "standalone" or _standalone_health()


def run_health_check(layout: Layout) -> dict[str, object]:
    if not layout.health_marker.is_file():
        return {"ok": True, "status": "not_pending"}
    marker = json.loads(layout.health_marker.read_text(encoding="utf-8"))
    flavor = str(marker.get("flavor") or "")
    if flavor not in {"standalone", "satellite"}:
        raise ValueError("OTA health marker flavor is invalid")

    initial_wait = max(0, int(os.getenv("TATER_SAT1_UPDATE_HEALTH_WAIT_SECONDS", "20")))
    attempts = max(1, int(os.getenv("TATER_SAT1_UPDATE_HEALTH_ATTEMPTS", "6")))
    interval = max(0, int(os.getenv("TATER_SAT1_UPDATE_HEALTH_INTERVAL_SECONDS", "10")))
    if initial_wait:
        time.sleep(initial_wait)
    healthy = False
    for attempt in range(attempts):
        if appliance_healthy(layout, marker):
            healthy = True
            break
        if attempt + 1 < attempts and interval:
            time.sleep(interval)

    layout.update_dir.mkdir(parents=True, exist_ok=True)
    if healthy:
        result = {
            "ok": True,
            "status": "accepted",
            "flavor": flavor,
            "version": str(marker.get("version") or ""),
            "previous_version": str(marker.get("previous_version") or ""),
            "timestamp": time.time(),
        }
        (layout.update_dir / "last-success.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        layout.health_marker.unlink(missing_ok=True)
        shutil.rmtree(layout.rollback_dir, ignore_errors=True)
        if flavor == "standalone":
            # Clear state left by the retired app-only updater only after the
            # signed OTA passes health, preserving rollback until then.
            shutil.rmtree(layout.tater_app_release_dir, ignore_errors=True)
            shutil.rmtree(layout.tater_app_update_dir, ignore_errors=True)
            _systemctl("disable", "tater-sat1-app-update.timer", check=False)
            _systemctl("stop", "tater-sat1-app-update.service", check=False)
        return result

    restored = restore_backup(layout)
    result = {
        "ok": False,
        "status": "rolled_back" if restored else "rollback_unavailable",
        "flavor": flavor,
        "version": str(marker.get("version") or ""),
        "previous_version": str(marker.get("previous_version") or ""),
        "timestamp": time.time(),
    }
    (layout.update_dir / "last-failure.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _systemctl("start", *_service_names(flavor), check=False)
    if restored and os.getenv("TATER_SAT1_UPDATE_NO_REBOOT") != "1":
        subprocess.run(["systemctl", "reboot"], check=True)
    return result


def main() -> int:
    layout = Layout(Path(os.getenv("TATER_SAT1_UPDATE_ROOT", "/")))
    result = run_health_check(layout)
    print(json.dumps(result, sort_keys=True))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
