from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any


VOICE_PIPELINE = Path("tater_voice/voice_pipeline/__init__.py")
OLD_SETTINGS_BLOCK = ('''def _get_bool_setting(name: str, default: bool) -> bool:
    return _as_bool(_voice_settings().get(name), default)


def _get_int_setting(name: str, default: int, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    return _as_int(_voice_settings().get(name), default, minimum=minimum, maximum=maximum)


def _get_float_setting(name: str, default: float, *, minimum: Optional[float] = None, '''
'''maximum: Optional[float] = None) -> float:
    return _as_float(_voice_settings().get(name), default, minimum=minimum, maximum=maximum)
''')
SAT1_SETTINGS_BLOCK = ('''def _voice_setting_or_environment(name: str) -> Any:
    """Use persisted settings first, then allow appliance-only env tuning."""
    settings = _voice_settings()
    if name in settings:
        return settings.get(name)
    return os.getenv(name)


def _get_bool_setting(name: str, default: bool) -> bool:
    return _as_bool(_voice_setting_or_environment(name), default)


def _get_int_setting(name: str, default: int, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    return _as_int(_voice_setting_or_environment(name), default, minimum=minimum, maximum=maximum)


def _get_float_setting(name: str, default: float, *, minimum: Optional[float] = None, '''
'''maximum: Optional[float] = None) -> float:
    return _as_float(_voice_setting_or_environment(name), default, minimum=minimum, maximum=maximum)
''')


def _ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = {".git", ".cache", ".runtime", ".venv", "__pycache__", "agent_lab", "build", "dist"}
    return {
        name
        for name in names
        if name in ignored or name.endswith((".dmg", ".img", ".img.xz"))
    }


def prepare(
    source: Path,
    destination: Path,
    revision: str,
    *,
    release_tag: str = "",
    release_published_at: str = "",
) -> dict[str, Any]:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination or destination == Path(destination.anchor):
        raise ValueError("prepared Tater destination must be a separate non-root directory")
    if not (source / "setup_tater.sh").is_file():
        raise ValueError(f"Tater source is missing setup_tater.sh: {source}")

    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True, ignore=_ignore)

    pipeline = destination / VOICE_PIPELINE
    text = pipeline.read_text(encoding="utf-8")
    overlays: list[str] = []
    if "def _voice_setting_or_environment(" not in text:
        if OLD_SETTINGS_BLOCK not in text:
            raise ValueError(
                "latest Tater changed its voice settings helpers; update the SAT1 overlay before releasing"
            )
        pipeline.write_text(text.replace(OLD_SETTINGS_BLOCK, SAT1_SETTINGS_BLOCK, 1), encoding="utf-8")
        overlays.append("sat1_voice_environment_defaults")

    metadata: dict[str, Any] = {
        "schema": 1,
        "tater_reference_revision": revision,
        "overlays": overlays,
    }
    if release_tag:
        metadata["tater_release_tag"] = release_tag
    if release_published_at:
        metadata["tater_release_published_at"] = release_published_at
    (destination / ".tater-sat1-build.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata
