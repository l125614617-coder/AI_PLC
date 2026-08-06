# PLC-Assist 部署文件

本文件說明如何在一台新的 Windows 機器上，從零開始把 PLC-Assist 整個系統架起來——包含 LLM 生成介面本身，以及選用的「編譯檢查 + 模擬部署」驗證管線。

## 1. 系統概觀

PLC-Assist 是一個 Streamlit 應用，讓使用者透過本機 LLM（Ollama）生成 IEC 61131-3 結構化文字 (ST) 程式碼，並提供多層驗證：

```
使用者輸入 (控制參數)
      │
      ▼
LLM 生成 ST 程式碼 (Ollama, qwen3.5:9b)
      │
      ▼
[Stage 1] validator.py — 規則式靜態檢查（純 Python，離線，永遠可用）
      │
      ▼
[Stage 2] compiler.py — matiec (iec2c) 真實編譯檢查（選用，需要工具鏈）
      │  自動偵測 AXIS_REF 變數 + bEnable 訊號，接上 Modbus 觀測點
      ▼
[Stage 3-5] simulator.py — 部署到 OpenPLC 並跑 Modbus 情境測試（選用，需要工具鏈）
```

第一層（`validator.py`）零依賴、隨開即用。第二、三層需要額外的編譯/模擬工具鏈（見第 4 節），沒裝的話 UI 會優雅降級、不影響基本生成功能。

## 2. 環境需求總覽

| 項目 | 用途 | 是否必要 |
|---|---|---|
| Windows 10/11 | 執行環境 | 必要 |
| Python 3.11+ | 執行 Streamlit app | 必要 |
| Ollama + `qwen3.5:9b` 模型 | LLM 生成引擎 | 必要 |
| MSYS2 + OpenPLC_v3（原生 Windows 建置） | 編譯檢查 + 模擬部署（Stage 2-5） | 選用，但強烈建議 |

## 3. 安裝步驟

### 3.1 取得專案原始碼

將整個專案資料夾複製到目標機器，例如 `D:\AI_PLC`。

### 3.2 建立 Python 虛擬環境並安裝套件

```powershell
cd D:\AI_PLC
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

開發/測試環境（含 pytest）：

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### 3.3 安裝並設定 Ollama

1. 到 [ollama.com](https://ollama.com) 下載安裝 Ollama for Windows。
2. 拉取模型：
   ```powershell
   ollama pull qwen3.5:9b
   ```
3. 確認服務有跑起來（Ollama 安裝完通常會自動啟動並監聽 `http://localhost:11434`）：
   ```powershell
   curl http://localhost:11434/api/tags
   ```

`app.py` 目前寫死呼叫這個 model 名稱（`MODEL_NAME = "qwen3.5:9b"`，見 `app.py:25`）；如果要換模型，直接改這一行即可，但要注意 system prompt 的規範是針對這顆模型的實測行為調校的（見第 6 節），換模型後建議重新驗證一輪。

### 3.4 編譯/模擬工具鏈（選用，Stage 2-5 需要）

這一步負責裝好 `iec2c`（matiec 編譯器）和 OpenPLC_v3 runtime，兩者都是原生 Windows 執行檔，不需要 WSL。

**自動安裝**：執行 `setup\setup_windows_toolchain.ps1`：

```powershell
cd D:\AI_PLC
.\setup\setup_windows_toolchain.ps1
```

這支腳本會：
1. 透過 `winget` 安裝 MSYS2（若尚未安裝）
2. 跑兩次 `pacman -Syu`（MSYS2 首次設定的標準流程，第一次會自動關閉終端機，這是正常現象，腳本會接著跑第二次）
3. 安裝建置工具鏈（gcc、git、make、autoconf 等）
4. 把 OpenPLC_v3 clone 到 MSYS2 家目錄下並執行官方的 `install.sh win_msys2`
5. 修正一個已知的環境問題：OpenPLC 的 Windows 建置腳本寫死了 `/usr/local/include/modbus`、`/usr/local/lib` 這種舊路徑慣例，但 `pacman` 實際上把 libmodbus 裝在 MSYS2 的 MINGW64 前綴下（`/mingw64/...`）——腳本會自動把檔案複製到正確位置
6. 驗證關鍵產物（`iec2c.exe`、`openplc.exe`、`.venv/bin/python3`）確實存在

