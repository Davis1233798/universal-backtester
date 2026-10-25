# Universal Backtester · 專業量化研究工作台

> 2026-10-25 前端重構：現已提供 React + TypeScript + Vite 的專業介面，
> 借鑑 CryptoQuantX 的工作區設計，並重新實作元件。API 的數學模型
> 仍是 Python 基礎版本，**尚非完整 Pine Script 或 Rust 原生數億根回測器**。

### 前端功能

- 可縮放 K 線、成交量、EMA9/21、Bollinger、RSI、MACD 及買賣標記
  （Lightweight Charts v4 使用本機 bundle，無外部 JavaScript CDN）。
- 左側工作區導覽：策略回測、策略工廠、多市場回測、績效分析、
  歷史回測、每日排程。桌面／平板／手機響應式版面。
- 私人策略庫：Pine 代碼、內建策略參數及不可變的修訂歷史，
  支援建立、修改、刪除、還原；所有路由受私人 Bearer Token 保護。
- 批次回測：交易所矩陣（CEX + Hyperliquid），以及研究用
  同步共享資金價差策略。交易模型限制在頁面中明確標示。
- 勝率、PF、最大回撤、平均 R、Sharpe、Sortino、Calmar、交易日誌與 JSON 匯出。
- 可選 AI 策略草稿：設定後端私密環境變數 `UBT_AI_API_KEY`
  （可選 `UBT_AI_MODEL`，預設 `gpt-4.1-mini`）後提供自然語言策略草稿。
  生成程式需通過有限的 Pine 相容子集解析，**絕不自動執行或下單**。
  若未配置，API 返回 503，而非捏造 AI 結果。

### 本機建置與啟動

```bash
# 在專案根目錄先自行建立未提交的 .env
# UBT_API_TOKEN 至少 32 字元，不可使用範例測試 Token
docker compose up --build -d
```

Docker 會先建置 `frontend/` Vite bundle，再透過 FastAPI
供應 `/assets/*`；獨立 Python 啟動且缺少 bundle 時使用
`unibacktest/static/index.html` 舊版安全備援介面。
本機前端開發：`cd frontend && npm install && npm run dev`，
Vite 會將 `/api` 代理到本機 `127.0.0.1:8000`。

**部署安全：** `render.yaml` 預設私人 API；必須在 Render Dashboard
設定私人 `UBT_API_TOKEN`。公開 Demo 需明確設 `UBT_PUBLIC_DEMO=1`，
僅有合成行情且不能儲存策略或呼叫交易所。SPA 授權 Token
僅留在目前頁面的記憶體，不寫到網址或 localStorage。
正式多人服務仍需要帳戶與資源隔離、速率限制和沙盒。

**Render 網址：** 必須先設定 GitHub Actions variable `RENDER_SITE_URL`
為實際的 Render 網址，部署驗證任務才會以 /api/health 的 Commit
回報確認服務已上線。**CI 綠燈不等於 Render 已部署成功。**

---

# Universal Backtester · 多市場量化回測系統（MVP 0.1）

**可立即使用的回測原型；不是所有交易所、所有合約或所有策略語言的完整相容實作，也不是交易所實盤撮合模擬器。**

主要功能：

