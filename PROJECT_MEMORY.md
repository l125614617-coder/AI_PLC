# PLC-Assist 專案記憶

最後更新：2026-07-24（Asia/Taipei）

## 目前狀態

- 專案位置：`D:\AI_PLC`
- PLC-Assist Ollama 本地版：`http://localhost:8501`
- PLC-Assist Codex 推理版：`http://localhost:8502`
- Ollama API：`http://localhost:11434`
- OpenPLC webserver：`http://localhost:8081`（8080 被既有的 `ApplicationWebServer` 占用）
- Ollama 模型 `qwen3.5:9b` 已安裝。
- OpenPLC_v3 安裝位置：`C:\msys64\home\Jimmy\OpenPLC_v3`
- `iec2c.exe`、`openplc.exe` 與 OpenPLC Python 環境均已建立。
- OpenPLC blank program 已實際編譯成功。

上述服務於 2026-07-24 已用背景程序啟動；重新開機後需要重新啟動。

## 已完成的修復

### OpenPLC 安裝腳本

`setup/setup_windows_toolchain.ps1` 原本只剩 libmodbus 修補片段，缺少函式定義與完整安裝流程，已重建為可重跑的完整腳本。

腳本現在會：

1. 安裝或更新 MSYS2。
2. 安裝 OpenPLC 建置依賴。
3. clone/build OpenPLC_v3。
4. 處理新版 MSYS2 的 `libmodbus.dll.a`。
5. 優先使用 OpenPLC 自行建置、包含 RPi 擴充 API 的 `/usr/include/modbus` 與 `/usr/lib` 配套版本，避免與 `/mingw64` 的標準版 header 混用。
6. 編譯 blank program 並驗證關鍵產物。
7. 安裝 PLC-Assist 所需的 `pymodbus==2.5.3` 與 `requests`。

安裝輸出的 `ldconfig: command not found` 與 `cat: ethercat: No such file or directory` 在目前 Windows blank driver 流程屬非致命訊息。

### ST 生成與驗證

一次 JOG 生成結果出現以下問題：

- 缺少 `END_PROGRAM`
- 使用未宣告的 `bDone`、`rCurrentPos`
- `rJogVel` 未初始化為 UI 指定的 1500
- `MC_Power` 只在急停分支呼叫且固定傳入 `FALSE`
- Reset 條件方向錯誤
- 直接讀取 `EStopActive`、`LimitPos`、`LimitNeg`

已在 `app.py` 加強 system/user prompt：

- 強制輸出前檢查 `END_PROGRAM` 與變數宣告。
- `MC_Power` 必須每個掃描週期呼叫。
- UI 的速度/位置必須實際寫入程式。
- 禁止生成程式直接讀寫四個外部安全輸入欄位。
- Reset 必須由一般輸入 `bResetReq` 驅動。

已在 `validator.py` 修正：

- 不再把 `Axis1.Busy` 等結構成員誤判為未宣告變數。
- 不再把 FB 呼叫中的 `Enable :=`、`Axis :=` 等具名參數誤判為變數。
- 直接使用 `EStopActive`、`LimitPos`、`LimitNeg`、`HomeSwitch` 時會回報明確錯誤。

Streamlit 已在修改後完整重啟，健康檢查為 HTTP 200。

### 自動測試與端到端驗證

- 已安裝 `requirements-dev.txt` 中鎖定的 `pytest==9.1.1`。
- pytest 完整測試為 `12 passed`，包含新增的 validator 回歸測試。
- 已實測 qwen3.5:9b 產生 JOG 程式：本機驗證通過，matiec 真實編譯通過。
- 已完成 OpenPLC 部署與 Modbus runtime 測試：
  - `enable_responds` 通過。
  - `estop_cuts_power` 通過。
- 修正 `MC_Power`：E-Stop 現在會斷電並設定 `Error`、`ErrorID=1`、`ErrorStop`。
- 因 8080 已被其他程式使用，`simulator.py` 現在支援 `OPENPLC_WEB_BASE`；
  新增 `setup/run_openplc.py` 與 `setup/start_openplc.sh`，可在不修改 OpenPLC 安裝檔的情況下改用 8081。

### Codex 第二版

- 新增 `app_codex.py` 獨立網頁入口，與 Ollama 版可同時運行。
- 新增 `codex_provider.py`，沿用電腦現有的 Codex CLI 登入。
- Codex 工作階段固定使用 `--ephemeral --ignore-user-config --sandbox read-only`，
  不允許生成流程修改專案。
- 預設模型為 `gpt-5.6-sol`，可用 `PLC_ASSIST_CODEX_MODEL` 覆寫。
- UI 顯示 Codex 推理摘要、進度事件與 token usage，不顯示私有逐字思考鏈。
- 真實 GPT-5.6 Sol JOG 生成已通過 validator 與 matiec 編譯。
- Codex Streamlit UI render smoke test及按鈕觸發真實生成的端到端測試均通過。
- pytest 現為 `14 passed`。

## 啟動方式

PLC-Assist：

```powershell
cd D:\AI_PLC
.\venv\Scripts\python.exe -m streamlit run app.py
```

PLC-Assist Codex 推理版：

```powershell
.\venv\Scripts\python.exe -m streamlit run app_codex.py --server.port 8502
```

OpenPLC：

```powershell
$env:OPENPLC_WEB_BASE = "http://localhost:8081"
C:\msys64\usr\bin\bash.exe -lc "OPENPLC_WEB_PORT=8081 /d/AI_PLC/setup/start_openplc.sh"
```

若 Ollama API 沒有監聽 11434：

```powershell
ollama serve
```

## 尚待注意

- 完整測試指令：

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest -q
```

- 參考資料夾 `JidienSyncServer_Release_V1.02.00` 僅供借鑑，已排除在 Git 追蹤之外。