整個過程約 5-15 分鐘，大部分時間花在套件下載跟編譯上。跑完後 `compiler.py`/`simulator.py` 會自動從 `C:\msys64\home\<你的使用者名稱>\OpenPLC_v3` 找到需要的檔案，不用額外設定路徑。

**手動安裝 / 疑難排解**：如果自動腳本失敗，可以照著腳本內的步驟一步步手動執行（腳本本身寫得很直白，每一步都有註解說明在做什麼）。

## 4. 啟動服務

### 4.0 按需啟動（建議）

```powershell
.\venv\Scripts\python.exe service_manager.py
```

Service Manager 可個別啟停各生成後端、三個 Streamlit 介面與 OpenPLC，
並顯示 PID／健康狀態、開啟網頁或日誌。它不會停止非自己啟動的程序。

```powershell
.\venv\Scripts\python.exe service_manager.py status
.\venv\Scripts\python.exe service_manager.py start llamacpp --openplc
.\venv\Scripts\python.exe service_manager.py stop llamacpp
```

### 4.1 只跑基本生成功能（不需要工具鏈）

Ollama 本地版：

```powershell
cd D:\AI_PLC
.\venv\Scripts\python.exe -m streamlit run app.py
```

瀏覽器開啟 `http://localhost:8501`。

Codex 推理版（需要先完成 `codex login`）：

```powershell
cd D:\AI_PLC
.\venv\Scripts\python.exe -m streamlit run app_codex.py --server.port 8502
```

瀏覽器開啟 `http://localhost:8502`。Codex 版使用唯讀、ephemeral 工作階段，
預設模型為 `gpt-5.6-sol`；可用 `PLC_ASSIST_CODEX_MODEL` 覆寫。生成後會先
自動通過 matiec 編譯閘門，失敗時預設自動修復兩輪；可用
`PLC_ASSIST_CODEX_MAX_REPAIRS` 調整次數。

Qwen3.6-27B llama.cpp MTP 版（本機已放置模型與 Vulkan 發行檔時）：

```powershell
cd D:\AI_PLC
.\setup\start_llamacpp.ps1
```

另開一個 PowerShell：

```powershell
.\venv\Scripts\python.exe -m streamlit run app_llamacpp.py --server.port 8503
```

llama-server 預設只監聽 `127.0.0.1:8082`，介面在 `8503`。可用
`PLC_ASSIST_LLAMACPP_BASE` 與 `PLC_ASSIST_LLAMACPP_MODEL` 覆寫 API 位址及
模型名稱。`setup/start_llamacpp.ps1 -MtpTokens 0` 可關閉 MTP 做基準測試。

### 4.2 完整功能（含 Compile + Simulate）

除了上面的 Streamlit app，還要另外啟動 OpenPLC 的 webserver（負責接收部署請求、跑 Modbus）：

```powershell
C:\msys64\usr\bin\bash.exe -lc "cd ~/OpenPLC_v3/webserver && ~/OpenPLC_v3/.venv/bin/python3 webserver.py"
```

這會佔用終端機前景執行，建議另開一個視窗，或用 `nohup ... &` 丟到背景。OpenPLC 網頁介面的預設帳密是 `openplc` / `openplc`（`simulator.py` 裡寫死這組帳密去自動登入，如果你在 OpenPLC 的 `users` 頁面改過密碼，記得同步更新 `simulator.py` 的 `WEB_PASSWORD`）。

自動情境測試會在每個案例結束後停止測試 Runtime，避免案例之間互相污染。
全部案例通過後，可在結果區按「部署至 2D Twin」，系統會再次部署同一份
編譯程式並保持 Runtime 運行。部署身分保存在
`.runlogs/twin-deployment.json`；Twin UI 只在狀態為 `running` 時開放控制。
在 Runtime 之前，`motion_contract.py` 會核對生成程式的運動函式方塊與 UI
需求，並解析 Position、Velocity 常數；例如 Absolute Position 需求若生成
`MC_MoveVelocity`，會以 `MOTION_MODE_MISMATCH` 阻擋，不會把有效的 JOG
行為誤判為符合定位需求。
Absolute 到位案例會依已解析的距離與速度估算完成時間（最多等待 30 秒），
並輪詢 Done、Position、TargetPosition 與 Velocity，而非使用固定延遲。

對單一 `MC_MoveAbsolute` 且 Position／Velocity 都是一般變數的程式，Compiler
會注入 `%QW6` command position、`%QW7` command velocity 與 `%QX0.15`
apply pulse。Twin 的「移動至目標」會先將 start 清為 FALSE，等待 PLC scan，
寫入兩個 command registers、脈衝 apply，再重新將 start 設為 TRUE，確保
MC_MoveAbsolute 收到新的 Execute 上升沿。Literal 或計算式參數仍可正常驗證，
但不開放互動修改，避免文字改寫或不明確的變數覆蓋。

三個服務都要跑：Ollama（11434）、OpenPLC webserver（預設 8080 + Modbus 502）、Streamlit（8501）。

## 5. Port 一覽表

PLC-Assist Service Manager 預設使用 OpenPLC `8081`。若採用其他連接埠，需在
啟動 PLC-Assist 前設定相同的 `OPENPLC_WEB_BASE`，例如：

```powershell
$env:OPENPLC_WEB_BASE = "http://localhost:8081"
C:\msys64\usr\bin\bash.exe -lc "OPENPLC_WEB_PORT=8081 /d/AI_PLC/setup/start_openplc.sh"
```

| Port | 服務 | 說明 |
|---|---|---|
| 8501 | Streamlit | 主要操作介面 |
| 8502 | Streamlit | Codex 推理版操作介面 |
| 8503 | Streamlit | llama.cpp MTP 版操作介面 |
| 8082 | llama.cpp | Qwen3.6-27B OpenAI-compatible API（僅 localhost） |
| 11434 | Ollama | LLM 推論 API |
| 8080（可設定） | OpenPLC webserver | 部署程式、觸發編譯用的 HTTP 介面 |
| 502 | OpenPLC Modbus TCP | 模擬情境測試讀寫用 |

開發服務的實際監聽介面由各服務設定決定；若機器位於共用網路，請用防火牆限制存取。

## 6. 已知限制與維運注意事項

Runtime 情境會依生成程式選擇適用案例：共同測試啟用與 E-Stop；
`MC_MoveVelocity` 另測限位中止與放開 JOG 後停止；`MC_MoveAbsolute`
另測限位中止與到位；有 `MC_Reset`／`bResetReq` 時另測錯誤復歸。
adapter 以 holding registers 暴露縮放 10 倍的 Position、Velocity、
TargetPosition、TargetVelocity，以及 ErrorID、AxisState。
這些測試使用簡化虛擬軸，不能取代實機安全驗證。

### 實機連線安全閘

連線設定可參考 `hardware_config.example.env`。預設只允許 loopback；
Web 或 Modbus 指向非本機時會拒絕執行，除非明確設定
`PLC_ASSIST_ALLOW_REAL_HARDWARE=1`。啟用前必須另行確認實機 I/O mapping、
驅動器參數、軟硬體限位、E-Stop 安全鏈、低速試車程序與現場風險評估。

### 建立 Windows 發行包

```powershell
.\setup\build_release.ps1 -Version 0.2.2
```

輸出為 `release\PLC-Assist-0.2.2-win64.zip`，包含 GUI Service Manager、
CLI 執行檔、程式碼、設定範例與文件；大型模型、llama.cpp binaries 與
OpenPLC 安裝不打包。

**這條最重要，務必記住**：Streamlit 的自動重整 (Rerun) 只會重新執行 `app.py` 本身，**不保證會重新載入 `compiler.py`、`simulator.py`、`scenarios.py`、`st_common.py`、`validator.py` 這些被 import 進去的模組**。也就是說，如果你（或未來維護這個專案的人）改了這些檔案的內容，光是在瀏覽器按重新整理或 Streamlit 的 Rerun 按鈕**不夠**——必須把 Streamlit process 完全停掉、重新執行 `streamlit run app.py`，改動才會真正生效。這個坑在開發過程中真實踩過：連續好幾輪生成結果對不上預期的修正，最後發現是因為同一個 Streamlit process 從很早之前就一直沒重啟過。

