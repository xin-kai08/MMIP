# 循物：本機垃圾與殘留辨識網站

第一版已串接 React＋Vite＋TypeScript、FastAPI、SQLite 與既有 experiment_v3/stage2_best.pt。使用繁體中文，支援多圖辨識、辨識前 Ground Truth、辨識後人工回饋、歷史、分來源／模型版本統計及 CSV 匯出。沒有重新訓練、改資料集標籤或覆寫正式 test。

## 日常啟動：不用重新下載

從專案根目錄執行：

```powershell
cd F:\project\MMIP\middle
.\.venv\Scripts\python.exe -m website.run
```

瀏覽器開啟 **http://127.0.0.1:8000**。後端提供已建置的前端，日常只需啟動這個程序；不需要再 npm install、啟動 Vite 或重新下載 Node。看到「模型已就緒」即可上傳。Ctrl+C 停止。

請使用單一後端程序／worker，不加 `--workers 2`、不開多個 GPU 服務。資料庫的 OS worker lock 會拒絕同資料庫的第二個服務；每張圖片由同一條模型執行緒依序推論，HTTP 查詢不被 GPU 推論長時間阻塞。

## 安裝與前端開發

本次新增安裝與下載快取均在 F 槽：

- Python 套件：`F:\project\MMIP\middle\.venv\Lib\site-packages`
- 可攜 Node 22.14.0：`website/.tools/node-v22.14.0-win-x64/`，不做全系統安裝、不改系統 PATH。
- 前端套件：`website/frontend/node_modules/`
- 下載快取：`website/.cache/uv/`、`website/.cache/npm/`
- 前端建置：`website/frontend/dist/`

只要保留這些檔案，之後不需重新下載。換電腦、刪除環境或更新版本才需要重裝；移動路徑時建議重建 Python venv。Node 與 npm 的 wrapper 會使用專案內相對路徑。

以下是**首次安裝／遺失依賴時**的命令，會連網，依系統權限流程授權：

```powershell
uv pip install --cache-dir website\.cache\uv --python .venv\Scripts\python.exe -r website\requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\bootstrap_node.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\frontend.ps1 install
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\frontend.ps1 build
```

Node 從官方網站下載可攜 ZIP，對照官方 SHASUMS256.txt 後解壓。npm install 使用 package-lock.json；wrapper 的 install 實際執行 `npm ci`，套件與快取仍在 F 槽。`.venv` 若尚未建立，先依 [訓練環境說明](../training/README.md) 安裝相容 Torch／TorchVision，不需下載新的模型。

改前端時，在兩個 PowerShell 終端分別執行：

```powershell
# 終端 1：API 與模型
.\.venv\Scripts\python.exe -m website.run
# 終端 2：Vite 開發頁 http://127.0.0.1:5173
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\frontend.ps1 dev
```

