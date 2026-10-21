# 人工標註修正與驗證 — 2026-10-20

## 完成內容

- 一般辨識直接顯示回饋表單。首次「儲存人工回饋」，成功後停用並顯示「已儲存」；只有兩類答案或兩項確認旗標與已儲存內容不同，才啟用「更新人工回饋」。未儲存修改改回原值不送出，儲存中防連點，失敗保留草稿，重新整理恢復已儲存內容。
- 評估模式顯示「預測前答案（已鎖定）」，逐任務列出答案及確認狀態；缺值／未確認明示。結果後回饋預設收合，首次入口「新增修正回饋」，已有回饋則顯示最新摘要及「查看／修改回饋」。開啟表單不複製、確認或提交原 GT。
- API 在既有 SQLite `BEGIN IMMEDIATE` 交易內比較該圖最新 post_feedback 的四個欄位。相同回傳 HTTP 200／`changed=false`，保留原 ID／時間；不同才 HTTP 201／`changed=true` 追加歷史。A→B→A 有效，快速並發相同內容只新增一次。
- 來源保持分離。統計每圖每來源取最新快照，再逐任務檢查確認及合法答案；最新取消確認不回退舊版，不跨來源補值。CSV 保留全部來源、版本 ID、前版 ID、時間及確認旗標。
- 不需資料庫 schema 遷移，沒有清除既有重複歷史或修改正式使用者資料。原 GT 的既有資料庫不可更新 trigger／唯一索引保留；API 不接受將回饋寫入 pre_ground_truth。
- 修正瀏覽器測試發現的時序問題：POST 成功後已收到的版本，後續背景 GET 不得再次重設草稿；較舊回應不覆蓋較新基準。新的遠端版本到達時也保留尚未儲存的草稿。

## 實際驗證結果

| 檢查 | 結果 |
|---|---|
| `python -m unittest website.test_website -v` | 9 項全數通過 |
| 同內容直接 API 重送 | HTTP 200、changed=false，ID／created_at 不變 |
| 並發提交 | 兩波各 12 個請求，每波 1 次新增、11 次 no-op |
| A→B→A、只修改確認旗標 | 各次實際變更新增前版鏈結；無變更不新增 |
| 寫入失敗／重試 | 交易回滾；重試新增一版 |
| 既有重複歷史 | 人工植入測試重複列仍保留，統計每圖每任務最多一次 |
| GT／預測／回饋及 CSV | 原 GT 與預測不變；來源、版本與 BOM 匯出通過 |
| TypeScript＋Vite production build | 通過；已產生新 dist |
| 真實模型 | CUDA 單張 API 與 Predictor 結果一致；瀏覽器使用相同 checkpoint 的 CPU 推論 |
| 無頭 Chrome 操作 | 17 個情境通過，console page errors 0；桌面及手機截圖已檢查 |
| 延遲背景刷新 | 刻意延遲 GET，開始下一次編輯後再放行，草稿仍保留 |
| 測試隔離與關閉 | 新建暫存 DB／上傳／Chrome profile；使用 8002，測試後正常關閉並移除本次暫存資料 |

瀏覽器測試使用兩張評估照片與一張一般辨識照片，不進行整批模型評估。第一張累積 5 個有效回饋版本，統計仍只算該圖一次；原 GT 空白的第二張後來提供回饋，原 GT 仍空白。最後兩任務的有效樣本數均為預測前 GT 1、預測後回饋 3，兩來源互不補值。HTTP 503 故障情境由隔離瀏覽器攔截模擬，只用來驗證表單重試，模型預測來自真實 checkpoint。

測試曾發現背景刷新覆蓋新草稿，修正後重建並通過刻意延遲測試；測試服務也修正 Windows 關閉 socket 的順序，最終重跑正常關閉。缺少模型的 API 測試會刻意記錄一條測試用錯誤，屬於預期的錯誤處理情境。

詳細結果：[feedback_browser.json](verification/feedback_browser.json)。測試截圖：`verification/screenshots/feedback/`。模型 SHA-256 與既有檔案核對一致：`572144ea31c0663c3e952e8f8ebd5fb608cca6772ecb5a9bac298f72b4758805`；`dataset/labels.csv` SHA-256 仍為 `256ccb96ea886fdfe60f8b93d55de0c1cb7dfde9f66cb5d330facad668eeca02`。

## 修改檔案

- `website/app.py`：交易內去重、changed 回應、來源限制。
- `website/frontend/src/main.tsx`、`style.css`：已儲存／變更狀態、唯讀 GT、選填回饋及草稿時序保護。
- `website/test_website.py`：API 回歸與並發、來源統計測試；明確覆蓋測試環境變數以免連到正式 DB。
- `website/verify_feedback.py`、`website/frontend/verify_feedback.mjs`：自動建立、驗證並關閉隔離瀏覽器測試環境。
- `website/frontend/verify_browser.mjs`：既有全流程測試沿用新的展開回饋入口。
- 根 `README.md`、`website/README.md`：操作、API、統計、套用方式與實際驗證更新。

## 套用與重跑

前端已重建，無須重新安裝依賴。現有執行中的後端仍載入舊 Python 程式，請於原終端 Ctrl+C 停止後重新啟動，然後重新整理頁面：

```powershell
cd F:\project\MMIP\middle
.\.venv\Scripts\python.exe -m website.run
```

開啟 `http://127.0.0.1:8000`。不用更換資料庫、重新訓練或重跑歷史推論。

重跑驗證：

```powershell
.\.venv\Scripts\python.exe -m unittest website.test_website -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\frontend.ps1 build
.\.venv\Scripts\python.exe -m website.verify_feedback
```
