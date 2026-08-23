# PLC-Assist 本機展示重建指南

本文件的目標是讓新的維護者只使用 GitHub Repository 與公開取得的外部工具，在 Windows 本機重建目前的研究展示成果。

## 1. 可重建範圍

完成本指南後，可展示：

- Ollama、Codex CLI 或 llama.cpp 產生 IEC 61131-3 Structured Text。
- 靜態規則、Motion Contract 與 matiec 編譯驗證。
- OpenPLC Runtime 與 Modbus 情境測試。
- JOG、Absolute Position、E-Stop、限位與 Reset。
- 將已驗證的同一份 ST 部署至 2D Digital Twin。

這是本機研究展示，不是實機安全控制方案。

## 2. GitHub 內含與不含的資料

Repository 已包含原始碼、Motion Function Block stubs、測試、安裝腳本、設定範例與說明文件。

下列項目因容量、授權、機器差異或安全性不放入 Git：

| 項目 | 取得方式 | 預設位置 |
|---|---|---|
| Python 虛擬環境 | 依 `requirements.txt` 重建 | `venv/` |
| OpenPLC、matiec、MSYS2 | 執行工具鏈腳本 | `C:\msys64\home\<USER>\OpenPLC_v3` |
| Ollama 與模型 | 安裝 Ollama 後執行 `ollama pull qwen3.5:9b` | Ollama 自管 |
| Codex CLI 登入狀態 | 安裝 Codex CLI 後執行 `codex login` | 使用者設定區 |
| llama.cpp | 從官方發行版取得 Windows Vulkan build | `tools/llama.cpp/llama-server.exe` |
| Qwen GGUF 模型 | 從模型發布來源取得 | `models/Qwen3.6-27B-Q3_K_M.gguf` |
| 密碼與本機設定 | 參考 `hardware_config.example.env` 自行設定 | 環境變數或未追蹤設定檔 |

只需快速完成展示時，建議使用 Ollama；llama.cpp 27B 是選配的高品質、較高資源模式。

## 3. 系統需求

- Windows 11 x64。
- PowerShell、Git、Python 3.11 或相容版本。
- 可使用 `winget`，或預先安裝 MSYS2。
- Ollama 模式建議至少有足以執行 9B 模型的記憶體。
- llama.cpp 27B 模式需要約 14 GB 模型空間，並建議有充足 RAM／共享 GPU 記憶體。
- 安裝階段需要網路；展示執行可維持在 loopback。

## 4. 從零安裝

```powershell
git clone https://github.com/l125614617-coder/AI_PLC.git
Set-Location AI_PLC
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

安裝 OpenPLC、matiec 與 MSYS2 工具鏈：

```powershell
.\setup\setup_windows_toolchain.ps1
```

腳本完成後，先驗證純 Python 測試：

```powershell
.\venv\Scripts\python.exe -m pytest -q tests
```

## 5. 建議展示路徑：Ollama

安裝 Ollama，然後下載預設模型：

```powershell
ollama pull qwen3.5:9b
.\venv\Scripts\python.exe service_manager.py
```

在 Service Manager 啟動：

1. Ollama API 與 Ollama UI。
2. OpenPLC。
3. 2D Digital Twin。

服務預設網址：

| 服務 | 網址 |
|---|---|
| Ollama UI | `http://127.0.0.1:8501` |
| Codex UI | `http://127.0.0.1:8502` |
| llama.cpp UI | `http://127.0.0.1:8503` |
| Digital Twin | `http://127.0.0.1:8504` |
| OpenPLC Web | `http://127.0.0.1:8081` |
| OpenPLC Modbus | `127.0.0.1:502` |

## 6. 完整展示腳本

1. 開啟 Ollama UI，選擇 `JOG`，設定非零速度與方向。
2. 產生 ST，確認 Local Validation 無阻擋項目。
3. 按 `Compile + Simulate`，確認 Motion Contract、matiec 及 Runtime 情境全部通過。
4. 按「部署至 2D Twin」。
5. 在 Twin 操作啟動、停止、方向、E-Stop、限位與 Reset。
6. 回到生成介面選擇 `Absolute Position`，輸入位置及速度並重新產生。
7. 再次完成 `Compile + Simulate` 並部署。
8. 在 Twin 連續送出不同目標位置，展示不重新生成 ST 的互動定位。

Twin 會以 SHA-256 核對部署程式，確保展示的是本次通過驗證的 ST。

## 7. 端到端驗收

在 OpenPLC 已啟動時執行：

```powershell
.\venv\Scripts\python.exe setup\smoke_twin.py
```

驗收標準：

- pytest 全部通過。
- `setup\smoke_twin.py` 成功。
- 生成介面能產生 ST。
- `Compile + Simulate` 的所有閘門通過。
- Twin 顯示與 Modbus 狀態同步，且未驗證程式不能部署。

## 8. 其他 AI 後端

Codex 模式：

```powershell
codex login
.\venv\Scripts\python.exe -m streamlit run app_codex.py --server.port 8502
```

llama.cpp 模式需先放置 `llama-server.exe` 與 GGUF 模型，再執行：

```powershell
.\setup\start_llamacpp.ps1
.\venv\Scripts\python.exe -m streamlit run app_llamacpp.py --server.port 8503
```

若模型檔名不同，可使用 `-ModelPath` 指定完整路徑。

## 9. 建立可交付 ZIP

```powershell
.\setup\build_release.ps1 -Version 0.2.3
```

輸出位於 `release/`。ZIP 包含原始碼、測試、文件、必要 stubs、設定範例、Service Manager GUI/CLI 和 `SHA256SUMS.txt`，不包含模型、工具鏈、憑證與執行日誌。

## 10. 常見問題

- 修改核心 Python 模組後，要完整停止並重啟 Streamlit process。
- 若 OpenPLC 無法啟動，先確認 502 與 8081 埠沒有被其他程序占用。
- 若只需觀看 UI 和 Local Validation，可暫不安裝 OpenPLC；Runtime 與 Twin 驗收則必須安裝。
- 詳細工具鏈設定與錯誤處理請參考 [DEPLOYMENT.md](DEPLOYMENT.md)。
- 各檔案的用途與外部產物清單請參考 [REPOSITORY_MANIFEST.md](REPOSITORY_MANIFEST.md)。