Vite proxy 將 `/api` 送到本機 8000。修改完成後重新 build，回到 8000 使用正式前端。預設 API、埠號及限制集中於 `website/config.json`；改共用設定後應重新 build，避免舊前端設定不一致。[Vite 官方環境需求](https://vite.dev/guide/) 與 [FastAPI 上傳文件](https://fastapi.tiangolo.com/tutorial/request-files/) 為實作依據。

## 使用方式與 ID-only 限制

ID 必填，只接受 ASCII 英文字母／數字 4～20 字元，不能有空格或符號；前後端皆驗證，儲存為小寫。已有 ID 直接進入其歷史，新 ID 填暱稱後建立。暱稱可重複，只作顯示；歷史始終依 canonical ID 查詢。可切換 ID，瀏覽器 localStorage 記住上次 ID。

**ID 是紀錄識別碼，不是安全登入。知道同一 ID 的人可以查看、標註、匯出及刪除該 ID 的紀錄。** 沒有密碼、驗證碼、第三方登入或私人帳戶保護。預設只綁定 127.0.0.1，不應直接當成公開服務或存放私密圖片。

上傳支援選取多張、拖曳、縮圖與移除。每張一個主要物品；每批最多 20 張，每張 8 MiB、16,000,000 pixels，只接受實際解碼為 JPEG／PNG／WebP 的單幀圖片。不是只看副檔名。檔案與結果會保存於本機，不自動加入訓練資料。

### 一般辨識

上傳後直接推論，顯示垃圾與殘留兩項類別、各自信心與獨立低信心提示。之後逐張選擇人工答案、確認並儲存，來源固定為 `post_feedback`。這是結果顯示後的回饋，不當作獨立或盲測 Ground Truth。

### 實驗評估

每張圖在辨識前填垃圾與殘留 Ground Truth，兩項各自預設「尚未確認」，不預選模型答案。提交前不推論／不顯示預測；標註先寫入 DB，再讓 worker 執行。來源為 `pre_ground_truth`，即使空白也固定保存，後續不能把它改寫成模型答案。送出後的修正另存 post_feedback 修訂紀錄。

人工尚未確認不是 not_assessable；低信心也不是 not_assessable。food_waste（廚餘垃圾）與 food（食物殘留）是不同任務。

## 模型、信心與設定

預設使用 `training/runs/experiment_v3/stage2_best.pt`；讀取 checkpoint 類別 metadata，重用 `training.engine.Predictor`，保留訓練的等比例縮放、白色補邊、224×224 與 ImageNet 正規化。啟動載入一次、eval、inference_mode，同一次 forward 取得兩個頭。

| 任務 | 實際 checkpoint 類別順序與顯示 |
|---|---|
| 垃圾 | general 一般垃圾／glass 玻璃／food_waste 廚餘／other_recycling 其他回收 |
| 殘留 | none 無殘留／food 食物殘留／liquid 液體殘留／not_assessable 不適用／無法判斷 |

信心門檻沿用 Predictor 的 **0.6**，低於門檻只顯示提示，不改寫類別。沒有提供門檻調整 UI 或 API。**模型信心不是正確率。** 模型版本保存 checkpoint 檔名＋完整 SHA-256，載入前後核對檔案未變，不依檔名猜版本。

`website/config.json` 設定 host／port／dev_port、model_path、device、database、uploads、上傳限制；`WASTE_MODEL_PATH`、`WASTE_DEVICE`、`WASTE_DATABASE`、`WASTE_UPLOADS` 可覆蓋對應值，例如：

```powershell
$env:WASTE_DEVICE='cpu'
.\.venv\Scripts\python.exe -m website.run
```

模型／CUDA 不可用時 health 明確回報，禁止新推論，不自動產生假結果或默默換模型。改模型或裝置後重新啟動；不改寫已保存的舊預測。

## 資料流程與儲存

```text
ID＋模式＋圖片＋預先標註
  → 驗證請求、建立 batch／逐圖紀錄
  → 實際解碼、像素／大小檢查，UUID 檔名保存
  → SQLite queued
  → 單一模型 thread：processing → completed 或 failed
  → 保存雙頭預測、機率、信心、旗標、模型 hash、處理時間
  → 前端依 batch／image ID 輪詢真實狀態
  → 人工確認追加 revisions → 歷史、統計、CSV
```

| 位置 | 內容 |
|---|---|
| `website/data/app.sqlite3` | users、batches、images、predictions、annotations、file_gc、schema_versions |
| `uploads/images/` | 原始上傳 bytes，UUID.jpg／png／webp，不使用 ID、暱稱或原檔名組路徑 |
| `website/data/request-temp/` | 上傳 multipart 的本機磁碟暫存，關閉 request 時清理 |
| `website/frontend/` | React／Vite／TypeScript 與 package lock |
| `website/verification/` | 測試結果與畫面檢查；截圖不提交 git |

SQLite 啟用 foreign_keys、WAL，版本 v1 同時保存 PRAGMA user_version 與 schema_versions；遇到未知 schema 版本拒絕啟動，不重建覆蓋 DB。每個操作獨立連線、參數化 SQL；預測與人工標註分表，不互相覆蓋。annotations append-only，pre GT 有唯一索引與禁止 UPDATE trigger；post_feedback 保留 previous_id、annotator_id 與 server timestamp。

一般模式沒有預測前 GT。一般／評估模式的 post_feedback 都保留修改紀錄；統計採最新一筆 feedback，匯出包含所有版本。批次以 user＋request_key 保證送出重試不建立重複紀錄，同 key 不同內容會 409。

一張無效圖片保留 failed 原因，不影響其他圖片；失敗但有有效檔案的推論可重試，解碼失敗需重新上傳。重啟時 processing 改回 queued，已完成的不重跑；worker 開機只清理自有 UUID 孤兒檔，遺失的已引用檔案改為 failed。

處理中／排隊中的圖片不可刪除（409），等待結果後再操作；整批中有任何處理中圖片也不可刪。使用者確認後才刪除，DB 關聯 cascade 清理，待刪檔寫 file_gc，提交後清檔，失敗則保留清理紀錄供 worker／重啟重試。上傳驗證或 DB 寫入失敗會回滾與清除本次新檔；崩潰遺留檔於下次啟動核對。

圖片只透過 image ID 與對應 ID 的 API 取得；無任意本機路徑讀取入口。上述 ID 查詢範圍不是身分驗證，知道 ID 仍可冒用。

## 歷史、統計與 CSV

歷史按 ID 分頁查詢，可查看單批明細、重新整理恢復狀態、逐圖或整批刪除。CSV 可依全部 ID 紀錄或指定批次匯出，UTF-8 BOM，包含預測／人工答案／來源／確認旗標／時間／模型版本及所有修訂。使用者可輸入欄位會防護 `= + - @` 等 Excel 公式注入，避免開啟 CSV 時被當成公式。

統計預設 pre_ground_truth，post_feedback 必須另選，不混合兩種來源。只計 completed 且該任務有有效、confirmed 人工答案的紀錄。不同 checkpoint SHA 分開顯示；兩任務各有有效／未確認數、accuracy、Macro-F1、各類 precision／recall／F1／support 與混淆矩陣。沒有有效標註時回傳 null、顯示「尚無可評估資料」，不是 0%。

這是網站上傳資料的實測，與 `training/runs/experiment_v3/final_test/` 完全分開；不重新跑正式 test、不把上傳圖加入 dataset。

## API

所有路徑以 config 的 `/api` 為前綴。紀錄 API 帶 `user_id`，僅用作 ID 篩選，沒有 token 或安全登入。

| 方法／路徑 | 功能 |
|---|---|
| GET `/health` | 模型 ready／error、版本、metadata、固定門檻與上傳限制 |
| GET `/users/{id}` | 正規化、查詢 ID 是否存在 |
| POST `/users` | 建立 ID＋暱稱，已存在 409 |
| POST `/batches` | multipart：metadata JSON＋多個 files |
| GET `/batches?user_id=...&page=1&page_size=10` | 分頁歷史 |
| GET `/batches/{id}?user_id=...` | 實際進度、結果與標註歷史 |
| POST `/images/{id}/annotations?user_id=...` | 新增結果後回饋，不能更新 pre GT |
| POST `/images/{id}/retry?user_id=...` | 重試可重試的 failed 圖片 |
| GET `/images/{id}/file?user_id=...` | 取得圖片 |
| DELETE `/images/{id}?user_id=...&confirm=true` | 確認後刪單圖 |
| DELETE `/batches/{id}?user_id=...&confirm=true` | 確認後刪整批 |
| GET `/stats?user_id=...&source=pre_ground_truth` | 分模型版本統計，可加 batch_id |
| GET `/export.csv?user_id=...` | 全部或加 batch_id 匯出 |
| GET `/openapi.json` | 實際 API schema |

metadata 包含 user_id、mode（general／evaluation）、UUID request_key 與 annotations。每個 annotation 為 waste／residual（合法 enum 或 null）、waste_confirmed／residual_confirmed。evaluation 的 annotations 長度必須等於圖片張數；general 必須為空。所有批次及圖片狀態為 queued／processing／completed／failed，混合成功與失敗的批次會顯示完成與失敗張數，不假造時間進度。

## 備份與還原

先 Ctrl+C 停止後端，讓圖片與 DB 處於一致狀態，再執行：

```powershell
.\.venv\Scripts\python.exe -m website.backup
```

預設寫入 `website/data/backups/<UTC時間>/`，使用 SQLite backup API 保存 app.sqlite3，再複製 DB 引用的 images 與 config；伺服器未停止時會拒絕備份。可用 `--output F:\你的備份資料夾\backup1` 指定新目錄。

還原時保持服務停止：將備份 DB 複製至 config 指定資料庫路徑，備份 images 內容複製至 uploads 目錄，確認 config 對應原模型，再啟動。已有資料時先另做備份，不把新舊 DB／圖片混搭。不要在服務執行中直接只複製 SQLite 主檔而漏掉 WAL。

## 驗證與已知限制

- API 6 項測試含真實 CUDA checkpoint E2E、ID、混合成功／失敗、idempotency、重啟接續、人工答案不覆蓋預測、來源分流、CSV BOM／公式防護與刪除一致性。
- React TypeScript 編譯及 Vite production build 通過，FastAPI 實際提供 dist。
- 獨立無頭 Chrome 操作通過：ID 建立、多圖、提交前無預測、雙頭結果、人工回饋、重新整理與歷史、分來源統計、CSV 下載、混合結果、刪單圖／整批及手機畫面。沒有操作使用者既有 Chrome 分頁。
- 瀏覽器測試使用隔離的 8001、`.cache/ui-test/` DB／圖片；正式 8000 保持乾淨。UI 測試使用兩張既有照片作為探針，不做大量資料集評估。相關輸出見 [驗證紀錄](verification/browser.json)。
- 既有模型仍有未解近似候選等資料風險；信心未校準，網站不保證當地垃圾處置正確。人工驗證也不是對填答者身分的驗證。
- 尚未實作登入、公開部署、XAI、門檻調整、資料回訓或模型自動更新，符合第一版範圍。

測試命令：

```powershell
.\.venv\Scripts\python.exe -m unittest website.test_website -v
# 無頭瀏覽器測試需先於 8001 啟動獨立測試服務，見 verification/browser.json 記錄
```

後端只讀既有 [訓練／推論程式](../training/README.md)，根 [README](../README.md) 記錄最新專題進度；舊日期訓練報告保留原文。
