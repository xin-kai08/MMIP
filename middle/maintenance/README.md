# 專案磁碟整理

工具：`maintenance/cleanup.py`，僅使用 Python 標準函式庫及既有工作流程的鎖。所有路徑依程式位置定位至專案，不依賴目前終端路徑。不會重裝環境或修改標籤、圖片、模型。

## 操作命令

從 `F:\project\MMIP\middle` 執行 PowerShell。預設 **dry-run，不刪除檔案**：

```powershell
# 預設保留最新 20 份自動備份及全部特殊命名備份；其餘列入封存計畫。
.\.venv\Scripts\python.exe maintenance\cleanup.py

# 同時檢查已知的可重建快取；查詢程序權限不足時，保留快取並記錄原因。
.\.venv\Scripts\python.exe maintenance\cleanup.py --caches

# 檢查報告後實際封存與清理。
.\.venv\Scripts\python.exe maintenance\cleanup.py --caches --apply

# 本次一次性整理依委託保留 5 份；日後不加 --keep 就是 20 份。
.\.venv\Scripts\python.exe maintenance\cleanup.py --keep 5 --caches --apply

# 安全測試（僅建立並清理合成測試資料）。
.\.venv\Scripts\python.exe -m unittest maintenance.test_cleanup -v
```

每次執行重新統計、重新建立清單；報告位於 `maintenance/reports/cleanup_<UTC時間>_<隨機碼>.json`。報告包含清理前後各資料夾邏輯位元組數、檔數、磁碟可用空間、候選清單、逐檔雜湊、實際刪除及保留原因。dry-run 只會建立報告與暫時取得鎖。

若 Windows 限制程序查詢，需要依系統流程授權該命令；工具不會跳過使用狀態檢查。執行中不強制終止任何服務。請避免同時開啟套件安裝、瀏覽器測試或其他磁碟清理。

## 備份與 ZIP 驗證

- 審圖儲存前的備份機制維持不變，原始備份位置：`dataset_generate/dataset_workflow/backups/`。
- 只挑選檔名完全符合 `labels_YYYYMMDDTHHMMSSffffff.csv` 的自動備份，依檔名時間排序。所有其他名稱的 CSV（例如 `labels_before_original_review_...csv`）保留於原處，不以修改時間猜測用途。
- ZIP 存於 `backups/archives/labels_archive_<UTC時間>_<隨機碼>.zip`；內部直接保留原 CSV 檔名，另有 `MANIFEST.json`（檔名、大小、SHA-256）與 `SHA256SUMS.txt`。
- 先寫唯一 `.partial.zip`，關閉並同步寫入後，讀取全部成員並逐檔計算**解壓內容** SHA-256、核對大小、檔案數及清單一致性。成功才改為最終 `.zip`，再次核對所有原檔 SHA-256 後才依本次明確清單刪除。
- 每次刪除前重新解析絕對路徑，必須位於本專案的備份資料夾，拒絕 symlink/junction。驗證失敗不刪除該批原檔；`.partial.zip` 保留供檢查，不自動當成功封存使用。
- 重跑時先驗證既有最終 ZIP。若上次在驗證後、刪除前中斷，符合檔名及 SHA-256 的殘留 CSV 會使用既有 ZIP，不重複封存或覆寫。若同名 CSV 與封存內容不同，直接停止。
- 封存與清理期間使用既有 `dataset_generate/dataset_workflow/.workflow.lock`，與審圖儲存互斥。已有鎖就停止，絕不自動移除他人鎖；意外中斷時，先確認對應程序確實停止，再依原有工作流程處理殘留鎖。

單獨重新驗證某個 ZIP（請把範例檔名替換成實際名稱）：

```powershell
.\.venv\Scripts\python.exe maintenance\cleanup.py --verify dataset_generate\dataset_workflow\backups\archives\labels_archive_實際檔名.zip
```

## 還原

先用上述 `--verify` 驗證，再將需要的 CSV 解壓到**新建、空白的還原資料夾**，不要直接覆蓋 `dataset/labels.csv`：

```powershell
Expand-Archive -LiteralPath 'dataset_generate\dataset_workflow\backups\archives\labels_archive_實際檔名.zip' -DestinationPath 'maintenance\restore_自行指定的新名稱'
Get-FileHash -Algorithm SHA256 -LiteralPath 'maintenance\restore_自行指定的新名稱\labels_實際時間.csv'
```

比對解壓出的 `SHA256SUMS.txt`／`MANIFEST.json`。若要回復主標籤表，先停止審圖寫入、備份目前主表，確認所需版本後再依原流程還原；解壓本身不會改動現行標籤。

## 快取範圍與保留項目

僅允許以下四個明確目標：`website/.cache/npm`、`website/.cache/uv`、`website/.cache/browser`、根目錄 `.cache/browser`。未知內容不納入。工具核對程序命令、最近 10 分鐘修改時間，以及 Windows 檔案共用限制；正式清理前再次核對清單與 SHA-256，並持有阻止其他讀寫的檔案 handle，才逐檔刪除。發現使用中、內容變更或候選內有 `.db/.sqlite/.sqlite3` 資料庫時，保留該候選並列出原因。清空後保留空目錄，避免遞迴刪除競態。

`website/.cache/ui-test` 有 SQLite 與圖片，**不視為一般可刪快取**。遇到 hardlink 共用檔案的候選資料夾也整個保留，避免碰到與執行中環境共用的 DLL／PYD。Windows 後續拒絕刪除時記錄並跳過，不強制解鎖。不刪除任何服務資料、使用者上傳圖片、資料庫、訓練成果、固定分割、評估、審核紀錄、程式碼、`.git`、`.venv`、`website/.tools`、`node_modules` 或 `dist`。

清除 npm/uv 下載快取不會解除已安裝的套件；日常啟動仍使用現有環境。未來若重裝或升級被清掉的套件版本，可能需要重新下載。

報告中的大小是檔案邏輯長度；NTFS 配置、uv hardlink、背景磁碟寫入會使磁碟可用空間增量不同。請同時參考 `net_logical_bytes_reclaimed` 和 `volume_free_delta_bytes`。工具對保護資料核對前後雜湊，執行環境／工具目錄核對清單、大小與修改時間；使用中而無法讀取的 worker lock 只比較 metadata，報告會明列限制。