- Web UI (`http://127.0.0.1:8000`)、REST API (`/docs`)、命令列 `ubt`。
- CEX／部分 DEX：透過 CCXT 支援有 `fetchOHLCV` 能力且商品已掛牌的交易所、現貨或線性合約；可在 API `/api/sources` 檢視 CCXT 安裝後交易所 ID 清單。是否有完整商品/時段/資金費率仍取決於個別交易所。
- DEX：Hyperliquid 永續合約原生 `/info` K 線，最多最近 5,000 根；包括可選的歷史資金費率。其他 DEX 用 CCXT（如其有接入）或自行編寫資料來源插件。
- 全球股票：`yfinance` 可查支持的全球代號，例如 `AAPL`, `2330.TW`, `7203.T`, `0700.HK`；受 Yahoo 來源的可取得範圍、使用條款、除權息、時區與存活偏差等限制。需要大規模商業股市資料時換成授權資料商插件。
- 離線 CSV：任何來源的 OHLCV/K 線資料；選擇性每根 `funding_rate`。
- 一致 UTC 毫秒時間戳；日期範圍為 **[start, end)**，也就是包含 start、不包含 end。
- SQLite WAL 歷史快取（以 provider/exchange/symbol/timeframe/marketType/funding 存不同序列）、增量下載、保存每次回測績效與交易紀錄。
- 策略：SMA 交叉、RSI、Donchian、買入持有；可信任 Python 插件；JavaScript/TypeScript、Go、Rust、C#、Java、R、Julia 等可使用 **JSON Lines 程序協定**；訊號 CSV 適用 Pine Script 等無法在平台直接執行的語言。
- 下一根開盤成交、線性合約多空、費用/滑價、槓桿、約略強平、指定資金費率、績效（總報酬、CAGR、回撤、Sharpe、勝率）與資金曲線。
- 在獨立常駐服務內執行已保存的每日回測任務（預設 Asia/Taipei 08:00）。

## 1. 啟動（Docker；建議）

解壓縮至目錄後在專案根目錄執行：

```bash
docker compose up --build -d
```

瀏覽 `http://127.0.0.1:8000`；FastAPI Swagger API 在 `http://127.0.0.1:8000/docs`。

**重要：** `docker-compose.yml` 把網頁限制在 `127.0.0.1:8000`，不要直接暴露給公開網路。`api` + `scheduler` 共用 `./data` SQLite；後者每日 08:00 台北時間執行任務。Docker 容器內路徑請用 `/app/data/*.csv`。

### 純 Python

Python 3.11+：

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -e '.[all]'
ubt demo
uvicorn unibacktest.api:app --host 127.0.0.1 --port 8000
# 第二個終端：
ubt scheduler --time 08:00 --tz Asia/Taipei
```

不需安裝所有外部資料套件也可跑離線示範：`pip install -e '.[test]'`。

## 2. 命令列實例

```bash
ubt demo
ubt backtest examples/config-demo.json
ubt backtest examples/config-binance-perp.json
ubt backtest examples/config-taiwan-stock.json
ubt add-job examples/config-binance-perp.json
ubt jobs
ubt run-due --time 08:00 --tz Asia/Taipei
pytest -q
```

`ubt demo` 使用**合成行情**，其報酬不代表真實市場表現。真實 Binance 衍生品使用 `binanceusdm` 交易所 ID 與 `BTC/USDT:USDT` 符號；如目前所在地或 API 權限不允許使用，改用其他合法可存取資料源，或 CSV。

### API

```bash
curl -X POST http://127.0.0.1:8000/api/backtests \
  -H 'Content-Type: application/json' \
  -d '{"data":{"provider":"demo","symbol":"SYNTHETIC","start":"2024-01-01","end":"2025-01-01","timeframe":"1d"},"strategy":{"type":"builtin","name":"sma_cross","options":{"fast":10,"slow":30}},"risk":{"initial_cash":10000,"product_type":"spot","leverage":1}}'
