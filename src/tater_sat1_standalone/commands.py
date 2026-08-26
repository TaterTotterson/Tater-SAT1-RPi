from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .config import StandaloneConfig
from .identity import device_id, display_name
from .provisioning import effective_server_url


@dataclass(frozen=True)
class RuntimePlan:
    command: tuple[str, ...]
    environment: Mapping[str, str]
    working_directory: Path | None = None


def build_tater_plan(config: StandaloneConfig, token: str) -> RuntimePlan:
    if config.runtime.flavor != "standalone":
        raise ValueError("the Tater server is not installed in the satellite image flavor")
    runtime = config.runtime
    tater = config.tater
    environment = {
        "HTMLUI_HOST": tater.host,
        "HTMLUI_PORT": str(tater.port),
        "MALLOC_ARENA_MAX": "2",
        "PYTHONPATH": str(runtime.tater_app_dir),
        "TATER_AGENT_ROOT": str(runtime.agent_lab_dir),
        "TATER_LOAD_PROFILE_ENV": "0",
        "TATER_NATIVE_SATELLITE_TOKEN": token,
        "TATER_REDIS_CONFIG_PATH": str(runtime.redis_config_path),
        "TATER_REMOTE_ONLY": "1",
        "TATER_RUNTIME_BACKGROUND_WORKERS": "1",
        "TATER_RUNTIME_DASHBOARD_WORKERS": "1",
        "TATER_RUNTIME_DIR": str(runtime.tater_runtime_dir),
        "TATER_RUNTIME_SPEECH_WORKERS": "1",
        "TATER_RUNTIME_STT_WORKERS": "1",
        "TATER_RUNTIME_TTS_WORKERS": "1",
        "TATER_RUNTIME_WAKE_WORKERS": "1",
        "TATER_SETUP_PROFILE": "edge",
        "TATER_SETUP_REQUIRE_LOCAL_LLM": "0",
        "TATER_SPEECH_ACCELERATION": "cpu",
    }
    command = (
        str(runtime.tater_python),
        "-m",
        "uvicorn",
        "tateros_app:app",
        "--host",
        tater.host,
        "--port",
        str(tater.port),
        "--no-access-log",
        *tater.extra_args,
    )
    return RuntimePlan(command=command, environment=environment, working_directory=runtime.tater_app_dir)


def build_satellite_plan(config: StandaloneConfig) -> RuntimePlan:
    runtime = config.runtime
    satellite = config.satellite
    command = [
        str(runtime.satellite_executable),
        "--name",
        display_name(config),
        "--audio-input-device",
        satellite.audio_input_device,
        "--audio-output-device",
        satellite.audio_output_device,
        "--wake-model",
        satellite.wake_model,
        "--preferences-file",
        str(runtime.satellite_state_dir / "preferences.json"),
        "--download-dir",
        str(runtime.satellite_state_dir / "models"),
        "--tater-url",
        effective_server_url(config),
        "--tater-token-file",
        str(runtime.token_path),
        "--tater-device-id",
        device_id(config),
        "--tater-board",
        satellite.board,
    ]
    if satellite.room:
        command.extend(("--tater-room", satellite.room))
    command.extend(satellite.extra_args)
    environment = {}
    if satellite.pulse_server:
        environment["PULSE_SERVER"] = satellite.pulse_server
    return RuntimePlan(
        command=tuple(command),
        environment=environment,
        working_directory=runtime.satellite_state_dir,
    )