其他值得知道的限制：

- **matiec 編譯器的特殊語法要求**（已經寫進 `app.py` 的 system prompt，但如果之後要手動除錯生成的程式碼，這幾點很關鍵）：
  - `END_IF`、`END_FOR`、`END_WHILE`、`END_CASE` 後面『必須』加分號（例如 `END_IF;`），這套編譯器不像某些其他 IEC 工具那麼寬鬆。
  - 不支援指定長度的字串型別：`STRING[20]`、`STRING(20)` 都會編譯失敗，只能用不指定長度的 `STRING`。
  - 識別字不能以底線開頭（IEC 61131-3 規定必須以字母開頭）。
- **編譯錯誤訊息本身有其極限**：這套 matiec 建置版本一旦遇到真實語法錯誤，錯誤回報的行號有時會有偏移（誤差通常在幾行內），需要對照附近的程式碼判斷；`compiler.py` 已經會在編譯前清空所有註解以避免最嚴重的一種錯誤訊息亂跳問題，但行號偏移本身沒有完全解決。
- **LLM 生成品質有其機率性**：9B 模型偶爾仍會生成語法錯誤或邏輯瑕疵的程式碼，這是預期中的行為，也正是整條 compile-check pipeline 存在的理由——目標不是讓 LLM 每次都完美，而是可靠地攔下它犯錯的時候。UI 上「🧠 顯示思考過程」目前預設關閉，因為實測發現開啟思考模式在這組規範較多的 system prompt 下，容易讓模型陷入反覆推敲甚至耗盡整個 token 預算、完全生不出程式碼。

## 7. 疑難排解

**「Compile + Simulate 顯示工具鏈不可用」**：確認 `C:\msys64\home\<使用者名稱>\OpenPLC_v3\webserver\iec2c.exe` 存在；不存在就重跑第 3.4 節的安裝腳本。

**「明明程式碼看起來沒問題，卻一直顯示編譯失敗」**：先確認你的 Streamlit process 是不是很久以前啟動的（見第 6 節的模組快取問題）——完全重啟一次通常能解決。

**「OpenPLC 部署階段卡住或逾時」**：檢查 `openplc.exe` 是不是有殘留的舊行程佔用 502 port：
```powershell
tasklist | findstr openplc.exe
taskkill /F /IM openplc.exe
```
`simulator.py` 每次部署前後都會嘗試自動清理，但如果是手動中斷測試腳本，可能會殘留。

**「Ollama 生成很慢或沒回應」**：確認 `ollama serve` 有在跑（`curl http://localhost:11434/api/tags`），以及模型是否已經 `ollama pull` 下來。

## 8. 專案結構

```
D:\AI_PLC\
├── app.py                  # Streamlit UI + system prompt + 生成/驗證/模擬的串接邏輯
├── app_codex.py             # Codex 推理版 Streamlit 入口
├── app_llamacpp.py          # llama.cpp MTP 版 Streamlit 入口
├── codex_provider.py         # Codex CLI JSONL 事件與生成後端
├── local_provider.py         # llama.cpp 串流 API adapter
├── benchmark_local_models.py # Ollama / llama.cpp 可重跑 PLC 基準
├── validator.py             # Stage 1：規則式靜態驗證（零依賴）
├── compiler.py               # Stage 2：真實 matiec 編譯檢查 + 軸介面自動注入
├── simulator.py               # Stage 3-5：部署到 OpenPLC + Modbus 情境測試
├── scenarios.py                # 情境測試的步驟定義（set/wait/assert）
├── st_common.py                 # validator.py 與 compiler.py 共用的 ST 解析小工具
├── motion_stubs/                 # 運動控制函式方塊模擬庫 (AXIS_REF, MC_Power, MC_MoveAbsolute...)
├── tests/                          # pytest 測試套件
├── setup/
│   └── setup_windows_toolchain.ps1   # 一鍵安裝 MSYS2 + OpenPLC_v3 的腳本
├── requirements.txt                    # 執行期依賴
├── requirements-dev.txt                 # + 測試依賴 (pytest)
└── DEPLOYMENT.md                          # 本文件
```