```

其他 API：`GET /api/sources`、`GET /api/health`、`GET /api/backtests`、`GET /api/backtests/{id}`、`POST /api/jobs`、`GET /api/jobs`、`PATCH /api/jobs/{id}?active=false`。建立任務不會自己執行；**必須**同時啟動 scheduler。

## 3. 行情與歷史資料來源

| Provider | 已實作 | 條件與限制 |
|---|---|---|
| `demo` | 是，完全離線 | 人工生成，僅供測試 |
| `csv` | 是，完全離線 | 接受任何授權來源的 OHLCV 欄位 |
| `ccxt` | 有統一 OHLCV + 可選歷史 funding API | `pip install -e '.[cex]'`; 不是每所/商品都支援 |
| `hyperliquid` | 原生永續 K 線與資金費率 | API 僅最近約 5,000 根 K；舊歷史需自建存檔/第三方數據 |
| `yfinance` | 全球 Yahoo 支援的股票代號 | `pip install -e '.[stocks]'`; 研究/個人用途條款、資料可得性受限 |
| `plugin:<python_module>` | 自行撰寫 | 受信任主機 `UBT_ALLOW_EXEC=1`，匯入模組的 `fetch(req)` |

**提醒：** 本 MVP 不支援原生逆向合約 / 幣本位非線性 P&L、選擇權的非線性到期支付、期貨換月、幣種換匯、借券融券、股票完整企業行為事件；不應把這些商品視為已通過正確性驗證。可先將價格/資金費率標準化為線性 USD 或 USDT 報價後研究，但契約細節仍須補實作。`market_type` 只是 CCXT 市場選擇參數，不代表此引擎包含全部合約規則。

### CSV 來源格式

```csv
ts,open,high,low,close,volume,funding_rate
2024-01-01T00:00:00Z,100,106,98,105,1000,0
2024-01-02T00:00:00Z,105,111,104,110,1200,0.0001
```

- `ts` 是 K 線開盤 UTC ISO 8601、UNIX 秒或毫秒。
- `funding_rate` 可省略；未提供視為 **0，會低估/高估永續合約表現**。
- 股票日線/週線以交易所當地**交易日**映射成 UTC 午夜作儲存鍵；股票盤中線與加密貨幣保存實際 UTC 時間。
- 同一來源多次更新依時間戳覆寫；`refresh=true` 重新讀取數據，預設讀快取。
- 本引擎把資金費率視為該 K 線內到期應計費用；多筆事件聚合到大週期時按利率相加，屬於近似。
- K 線缺口不會填平；結果 `warnings` 提醒缺資料或非交易日。不同股票交易所的休市日不適合用加密貨幣的連續 K 線檢驗標準判斷。

## 4. 策略語言／插件協定

### 4.1 內建策略

`buy_hold`、`sma_cross`（參數 `fast`, `slow`, `long_short`）、`rsi_revert`（`period`, `buy_below`, `sell_above`, `long_short`）、`breakout`（`lookback`,`long_short`）。

每根 K 收盤後計算：

- `target = 1`：將本策略的配置資金設定成**滿倉多單**。
- `target = 0`：平倉。
- `target = -1`：滿倉空單，僅線性合約允許。
- `target` 必須介於 `-1` ~ `1`；名義槓桿 `leverage × abs(target)`。倉位保持到下一次目標變更，非每日重新等比調倉。

### 4.2 Python 插件（非隔離沙盒）

參考 `examples/python_strategy.py`，提供 `on_bar(ctx) -> float`：

```json
{
  "strategy": {"type": "python", "path": "examples/python_strategy.py"}
}
```

**只執行自己信任的程式**：

```bash
UBT_ALLOW_EXEC=1 ubt backtest my_config.json
```

### 4.3 JavaScript、Go、C#、Rust、Java、R 等其他語言

使用固定程序協定：啟動一個常駐可執行程序，從標準輸入逐行讀取 JSON，對每個請求**只輸出一行** `{"target":0.0}`；stdout 不可用於 log。輸入 JSON：

```json
{
  "bars": [{"ts": 1704067200000, "open": 100, "high": 103, "low": 99, "close": 102, "volume": 123, "funding_rate": 0}],
  "target": 0,
  "position": 0,
  "wallet": 10000,
  "equity": 10000,
  "timeframe": "1d"
}
```

`bars` 最多保留最近 500 根**已收盤** K 線，沒有未來 K。每行同步回答，預設 3 秒超時會殺掉程序；跨語言腳本可以保存程式內狀態。

```json
{"strategy":{"type":"process","command":["node","examples/javascript_strategy.mjs"],"timeout":3}}
```

Go 例子：`go build -o /tmp/ubt-go examples/go_strategy.go`；啟用 `UBT_ALLOW_EXEC=1` 後，command 設為 `["/tmp/ubt-go"]`。TypeScript 可編譯成 JS，其他語言只需遵守相同 JSON-lines 協定。Docker 內建 Node.js，但 Go/C#/Rust/Java/R 等需自行安裝執行環境或掛載已編譯程式。**不是可以任意貼入任何語言原始碼就直接執行**。

### 4.4 TradingView Pine Script

Pine Script 需要 TradingView Pine runtime；本程式**沒有**內建 Pine 編譯器或策略解譯器。`examples/pine_strategy.pine` 展示畫出 `UBT_TARGET` 訊號；可在 TradingView 匯出圖表資料（依帳戶功能），將 Time/UBT_TARGET 欄轉成 `ts,target`，再用訊號 CSV：

```json
{"strategy":{"type":"signal_csv","path":"examples/strategy_signals.csv"}}
```

CSV 的 `ts` 必須是**發出訊號那根 K 的開盤時間**，目標在這根 K 的收盤時才可得，實際成交在下一根 K 開盤。**若匯出的訊號本身使用未來函數，平台無法消除這個偏差。**

### 4.5 擴充新的交易所、股票來源或 DEX

`examples/vendor_adapter.py` 是外掛範例。將模組放在 Python module path：

```bash
PYTHONPATH=examples:. UBT_ALLOW_EXEC=1 ubt backtest my_vendor_config.json
```

`data.provider = "plugin:vendor_adapter"`；模組實作 `fetch(req: DataRequest) -> list[Bar]`。回傳型別、OHLC 有效性、時間排序與範圍會再檢查。讀取交易所 REST API、RPC、indexer 或收費資料商須遵循授權、限流和存取權限。專案也可延伸到 Polygon、EODHD、TWSE、GMX、dYdX 等，但**這些特定來源尚未在本 MVP 綁定/實測**。

## 5. 回測假設與研究注意事項

**已做：** 不偷看未來 K、交易訊號下一根 K 開盤成交；收盤標記；線性多空、單一淨倉位；固定單邊 fee bps / slippage bps；倉位事件；指定歷史資金費率；極端價格低於維持保證金的近似強平；所有假設回傳於 `assumptions`。

**尚未做（很重要）：** 交易所級分層維持保證金及逐倉/全倉規則、保險基金、ADL、不同交易對的合約乘數、tick size/lot size、成交量限制/價格衝擊、K 線內 OHLC 先後順序、limit/stop order、L2 order book、可成交性分析、股票股息稅費/拆併、股票退市股票的存活偏差、外匯匯率、期貨展期、跨資產投資組合、walk-forward 優化、多重測試校正與回測資料授權保證。OHLC 強平以最不利極值估計，**可能比實際更悲觀**，也無法正確處理跳空後的真實撮合。

因此不應把某個回測的「勝率」當成實際可達成報酬。要做可信的策略比較，需要相同的成本、資料品質、樣本切分和風險控制；正式交易前需獨立驗證。

## 6. 日排程、資料延續與限制

- `POST /api/jobs` 儲存任務，獨立 `ubt scheduler` 每日一輪；執行失敗會保存錯誤狀態，**同一天不自動重試**。
- 啟動時間晚於指定時間也會補跑**當天**尚未執行的任務；跨日停機不會補跑歷史漏執行日期。
- 使用增量更新（回頭抓取最後 2 根 K）。若來源在更早時間修改資料，須自行 `refresh=true` 強制重抓完整歷史。
- 定期備份 `./data/backtests.sqlite3`；單機 SQLite 適合小型研究，海量 1 秒數據應改 Parquet/ClickHouse/TimescaleDB 等並對引擎進行效能擴展。
- 資料查詢不需要交易所 API 金鑰（公開歷史 K 線）；部分來源對地區、限流、歷史存取與費用有額外限制。
- 部分交易所實際能提供多久數據取決於上線日、API 分頁與保存期限；平台不會自行創造不存在的歷史行情。

## 7. 測試

```bash
pip install -e '.[test]'
pytest -q
```

測試涵蓋：下一根開盤、資金費率多空、強平、目標倉位驗證、SQLite、CSV、Daily scheduler、HTTP UI/API、模擬 CCXT/Hypeliquid API、Node.js JSON Lines 程序。模擬 API 測試**不等於已驗證交易所可連線**；建議在部署主機對幣別、時段和 API 權限做真實下載測試。

## 8. 技術參考

- CCXT manual: https://github.com/ccxt/ccxt/wiki/Manual
- Hyperliquid candle/funding info API: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- yfinance documentation and legal disclaimer: https://ranaroussi.github.io/yfinance/
- TradingView strategies: https://www.tradingview.com/pine-script-docs/faq/strategies/

## 8. GitHub Actions：CI/CD 與版本發布

專案的 `.github/workflows/ci-cd.yml` 在以下事件執行：

- **Pull Request → `main`**：Python 3.11／3.12／3.13 測試、套件編譯、CLI smoke test、Python wheel/sdist 建置與驗證，以及 Docker Compose 檢查、Docker build 與 HTTP health check。PR **不推送映像**。
- **推送到 `main`**：先跑上述檢查；全部成功後，使用內建 `GITHUB_TOKEN` 推送 **linux/amd64 + linux/arm64** Docker 映像到 GitHub Container Registry，標籤包含 `latest` 和 `sha-<commit>`。不需要個人 PAT。
- **推送 `vX.Y.Z` 標籤**：同樣先跑 CI，推送帶版本標籤的 Docker 映像，並在 GitHub Releases 發布 Python wheel 和 source distribution。版本必須與 `pyproject.toml` 的 `project.version` 一致。Release 不包含 Windows `.exe` 或 `.msi`。

查看 [Actions](https://github.com/Davis1233798/universal-backtester/actions) 與 [Releases](https://github.com/Davis1233798/universal-backtester/releases)。GHCR 映像路徑：`ghcr.io/davis1233798/universal-backtester:latest`（只有 `main` 的 publish job 成功後才會存在）。例如：

```bash
# 映像已發布時可拉取；預設 Web UI 僅綁定本機
# 注意：將 /your/path/data 改為實際資料目錄
docker run -d --name ubt-api -p 127.0.0.1:8000:8000 \
  -v /your/path/data:/app/data \
  ghcr.io/davis1233798/universal-backtester:latest
