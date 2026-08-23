# PLC-Assist Repository 與交付資料清單

## 1. GitHub 應追蹤的資料

| 類別 | 檔案／目錄 | 用途 |
|---|---|---|
| 應用入口 | `app.py`、`app_codex.py`、`app_llamacpp.py` | 三種 AI 後端的 Streamlit UI |
| AI Provider | `codex_provider.py`、`local_provider.py` | Codex CLI 與 llama.cpp 串接 |
| 契約與驗證 | `prompt_contract.py`、`motion_contract.py`、`validator.py` | Prompt、運動需求與靜態規則驗證 |
| 編譯與執行 | `compiler.py`、`simulator.py`、`scenarios.py`、`st_common.py` | matiec、OpenPLC 與 Modbus 測試 |
| Digital Twin | `twin_app.py`、`twin_client.py`、`twin_deployment.py`、`twin_settings.py` | Twin 顯示、控制、設定及部署身分 |
| 控制模型 | `motion_stubs/` | AXIS_REF 與 MC_* 模擬 Function Blocks |
| 管理工具 | `service_manager.py`、`setup/` | 服務生命週期、安裝、打包與 Smoke Test |
| 測試 | `tests/` | pytest 回歸測試與 ST fixtures |
| 依賴／設定 | `requirements*.txt`、`hardware_config.example.env` | 可重建依賴與安全設定範例 |
| 文件 | `README.md`、`DEMO_REPRODUCTION.md`、`DEPLOYMENT.md`、`PLC-Assist_目前架構圖.md`、`RELEASE_NOTES.md` | 使用、架構、部署與版本資訊 |

## 2. 刻意不進 GitHub 的資料

| 路徑／類型 | 原因 | 重建方式 |
|---|---|---|
| `venv/` | 平台相依、可由依賴檔重建 | `python -m venv` + `pip install` |
| `models/` | 模型檔過大且可能有獨立授權 | 由模型發布來源下載 |
| `tools/` | 第三方執行檔與大型工具 | 由官方發行版取得 |
| `release/` | 可由來源重建的輸出 | 執行 `setup/build_release.ps1` |
| `.runlogs/`、`.tmp/`、快取 | 機器專屬暫存 | 執行時自動產生 |
| `.env*`、`hardware_config.env` | 可能包含帳密或機器設定 | 從 example 檔自行建立 |
| OpenPLC/MSYS2 安裝目錄 | 體積大且位於 Repository 外 | 執行工具鏈安裝腳本 |

## 3. 可重現性邊界

GitHub 可以重建程式碼、Python 依賴、OpenPLC 工具鏈及測試流程，但無法保證不同日期下載的外部模型、Codex 模型或 OpenPLC upstream commit 產生完全相同的位元輸出。

若需要長期封存一場特定展示，應另外記錄：

- Git commit SHA。
- Python 與 Windows 版本。
- Ollama／llama.cpp／OpenPLC 版本。
- 模型名稱、下載來源、授權及 SHA-256。
- 發行 ZIP 的 SHA-256。
- pytest 與 Smoke Test 結果。

不要把 API key、Codex 登入資訊、真實 PLC 密碼或現場網路設定放進封存檔。

## 4. 發行包驗收

`setup/build_release.ps1` 產出的 ZIP 應包含：

- 所有執行所需 Python 模組，包括 `prompt_contract.py`。
- `motion_stubs/`、`setup/` 與 `tests/`。
- 重建、部署、架構與版本文件。
- Python requirements 與安全設定範例。
- Service Manager GUI/CLI。
- `SHA256SUMS.txt`。

解壓後應先核對雜湊，再依 [DEMO_REPRODUCTION.md](DEMO_REPRODUCTION.md) 執行測試與展示。
