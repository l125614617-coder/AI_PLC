# PLC-Assist

使用 LLM 生成 IEC 61131-3 結構化文字 (ST) 程式碼的小工具，目標是做運動控制相關的邏輯（JOG、絕對位置移動、緊急停止、復歸這些）。

| 版本 | 網址 | 模型來源 |
|---|---|---|
| Ollama 本地版 | `http://localhost:8501` | 本機 `qwen3.5:9b` |
| Codex 推理版 | `http://localhost:8502` | 已登入的 Codex CLI，預設 `gpt-5.6-sol` |
| llama.cpp MTP 版 | `http://localhost:8503` | 本機 `Qwen3.6-27B Q3_K_M` |

Codex 版顯示安全的推理摘要、進度與 token 使用量，不顯示或偽造模型的私有
逐字思考鏈。兩版共用相同的 ST validator、matiec 編譯器及 OpenPLC/Modbus
情境測試。Codex 版會在顯示結果前自動執行 matiec；若編譯失敗，最多自動
將真實錯誤交回 Codex 修復兩輪。

模擬 adapter 同時支援 `bEnable : BOOL;` 與
`bEnable : BOOL := FALSE;`，兩種宣告都能由 Modbus `start` 訊號驅動。

## 建議啟動方式：Service Manager

```powershell
.\venv\Scripts\python.exe service_manager.py
```

管理器可選「快速本機」「Codex」「27B 高品質」或「全部測試」，並可選擇
是否同時啟動 OpenPLC。每個服務都有啟動、停止、開啟網頁、日誌及健康狀態；
只會停止由管理器自己啟動的 PID，外部服務只會標示為 external。llama.cpp
可選擇 MTP tokens（0 表示關閉）。

日常建議一次只啟動一個生成後端；Qwen3.6-27B 使用最多 RAM／共享 GPU
記憶體，OpenPLC 只需在 Compile + Simulate 時啟動。

會做這個東西是因為每次要手寫一段基本的運動控制 ST 都要重新想一次安全互鎖邏輯，很煩，乾脆讓 LLM 先出草稿，人再看過修。但 LLM 生成的程式碼不能照單全收——所以這個專案真正花時間的地方其實不是「生成」，是後面那三層驗證，確保吐出來的東西至少「編得過」、而且「行為合理」，不是每次都靠肉眼抓 bug。

## 這東西在幹嘛

流程大致是：

1. 在網頁介面填一下控制參數（JOG / 絕對位置、速度、位置、要不要開緊急停止）
2. LLM 生成 ST 程式碼 + 變數表 + 說明 + 安全警告
3. 本地規則式檢查（`validator.py`）——秒出結果，抓明顯的低級錯誤
4. （選用）真的丟去 matiec 編譯一次（`compiler.py`）——這一步才會抓到 regex 檢查不出來的真實語法/型別錯誤
5. （選用）把編出來的東西部署到 OpenPLC，跑幾個 Modbus 情境測試（`simulator.py`），實際驗證緊急停止之類的安全邏輯有沒有真的生效

第 4、5 步是選用的，因為要另外裝一套編譯/模擬工具鏈（MSYS2 + OpenPLC_v3），沒裝的話前三步照常能用。

## 快速開始

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

裝好 Ollama、拉一下模型：

```powershell
ollama pull qwen3.5:9b
```

跑起來：

```powershell
.\venv\Scripts\python.exe -m streamlit run app.py
```

開 `http://localhost:8501` 就能用了。

Codex 第二版需要先確認 Codex CLI 已登入：

```powershell
codex login
.\venv\Scripts\python.exe -m streamlit run app_codex.py --server.port 8502
```

開 `http://localhost:8502`。若要更換 Codex 模型，可在啟動前設定
`PLC_ASSIST_CODEX_MODEL`；預設為 `gpt-5.6-sol`。

### Qwen3.6-27B MTP 實驗版

llama.cpp 與模型是大型本機產物，分別放在被 Git 排除的 `tools/` 與
`models/`。先啟動 llama-server：

```powershell
.\setup\start_llamacpp.ps1
```

再開另一個 PowerShell 啟動介面：

```powershell
.\venv\Scripts\python.exe -m streamlit run app_llamacpp.py --server.port 8503
```

預設使用 Vulkan、8K context、單一請求，以及 Qwen3.6 原生 MTP 兩個 draft
tokens。若要量測無 MTP 基準，可用：

```powershell
.\setup\start_llamacpp.ps1 -MtpTokens 0
```

這個版本不會取代 Ollama；llama-server 未啟動時仍可照常使用 8501 的
Ollama 版。