```

建立版本標籤時，先修改 `pyproject.toml` 版本並確保它已推到 `main`，再建立符合的 `vX.Y.Z` Git 標籤。**CI/CD 只自動發布到 GHCR / GitHub Releases，不會擅自部署到自有主機或公開網路**；若要做到真正的遠端環境自動部署，還需要部署目標、認證機制與網路安全設定。


## 9. 公開網頁測試部署（Render Blueprint）

為了避免公開執行外部 Python/JS 程式及任意路徑讀取，`render.yaml` 預設使用
**`UBT_PUBLIC_DEMO=1` 公開示範模式**。此模式仍在伺服器上運行實際
Python 回測引擎，但是 **只能使用人工合成 K 線**，無法查詢 CEX／DEX／股市
的真實行情，也不會保存回測結果或啟動每日排程。單次最多 1,500 根 K 線；
自動限制公開回測同時執行數。API 文件仍在 `/docs`。

按以下連結在自己的 Render 帳號建立 **免費 Web Service**（需在 Render 確認
授權及建立部署）：

[Deploy to Render](https://render.com/deploy?repo=https://github.com/Davis1233798/universal-backtester)

Render 完成建置後會顯示實際 `https://...onrender.com` 網址。**在 Render 未完成部署前，
不能假定該網址存在。** Blueprint 定義 Singapore 區域、Docker、`/api/health`
健康檢查、成功 CI 才自動部署（有串接 GitHub provider 時）。
免費服務閒置後會休眠，重開存在冷啟動延遲，亦不含持久化磁碟。

