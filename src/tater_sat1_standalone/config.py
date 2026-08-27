from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("/etc/tater-sat1-standalone/config.toml")
VALID_FLAVORS = {"standalone", "satellite"}


def _path(value: Any, default: str) -> Path:
    text = str(value or default).strip()
    if not text:
        raise ValueError("configured path must not be empty")
    return Path(text).expanduser()


def _port(value: Any, default: int) -> int:
    port = int(value if value is not None else default)
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be between 1 and 65535, got {port}")
    return port


def _integer(value: Any, default: int, *, label: str, minimum: int, maximum: int) -> int:
    number = int(value if value is not None else default)
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}, got {number}")
    return number


def _ratio(value: Any, default: float, *, label: str) -> float:
    number = float(value if value is not None else default)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1, got {number}")
    return number


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("extra_args must be an array of strings")
    return tuple(value)


def _flavor(value: Any) -> str:
    flavor = str(value or "standalone").strip().lower()
    if flavor not in VALID_FLAVORS:
        raise ValueError(f"runtime flavor must be one of {sorted(VALID_FLAVORS)}, got {flavor!r}")
    return flavor


@dataclass(frozen=True)
class RuntimeConfig:
    flavor: str = "standalone"
    state_dir: Path = Path("/var/lib/tater-sat1-standalone")
    tater_app_dir: Path = Path("/opt/tater/app")
    tater_python: Path = Path("/opt/tater/venv/bin/python")
    satellite_executable: Path = Path("/opt/tater-sat1/venv/bin/tater-sat1-voice")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> RuntimeConfig:
        return cls(
            flavor=_flavor(values.get("flavor")),
            state_dir=_path(values.get("state_dir"), str(cls.state_dir)),
            tater_app_dir=_path(values.get("tater_app_dir"), str(cls.tater_app_dir)),
            tater_python=_path(values.get("tater_python"), str(cls.tater_python)),
            satellite_executable=_path(values.get("satellite_executable"), str(cls.satellite_executable)),
        )

    @property
    def token_path(self) -> Path:
        return self.state_dir / "native-satellite-token"

    @property
    def server_url_path(self) -> Path:
        return self.state_dir / "tater-server-url"

    @property
    def first_boot_marker_path(self) -> Path:
        return self.state_dir / "first-boot-complete"

    @property
    def tater_runtime_dir(self) -> Path:
        return self.state_dir / "tater-runtime"

    @property
    def agent_lab_dir(self) -> Path:
        return self.state_dir / "agent-lab"

    @property
    def redis_config_path(self) -> Path:
        return self.state_dir / "redis-connection.json"

    @property
    def satellite_state_dir(self) -> Path:
        return self.state_dir / "satellite-runtime"


@dataclass(frozen=True)
class TaterConfig:
    host: str = "0.0.0.0"
    port: int = 8501
    url: str = ""
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> TaterConfig:
        return cls(
            host=str(values.get("host") or cls.host),
            port=_port(values.get("port"), cls.port),
            url=str(values.get("url") or "").strip(),
            extra_args=_string_tuple(values.get("extra_args")),
        )


@dataclass(frozen=True)
class SatelliteConfig:
    name: str = "auto"
    device_id: str = "auto"
    board: str = "satellite1_rpi"
    room: str = ""
    audio_input_device: str = "default"
    audio_output_device: str = "default"
    pulse_server: str = "unix:/run/tater-sat1-audio/pulse/native"
    wake_model: str = "hey_tater"
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> SatelliteConfig:
        return cls(
            name=str(values.get("name") or cls.name),
            device_id=str(values.get("device_id") or cls.device_id),
            board=str(values.get("board") or cls.board),
            room=str(values.get("room") or ""),
            audio_input_device=str(values.get("audio_input_device") or cls.audio_input_device),
            audio_output_device=str(values.get("audio_output_device") or cls.audio_output_device),
            pulse_server=str(values["pulse_server"]) if "pulse_server" in values else cls.pulse_server,
            wake_model=str(values.get("wake_model") or cls.wake_model),
            extra_args=_string_tuple(values.get("extra_args")),
        )


@dataclass(frozen=True)
class LedConfig:
    enabled: bool = True
    pixel_count: int = 24
    gpio_pin: int = 12
    frequency_hz: int = 800_000
    dma_channel: int = 10
    channel: int = 0
    invert: bool = False
    brightness: float = 0.66
    red: float = 0.094
    green: float = 0.733
    blue: float = 0.949
    peripheral_host: str = "127.0.0.1"
    peripheral_port: int = 6055

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> LedConfig:
        enabled = values.get("enabled", cls.enabled)
        invert = values.get("invert", cls.invert)
        if not isinstance(enabled, bool):
            raise ValueError("leds.enabled must be a boolean")
        if not isinstance(invert, bool):
            raise ValueError("leds.invert must be a boolean")
        pixel_count = _integer(
            values.get("pixel_count"), cls.pixel_count, label="leds.pixel_count", minimum=2, maximum=1024
        )
        if pixel_count % 2:
            raise ValueError("leds.pixel_count must be even so opposing SAT1 animations remain symmetric")
        host = str(values.get("peripheral_host") or cls.peripheral_host).strip()
        if not host or any(character.isspace() for character in host):
            raise ValueError("leds.peripheral_host must be a non-empty host without whitespace")
        return cls(
            enabled=enabled,
            pixel_count=pixel_count,
            gpio_pin=_integer(values.get("gpio_pin"), cls.gpio_pin, label="leds.gpio_pin", minimum=0, maximum=53),
            frequency_hz=_integer(
                values.get("frequency_hz"),
                cls.frequency_hz,
                label="leds.frequency_hz",
                minimum=100_000,
                maximum=2_000_000,
            ),
            dma_channel=_integer(
                values.get("dma_channel"), cls.dma_channel, label="leds.dma_channel", minimum=0, maximum=15
            ),
            channel=_integer(values.get("channel"), cls.channel, label="leds.channel", minimum=0, maximum=1),
            invert=invert,
            brightness=_ratio(values.get("brightness"), cls.brightness, label="leds.brightness"),
            red=_ratio(values.get("red"), cls.red, label="leds.red"),
            green=_ratio(values.get("green"), cls.green, label="leds.green"),
            blue=_ratio(values.get("blue"), cls.blue, label="leds.blue"),
            peripheral_host=host,
            peripheral_port=_port(values.get("peripheral_port"), cls.peripheral_port),
        )


@dataclass(frozen=True)
class StandaloneConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    tater: TaterConfig = field(default_factory=TaterConfig)
    satellite: SatelliteConfig = field(default_factory=SatelliteConfig)
    leds: LedConfig = field(default_factory=LedConfig)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> StandaloneConfig:
        runtime = RuntimeConfig.from_mapping(_section(values, "runtime"))
        satellite_values = dict(_section(values, "satellite"))
        if not str(satellite_values.get("board") or "").strip():
            satellite_values["board"] = f"satellite1_rpi_{runtime.flavor}"
        return cls(
            runtime=runtime,
            tater=TaterConfig.from_mapping(_section(values, "tater")),
            satellite=SatelliteConfig.from_mapping(satellite_values),
            leds=LedConfig.from_mapping(_section(values, "leds")),
        )


def _section(values: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = values.get(name, {})
    if not isinstance(section, Mapping):
        raise ValueError(f"[{name}] must be a TOML table")
    return section


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> StandaloneConfig:
    config_path = Path(path).expanduser()
    with config_path.open("rb") as handle:
        values = tomllib.load(handle)
    return StandaloneConfig.from_mapping(values)
