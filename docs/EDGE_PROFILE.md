# Remote-only Tater edge profile

Tater's normal CPU installation is intentionally broad. It installs local
model stacks that are inappropriate for a 512 MB Raspberry Pi Zero 2 W. Tater
now has a separate `edge` setup profile for this appliance.

The edge profile must preserve the full Tater application surface while making
local model providers unavailable in a clean, explicit way.

## Keep

- FastAPI/Uvicorn and the built frontend
- Hydra, Cores, Verbas, portals, integrations, and TaterOS
- Native satellite WebSocket routes
- Redis state and encrypted secrets
- OpenAI-compatible remote LLM support
- OpenAI-compatible remote TTS support
- Remote Wyoming STT/TTS support
- WebRTC VAD in the satellite process
- Local wake-word inference in the satellite process
- FFmpeg and media playback support needed for voice replies and music

## Exclude from the Pi image

- PyTorch and torchaudio
- TensorFlow, DeepFace, OpenCV, SpeechBrain, and face/voice/emotion ID workers
- Faster Whisper, local Parakeet, local Qwen ASR, and Vosk models
- Kokoro, Pocket TTS, Piper, Qwen TTS, and OmniVoice local engines
- Transformers, Accelerate, MLX, and the native llama.cpp build
- Development and firmware build toolchains

The edge profile has an isolated installation/import test and starts the full
Tater application without Torch, TensorFlow, ONNX Runtime, Faster Whisper, or
other local-model packages. The first host measurement was approximately
122 MiB RSS at idle with Redis connected and zero models loaded. A real Pi
measurement remains the performance gate.

## Missing provider work

Tater already supports remote Wyoming STT. A generic OpenAI-compatible STT
backend should be added so the appliance can call `/v1/audio/transcriptions`
directly, matching its existing remote LLM and TTS options.