完整 CEX／DEX／股票版本不可不加權限驗證直接暴露到公網；應另外建立
**有登入驗證、配額、隔離背景工作及持久資料庫**的私有部署。


## 10. 自訂 Pine Script 策略與跨市場商品搜尋

網頁的「策略」欄位現在可選 **自訂 Pine Script（相容子集）**，直接貼上
TradingView 常見 `.pine` 程式碼或上傳檔案。程式由限定 AST 直譯器執行，**不用**
`eval()`、`exec()` 或 shell，允許公開示範環境安全測試常見的
`input.int/float`、`ta.sma/ema/rsi/highest/lowest`、
`ta.crossover/ta.crossunder`、`if`、`strategy.entry`、
`strategy.close`、`strategy.close_all`。參考
`examples/pine_custom_crossover.pine`。

API 例（用 Python 發送 JSON 可保留 Pine 的多行字串）：
```python
import requests
code = """//@version=6
strategy("MA crossover")
fast = ta.sma(close, 10)
slow = ta.sma(close, 30)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("Long")
"""
result = requests.post("http://127.0.0.1:8000/api/backtests", json={
    "data": {"provider":"demo","symbol":"SYNTHETIC",
             "start":"2024-01-01","end":"2024-06-01"},
    "risk": {"product_type":"spot","leverage":1},
    "strategy": {"type":"pine", "code":code},
})
print(result.json())
```

