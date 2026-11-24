"""Physical setup recovery; independent of voice and server connectivity."""

from __future__ import annotations

import fcntl
import os
import subprocess
from dataclasses import dataclass
from typing import Callable

from .config import StandaloneConfig


@dataclass(frozen=True)
class ResetFeedback:
    clicks: int = 0
    remaining: float | None = None
    resetting: bool = False
    failed: bool = False


class SetupResetGesture:
    """Five short clicks, then hold the sixth press for five seconds."""

    DEBOUNCE = 0.04
    SHORT_CLICK = 0.5
    CLICK_WINDOW = 3.0
    ARM_WINDOW = 5.0
    HOLD = 5.0
    MAX_SAMPLE_GAP = 0.25

    def __init__(self) -> None:
        self._candidate = False
        self._candidate_at = 0.0
        self._stable = False
        self._released = False
        self._pressed_at = 0.0
        self._clicks = 0
        self._deadline = 0.0
        self._holding = False
        self._triggered = False
        self._last_sample: float | None = None

    def cancel(self) -> None:
        # A read failure must not count as continuous physical contact.
        self.__init__()

    def update(self, pressed: bool, now: float) -> tuple[ResetFeedback, bool]:
        if self._last_sample is not None and now - self._last_sample > self.MAX_SAMPLE_GAP:
            self.cancel()
        self._last_sample = now
        if pressed != self._candidate:
            self._candidate = pressed
            self._candidate_at = now
        if not pressed:
            # Even a release shorter than debounce cancels an armed hold.
            self._holding = False
        if self._stable != pressed and now - self._candidate_at >= self.DEBOUNCE:
            self._stable = pressed
            if pressed:
                self._pressed_at = now
                self._holding = self._released and self._clicks == 5 and now <= self._deadline
                self._triggered = False
            else:
                duration = now - self._pressed_at
                if self._released and not self._triggered and self._clicks < 5 and duration <= self.SHORT_CLICK:
                    self._clicks = self._clicks + 1 if now <= self._deadline else 1
                    self._deadline = now + (self.ARM_WINDOW if self._clicks == 5 else self.CLICK_WINDOW)
                else:
                    self._clicks = 0
                self._released = True
                self._holding = False
                self._triggered = False
        elif not self._stable and not pressed:
            self._released = True

        if self._holding and self._stable and pressed:
            remaining = max(0.0, self.HOLD - (now - self._pressed_at))
            if remaining == 0 and not self._triggered:
                self._triggered = True
                self._holding = False
                self._clicks = 0
                return ResetFeedback(resetting=True), True
            return ResetFeedback(clicks=5, remaining=remaining), False
        if self._clicks and now > self._deadline:
            self._clicks = 0
        return ResetFeedback(clicks=self._clicks), False


class ActionButtonInput:
    """The SAT1 action button is active-low on Pi BCM7 (physical pin 26)."""

    def __init__(self) -> None:
        import gpiod
        from gpiod.line import Bias, Direction, Value

        self._pressed_value = Value.INACTIVE
        self._request = gpiod.request_lines(
            "/dev/gpiochip0",
            consumer="tater-sat1-setup-reset",
            config={7: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP)},
        )

    def read_pressed(self) -> bool:
        return self._request.get_value(7) == self._pressed_value

    def close(self) -> None:
        self._request.release()


Runner = Callable[..., subprocess.CompletedProcess[str]]


def reset_setup(config: StandaloneConfig, *, runner: Runner = subprocess.run) -> None:
    """Clear network setup and external pairing, preserving the installed image and app data."""
    state_dir = config.runtime.state_dir
    update_dir = state_dir / "updates"
    update_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (update_dir / "update.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Setup reset is unavailable while an appliance update is running") from exc
        if (update_dir / "health-pending.json").exists() or (update_dir / "pending.sat1-ota").exists():
            raise RuntimeError("Setup reset is unavailable until the appliance update completes")

        def run(*command: str) -> subprocess.CompletedProcess[str]:
            return runner(list(command), check=True, capture_output=True, text=True, timeout=20)

        # Query type separately: names and SSIDs can contain nmcli's delimiter.
        profiles = run("nmcli", "-g", "UUID", "connection", "show").stdout.splitlines()
        wifi_profiles = []
        for uuid in profiles:
            connection_type = run("nmcli", "-g", "connection.type", "connection", "show", "uuid", uuid).stdout.strip()
            if connection_type in {"802-11-wireless", "wifi"}:
                wifi_profiles.append(uuid)

        voice_service = (
            "tater-sat1-satellite.service" if config.runtime.flavor == "satellite" else "tater-sat1-voice.service"
        )
        run("systemctl", "stop", "tater-sat1-provisioning.service", voice_service)
        paths = [
            config.runtime.server_url_path,
            config.runtime.satellite_name_path,
            config.runtime.satellite_room_path,
            config.runtime.satellite_identity_path,
        ]
        # The standalone token connects two local processes, rather than pairing
        # with a remote Tater. Keep it and all embedded Tater settings/data.
        if config.runtime.flavor == "satellite":
            paths.append(config.runtime.token_path)
        for path in paths:
            path.unlink(missing_ok=True)
        os.sync()
        try:
            for uuid in wifi_profiles:
                run("nmcli", "connection", "delete", "uuid", uuid)
        finally:
            # Also recover to setup if a profile deletion fails partway.
            run("systemctl", "--no-block", "restart", "tater-sat1-provisioning.service")