## 裝 OpenPLC（完整功能要用到）

前面三步裝好就能用了，但如果想要第 4、5 步的「真的編譯 + 部署到 OpenPLC 跑 Modbus」，還要多裝一套東西：MSYS2（Windows 上的編譯工具鏈）跟 OpenPLC_v3。這兩個都是原生 Windows 執行檔，不用 WSL。

偷懶版，跑腳本就好：

```powershell
.\setup\setup_windows_toolchain.ps1
```

這支腳本會自動：
1. 用 `winget` 裝 MSYS2（沒裝的話）
2. 跑兩次 `pacman -Syu`（MSYS2 第一次設定的固定流程——第一次跑完會自己把終端機關掉，這是正常的，不是壞掉，腳本會接著跑第二次）
3. 裝 gcc、git、make 這些建置工具
4. 把 OpenPLC_v3 clone 下來，跑它自己的 `install.sh win_msys2`
5. 修一個環境問題：OpenPLC 的 Windows 建置腳本認定 libmodbus 裝在 `/usr/local/...`，但 `pacman` 實際上裝在 MSYS2 的 `/mingw64/...` 下，腳本會自動把檔案複製到它要找的位置
6. 檢查 `iec2c.exe`、`openplc.exe` 這些關鍵產物真的有生出來

整個跑完大概 5-15 分鐘，大部分時間在下載套件跟編譯。跑完之後 `compiler.py`/`simulator.py` 會自己從 `C:\msys64\home\<你的使用者名稱>\OpenPLC_v3` 找到需要的東西，不用另外設定路徑。

裝完之後，除了 Streamlit，還要另外起一個 OpenPLC 的網頁服務（負責接收部署、跑 Modbus）：

```powershell
C:\msys64\usr\bin\bash.exe -lc "cd ~/OpenPLC_v3/webserver && ~/OpenPLC_v3/.venv/bin/python3 webserver.py"
```

這個會佔住終端機，開一個新視窗跑或丟到背景執行都行。OpenPLC 網頁介面預設帳密是 `openplc` / `openplc`（寫死在 `simulator.py` 裡，改密碼記得同步改那邊）。

如果 8080 已被其他軟體占用，可改用 8081：

```powershell
$env:OPENPLC_WEB_BASE = "http://localhost:8081"
C:\msys64\usr\bin\bash.exe -lc "OPENPLC_WEB_PORT=8081 /d/AI_PLC/setup/start_openplc.sh"
```

如果自動腳本跑失敗，或想知道每一步實際在做什麼，`DEPLOYMENT.md` 裡有更完整的說明跟疑難排解。

## 專案裡有什麼

- `app.py` — 整個 Streamlit 介面，包含餵給 LLM 的 system prompt（這份 prompt 其實改了很多輪，踩過不少雷，細節寫在 `DEPLOYMENT.md`）
- `app_codex.py` — Codex 推理版的獨立 Streamlit 入口
- `app_llamacpp.py` — Qwen3.6-27B / llama.cpp MTP 版入口
- `codex_provider.py` — 以唯讀、暫時 Codex CLI 工作階段生成 ST
- `local_provider.py` — llama-server OpenAI-compatible 串流轉接器
- `service_manager.py` — 按需啟停服務的 GUI／CLI 管理器
- `plc_config.py` — OpenPLC/Modbus 設定與遠端硬體安全閘
- `validator.py` — 純規則式的靜態檢查，沒有外部依賴，永遠能跑
- `compiler.py` / `simulator.py` / `scenarios.py` — 真正編譯 + 模擬部署那條 pipeline
- `motion_stubs/` — 手寫的運動控制函式方塊模擬庫（`MC_Power`、`MC_MoveAbsolute` 之類），LLM 生成的程式碼是接這一套跑的，不是自己重新發明安全邏輯
- `tests/` — pytest，主要蓋 `compiler.py` 那些比較細節的行為

## 目前的狀態老實說

這個 9B 的模型（本機能跑得動的大小）偶爾還是會生成語法錯的、或邏輯怪怪的程式碼，這是預期中的事，也是為什麼要有編譯與 runtime 情境把關，而不是完全信任 LLM 的輸出。目前模擬部署會依 JOG／Absolute 程式測試啟用、緊急停止、正負限位、Reset、連續啟停、運行中方向切換，以及 Absolute 到位；位置、速度、目標值、ErrorID 與 AxisState 會透過 holding registers 驗證。它仍是簡化的虛擬軸模型，不等同實機伺服器、機構負載與安全迴路驗證。