**重要差異**：這不是 TradingView Pine v5/v6 完整解譯器。
不支援 `strategy.exit` 限價/停損與網格掛單、
`request.security` 跨時間框架、`array/matrix`、function definitions、
`for/while`、library import、label/table 繪圖，亦沒有原生 Pine broker emulator
的完整行為。遇到不支援語法會回應錯誤而不會假裝策略已正確跑完。
`ta.ema` 與 `ta.rsi` 有短視窗初始化的近似誤差。
要求更完整 Pine v4–v6 轉譯可使用獨立
[PyneComp / PyneCore](https://pynecore.org/docs/cli/compile/) 流程
（需要 PyneSys API key），或用 TradingView 匯出訊號 CSV。
自訂 Python、JavaScript、Go 等策略仍可透過**可信任的私有部署**
和 JSON-lines 外掛接口執行。

商品不使用固定列表，而由實際供應商搜尋：
`GET /api/markets?provider=ccxt&exchange=bybit&market_type=swap&q=BTC&limit=50`
列出目前活躍合約交易對；
`provider=hyperliquid&q=BTC` 讀取原生永續合約清單；
`provider=yfinance&q=TSMC` 搜尋全球股票代號。
CCXT 的 `spot`、`swap`、`future` 市場類型可分別搜尋，
交易所 ID 可由 `GET /api/sources` 取得。查到商品不代表該供應商一定有
指定週期的歷史 OHLCV、過去已下市商品或其合約規格；**目前不可能保證
全球所有加密幣與所有股票都有完整免費歷史行情**。
公開 Render 示範模式的 `/api/markets` 禁用，僅私有完整版可查。



## 11. 回測績效指標、R 倍數與每次 Render 部署網址

- 最大回撤（MDD）是收盤資產權益自歷史最高點至後續低點的最大百分比及金額；收盤 K 線不能觀察盤中的真實資產高低。
- **營利因子 PF** = 所有已平倉、扣除分攤進出場費用及資金費後的正淨損益總和 ÷ 負淨損益的絕對值總和。沒有負淨損益時傳回 `null`，不顯示假造的無限大。
- **勝率** = 淨損益大於 0 的平倉筆數 ÷ 全部平倉筆數，打平的平倉仍計入分母。部分減倉會各自計為一筆平倉，不代表完整策略的 round-trip 筆數。
- **平均 R** = 各筆已平倉淨損益 ÷ 該筆平倉部位名義本金 × `r_reference_stop_pct/100`，再取簡單平均。這個參數是可自行填寫的「1R 參考停損距離 (%)」，**僅作為分析分母，不會觸發真實停損**，也不會自動讀取 Pine 裡的 `strategy.exit`。留空時 R 指標傳回 `null`，避免把沒有停損基準的交易錯當成可計算 R。部分平倉分攤既有的進場手續費和資金費。
- 其他指標：淨利、總報酬、年化 CAGR、Sharpe、Sortino、Calmar、交易筆數、淨損益期望值、平均獲利／虧損、盈虧比、連勝／連敗、持倉曝光率與費用。
- **重要**：這些是目前線性單商品 K 線撮合模型的指標，不能取代真實市場中下單、滑價、停損和歷史行情正確性的驗證。

每次推送 `main` 且 `CI / CD` 通過後，GitHub Actions 的
**Render deployment URL** 工作流程會檢查 Render 網站的 `/api/health`，
等它回報的 `deployed_commit` 與此次 GitHub Commit SHA **完全相同**，
才在工作流程 Summary 顯示可點擊的「Open Universal Backtester on Render」連結。
CI 通過不等於 Render 部署完成，因此這是獨立工作流程，不會讓 Render
的 `autoDeployTrigger: checksPass` 出現相互等待。

**必須完成一次設定：** 在 GitHub repository 的 **Settings → Secrets and variables → Actions → Variables**
新增變數 `RENDER_SITE_URL`，填入 Render Dashboard 中實際顯示的
`https://<實際服務名稱>.onrender.com` 網址。此變數是公開網址，
不能填入包含私密 token 的 Deploy Hook；實際服務必須綁定 `main`，
並在 Render 中設定 **After CI Checks Pass** 自動部署。
沒設定時只顯示「Render URL not configured」，不會憑空猜一個網址。
如果 Render 一直沒有部署對應 SHA，工作流程會提示尚未完成並保持失敗狀態，
避免將舊版網址誤報為新版成功部署。

網站在 Render 上執行時，也會在頁首自動顯示目前真實的
`location.origin` 連結，以便複製網址。


## 13. 依需求優先順序 1 → 5 → 3 → 2 → 4 的實作狀態

### 1. 移除 Pine 500 根回看限制（完成初步實作）
- 原生 Pine 相容子集允許 `close[1000]`、`ta.sma(close,1001)`；
  歷史視窗由無複製的 as-of 讀取視圖提供，杜絕未來資料。
- 串流模式會嘗試分析固定長度／`input.int` 週期，維持所需的有限回看緩衝；
  無法推導長度的動態公式明確拒絕串流，改用完整歷史模式。
- 其他 Pine API/AST/檔案大小資源安全限制仍存在；不等同 Pine v6 完整相容。

### 5. 訂單撮合與風險（部分完成）
- Pine `strategy.exit(stop=...,limit=...)` 支援單一淨倉位全數出場。
  收盤送出、**下一根**生效；跳空停損採較差的開盤成交價。
  同根同時觸及停損／停利採停損先發生，作為保守且可重現的 OHLC 假設。
- 交易所原生訂單簿、分段成交、停損限價／追蹤停損、逐倉／全倉保證金、
  不同合約乘數、鏈上 DEX Gas、強平階梯等**仍未實作**，不能宣稱精確撮合。

### 3. 同時工作程序（本機上限移除）
- 刪除硬編碼最多 32 程序；`workers` 可要求大於 32。
- 真正同時啟動量=min(要求值, 主機 CPU 數, `UBT_MAX_LOCAL_WORKERS`, 工作數)；
  其餘待執行工作在程序池佇列中。尚未實作多台主機分散式工作節點。

### 2. SQLite 串流回測（部分完成）
- `POST /api/backtests` 帶 `"streaming":true`；正式版網頁可勾選。
  透過 SQLite cursor 每批讀取原始 K 線，使用增量波動統計與保留極值的
  bounded preview 降低資產曲線記憶體需求，回傳標記
  `"streaming_preview_only":true`。
- 首次下載 CEX/DEX/CSV 仍可能一次在 RAM 累積資料；
  成交與平倉紀錄亦尚未分頁持久化。正式海量歷史處理仍需
  串流抓取寫入、Parquet/Arrow 與原生引擎。

### 4. 跨交易所共同策略（研究型首版）
- 新增 `POST /api/portfolio/backtests`，使用 `venues[]`、
  `portfolio.initial_cash`、`gross_notional_fraction`，
  統一時間戳執行跨交易所價差策略，直接持有兩個市場的多空腿。
- 不同交易所共用模擬資金，按每家手續費和滑價估值；至少兩個市場；
  市場 K 線缺漏即失敗，不補造行情。
- `strategy.type="spread"` 以 `entry_bps`／`exit_bps` 控制價差；
  `strategy.type="python"` 允許可信任主機的 `on_venues(ctx)->dict`
  自訂共同策略，需 `UBT_ALLOW_EXEC=1`。匿名 Render Demo 不開放。
- **未支援**完整 Pine `request.security` 跨市場語法、跨市場真實轉帳、
  各家獨立保證金／鏈上 Gas、訂單簿撮合、幣別匯率正規化。
  所有報告必須視為簡化的研究結果，不能等同可實際套利損益。


## 14. API 安全：預設拒絕匿名存取

**重要安全修正（2026-10-25）：** 正式 API 改為全域 Bearer Token 保護，
不再因為漏設 `UBT_PUBLIC_DEMO` 就自動開放真實資料與排程服務。

- **正式模式**：所有 `/api/*`（只有 `/api/health` 例外）都要求
  `Authorization: Bearer <UBT_API_TOKEN>`。
  若 `UBT_API_TOKEN` 未設定或少於 32 字元，返回 **503（鎖定）**；
  有設定但未提供或錯誤 Token 返回 **401**。
- **公開示範模式**：必須明確設定 `UBT_PUBLIC_DEMO=1`。
  允許匿名 `GET /api/health`、`GET /api/sources` 與
  `POST /api/backtests`，後者**僅支援合成 K 線、有限 Pine 子集**
  並有並行與請求大小資源預算。市場查詢、CSV、本機路徑、其他策略程式、
  多市場批次、跨交易所 Portfolio、已存記錄、排程皆拒絕。
- Swagger UI 的 `/docs`、`/redoc` 和 `/openapi.json` 在 Web 上關閉，
  避免將未授權的管理介面作為公開入口。
- 已將網頁的第三方 CDN JavaScript 移除，K 線圖可改用本機繪圖；
  私有 API Token 只透過請求 Header 傳遞，不儲存在網址或 localStorage。
- Docker Compose 仍只對本機 `127.0.0.1:8000` 開放，且現在要求先在
  專案根目錄建立 **不提交到 Git 的 `.env`**，提供自己生成的
  `UBT_API_TOKEN`。範例生成方式：
  `python -c 'import secrets; print(secrets.token_urlsafe(48))'`。
  私有伺服器須由 TLS 反向代理提供 HTTPS；Render 請透過 Secret Env Vars 配置。
- 若未經隔離的私有 API 暴露到網際網路，即便有 Token 仍不等同完善安全：
  未來應加入使用者身分、細粒度授權、rate limiting、工作佇列配額、
  儲存空間配額及自訂策略的獨立沙盒。**不得在公開多租戶服務上開啟
  `UBT_ALLOW_EXEC=1`**。

