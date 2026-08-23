# PLC-Assist 0.2.3

Release date: 2026-08-23

## Highlights

- 新增從 GitHub clone 到完整本機展示的重建指南。
- 新增 Repository、外部大型產物與交付內容清單。
- 修正發行包漏掉必要 `prompt_contract.py` 的問題。
- 發行包現在包含測試、架構文件與 `SHA256SUMS.txt`，並排除 Python 快取。
- 架構圖同步為目前六道部署閘門。

## Verification

- Full automated suite: 78 passing pytest tests.
- Windows package build completed with PyInstaller 6.16.0 and Python 3.13.7.
- `PLC-Assist-0.2.3-win64.zip`: 64 entries, required files 5/5, cache files 0.
- Archive SHA-256: `4ed7a46301eb0037988f0fb54e17ce760e2aac06515c7fbe201274e872189fdc`.

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
