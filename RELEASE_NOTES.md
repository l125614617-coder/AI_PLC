# PLC-Assist 0.2.2

Release date: 2026-07-29

## Highlights

- Forced UTF-8 decoding for llama.cpp SSE responses whose Content-Type omits
  a charset, preventing mojibake in Traditional Chinese output.
- Reassembled JSON events split across multiple SSE payload lines, including
  splits inside strings, literals, and nested structures.
- Added explicit errors for malformed or prematurely terminated JSON streams.
- Retained all v0.2.1 Service Manager, runtime observation, safety-gate, and
  packaged executable functionality.

## Verification

- UTF-8 Traditional Chinese streaming regression test.
- Split-string, split-literal, malformed, and incomplete JSON stream tests.
- Full automated suite: 40 passing pytest tests.
- Packaged CLI llama.cpp and OpenPLC simulation preflight checks passed.
- OpenPLC/Modbus:
  - negative JOG suite: 5/5;
  - repeated commands and direction switch suite: 6/6;
  - absolute-position suite: 5/5.
- Release archive excludes models, llama.cpp binaries, logs, local notes, and
  credentials.

Real-machine servo behavior and safety-chain validation remain site-specific
commissioning responsibilities; the included virtual-axis tests do not replace
them.
