# PLC-Assist 專案記憶

最後更新：2026-07-27（Asia/Taipei）

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
- Intel Core Ultra 7 155H 的整合式 Intel Arc 已由 llama.cpp Vulkan 辨識：
  18,400 MiB shared GPU memory。
- llama.cpp Windows Vulkan b10142 安裝於 `tools/llama.cpp`（Git 排除）。
- Qwen3.6-27B MTP Q3_K_M 安裝於
  `models/Qwen3.6-27B-Q3_K_M.gguf`（13,818,688,640 bytes，Git 排除）。
- 模型 SHA-256：
  `f8a9329b78446254200d5cd387c3d8c8f374a2b824696d4b550f42461b970310`，
  與 Hugging Face LFS OID 一致。
- llama.cpp MTP API：`http://127.0.0.1:8082`
- PLC-Assist llama.cpp MTP 版：`http://localhost:8503`

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
- Codex 生成現在會自動執行 matiec；失敗時把真實 compiler issues 交回 Codex，
  最多自動修復兩輪，再把結果顯示給使用者。
- 修正多行 FB 呼叫中 `Execute :=`、`Velocity :=` 等具名參數被誤判為未宣告變數，
  以及最後一個具名參數被誤判為缺分號的問題。
- 移除與「安全由 MC_* 內建」政策矛盾的 E-Stop/Limit 缺失提示。
- 新增 `E064`，可在 matiec 前攔截 `AXIS_REF.ErrorID : DINT` 被指定給 `DWORD` 的錯誤。
- pytest 現為 `17 passed`。

### bEnable 初值造成 Runtime 0/2

- Codex 生成 `bEnable : BOOL := FALSE;` 時，舊版 adapter 的 regex 只辨識
  `bEnable : BOOL;`，所以雖然 matiec 通過，Modbus `start` coil 並未橋接到程式。
- `_BENABLE_PATTERN` 已支援含初值的 BOOL 宣告。
- 已加入 compiler 回歸測試，pytest 現為 `18 passed`。
- 已用使用者回報的完整 JOG 程式重新部署 OpenPLC：
  `enable_responds` 與 `estop_cuts_power` 均通過（2/2）。

### Qwen3.6-27B llama.cpp MTP 版

- 新增 `app_llamacpp.py`，與 8501 Ollama、8502 Codex 版本並存。
- 新增 `local_provider.py`，把 llama-server OpenAI-compatible SSE 轉成既有
  UI 使用的串流介面。
- 新增 `setup/start_llamacpp.ps1`，預設 Vulkan、8K context、單一 slot、
  MTP draft tokens=2；使用 `-MtpTokens 0` 可跑無 MTP 基準。
- 新增 `benchmark_local_models.py`，同一 PLC prompt 可比較 Ollama 與
  llama.cpp，並自動執行 validator 與 matiec。
- 短請求、256 completion tokens 實測：
  - 無 MTP：2.90 tokens/s、100.7 秒。
  - MTP=2：4.57 tokens/s、70.5 秒，draft acceptance 66.5%。
  - MTP 生成吞吐提升約 57.7%。
- 完整 PLC prompt 實測：
  - JOG：170.5 秒，5.13 tokens/s，validator 通過、matiec compiled。
  - Absolute Position：194.6 秒，5.13 tokens/s，validator 通過、
    matiec compiled。
  - 兩次完整案例的 MTP acceptance 約 80%。
- Qwen3.6 產生的 JOG 程式已實際部署到 OpenPLC：
  `enable_responds` 與 `estop_cuts_power` 均通過（2/2）。
- 相同 JOG prompt 的現有 `qwen3.5:9b`：141.2 秒、9.67 tokens/s，
  validator 與 matiec 同樣通過。因此 27B MTP 目前定位為較慢的高品質
  實驗模式，Ollama 9B 保留為預設快速模式。
- pytest 當時為 `20 passed`。

### 擴充 Runtime 情境

- axis adapter 新增 `active`、`aborted`、`invelocity`、`reset`、`moving`
  Modbus coils，並可將 `bResetReq` 接到測試輸入。
- `MC_MoveVelocity` 現在會處理正負限位，限位或 E-Stop 時同步設定
  `Axis.CommandAborted`，放開 JOG Execute 時速度歸零。
- 情境會依生成程式使用 `MC_MoveVelocity` 或 `MC_MoveAbsolute` 自動選擇，
  不會對 JOG 錯誤要求定位完成。
- Qwen3.6 JOG 程式已在 OpenPLC 實測 5/5：
  `enable_responds`、`estop_cuts_power`、`limit_aborts_motion`、
  `jog_release_stops`、`reset_clears_error`。
- Absolute Position fixture 已在 OpenPLC 實測 5/5，額外確認
  `absolute_reaches_target` 的 `Done=TRUE` 且速度歸零。
- 2026-07-27 重新執行即時模型驗收：
  - llama.cpp Qwen3.6-27B JOG：validator 0 issue、matiec compiled。
  - Ollama qwen3.5:9b JOG：validator 0 issue、matiec compiled。
- pytest 現為 `23 passed`。

### Service Manager、數值觀測與進階 Runtime

- 新增 `service_manager.py` GUI／CLI，可按模式啟停、查看健康/PID、開網頁
  與日誌，並調整 llama.cpp MTP tokens；只停止自己啟動的 PID。
- 新增 holding registers：Position、Velocity、TargetPosition、
  TargetVelocity（縮放 10 倍）、ErrorID、AxisState。
- 修正 `MC_MoveVelocity` 負速度時位置方向顛倒。
- OpenPLC 實測：負向 JOG／負限位／Reset 5/5；連續啟停與正轉切負轉
  6/6；Absolute Position 5/5，Position=250.0、Velocity=0。
- 新增 compile timeout 回歸測試。
- 新增 `plc_config.py`，非 loopback PLC 預設拒絕，實機需明確 opt-in。
- pytest 現為 `34 passed`。

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

Qwen3.6-27B llama.cpp MTP：

```powershell
.\setup\start_llamacpp.ps1
.\venv\Scripts\python.exe -m streamlit run app_llamacpp.py --server.port 8503
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
