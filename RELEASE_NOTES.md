# PLC-Assist 0.2.0

Release date: 2026-07-27

## Highlights

- GUI and CLI Service Manager for on-demand Ollama, Codex, llama.cpp,
  Streamlit, and OpenPLC lifecycle management.
- Windows `PLC-Assist-Service-Manager.exe` and
  `PLC-Assist-Service-CLI.exe`.
- Modbus holding-register observation for position, velocity, targets,
  ErrorID, and AxisState.
- Runtime coverage for negative JOG/negative limit, repeated start/stop,
  direction switching, E-Stop, Reset, and absolute-position completion.
- Non-loopback PLC targets are denied by default and require an explicit
  real-hardware opt-in.

## Verification

- 34 pytest tests.
- OpenPLC/Modbus:
  - negative JOG suite: 5/5;
  - repeated commands and direction switch suite: 6/6;
  - absolute-position suite: 5/5.
- Release CLI executable health check passed.
- Release archive excludes models, llama.cpp binaries, logs, and local
  credentials.

Real-machine servo behavior and safety-chain validation remain site-specific
commissioning responsibilities; the included virtual-axis tests do not replace
them.
