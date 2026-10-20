# 磁碟整理實際結果 — 2026-10-20

已執行封存與安全清理，不重裝環境、不更動模型或人工標籤。下表為本次首次統計與清理後統計的檔案邏輯大小（MiB = 1,048,576 bytes）。子資料夾列已包含在其父資料夾，不可相加重複計算。

| 項目 | 整理前 MiB | 整理後 MiB |
|---|---:|---:|
| .venv | 4501.18 | 4501.18 |
| dataset | 209.77 | 209.77 |
| dataset_generate | 2158.99 | 327.85 |
| 其中 backups（含封存 ZIP） | 2053.08 | 221.94 |
| training | 385.14 | 385.14 |
| website | 415.56 | 241.04 |
| 其中 website/.cache | 211.91 | 37.39 |
| 根目錄 .cache | 14.72 | 14.72 |
| website/.tools | 125.44 | 125.44 |
| website/frontend/node_modules | 76.83 | 76.83 |
| website/frontend/dist | 0.25 | 0.25 |

專案總大小：**8,058,858,368 → 5,969,131,772 bytes（7.5054 → 5.5592 GiB）**。本次淨減少 **2,089,726,596 bytes，約 1.95 GiB**，已包含此次新增的約 12.7 MiB 詳細稽核報告。此為產生本摘要前的量測快照，後續寫入本摘要等小檔案會有少量差異。

F 槽可用空間在正式處理前後增加 **2,104,999,936 bytes，約 1.96 GiB**。這是整個磁碟的觀測差值，會受背景寫入、NTFS 配置與 hardlink 影響，不將它宣稱為完全隔離的精確歸因。

## 備份封存

- 原處 2,838 份 CSV → **6 份 CSV**：最新 **5** 份自動備份，以及 **1** 份特殊命名重要備份。
- 已封存並移除 **2,832** 份舊自動 CSV，原檔合計 **2,146,639,166 bytes**。其餘原處 CSV 共 **6,166,091 bytes**。
- ZIP：[labels_archive_20261020T032648671829Z_4c3f177f.zip](../dataset_generate/dataset_workflow/backups/archives/labels_archive_20261020T032648671829Z_4c3f177f.zip)，**226,557,046 bytes**。
- ZIP SHA-256：`dcad7c91000d8d19aeceb8d8b3497426a68267c16388e927156462c93e3fdf99`。
- ZIP 內有 2,832 份原檔名 CSV、`MANIFEST.json` 與 `SHA256SUMS.txt`，共 **2,834** 個成員；成員名稱無重複、數量與清單一致。
- **全部 2,832 份解壓內容的 SHA-256／大小驗證通過**，刪除前也重新核對全部來源 CSV 雜湊；刪除後再使用獨立 `--verify` 命令驗證 ZIP，同樣通過。
- 重跑實際 `--apply` 後，新增封存 **0**、新增刪除備份 **0**，最終 ZIP 仍只有 **1** 份，未覆寫或重複封存。

保留的自動備份：

```text
labels_20261018T122701249006.csv
labels_20261018T122707772062.csv
labels_20261018T122711377511.csv
labels_20261018T122715930540.csv
labels_20261018T122723848834.csv
```

重要備份完整保留：`labels_before_original_review_2026-10-17T073615.995464_0000.csv`。

## 快取與未處理項目

已移除 **700** 個確認候選中的快取檔，合計 **182,990,583 bytes**：npm 410 個（全部 180,155,677 bytes）及 uv 290 個（2,834,906 bytes）。

uv 清理遇到 Windows 拒絕刪除與執行環境共用的 `_pydantic_core...pyd` 時停止，未強制解鎖。已補上 hardlink 預防檢查、加入安全測試並重跑完成核對。首次操作的部分成功／錯誤紀錄保留在詳細 JSON，沒有改寫成首次全部成功。

以下完整保留，不強制終止任何服務：

| 未清理位置 | 目前 bytes | 原因 |
|---|---:|---|
| website/.cache/uv 剩餘 368 檔 | 20,601,401 | 含 hardlink 共用檔案，可能連到執行中環境 |
| website/.cache/browser | 17,054,640 | 瀏覽器測試 profile 內有資料庫，整個保留 |
| .cache/browser | 15,429,957 | 瀏覽器測試 profile 內有資料庫，整個保留 |
| website/.cache/ui-test | 1,553,359 | 測試服務仍在運行，含 SQLite 與圖片，不當一般快取刪除 |

網站 8000 與測試服務 8001 的 health 均為 `status=ok`、`model_ready=true`。沒有移除網站執行必要檔案；沒有更動 `.venv`、工具、node_modules、dist、資料圖片與目前 labels、訓練產物、上傳圖片、資料庫、`.git`。

## 核對與交付

- 7 項合成資料安全測試通過：封存與保留、驗證失敗不刪、內容損壞偵測、路徑限制、中斷後重跑、活躍 handle、共用審圖鎖及 hardlink 保留（部分情境同一項測試涵蓋）。
- 共 **23,295** 筆受保護檔案紀錄，首次清理前至重跑前、重跑前至完成後均 **0 項變更**。科學資料／模型／網站資料以 SHA-256 核對；環境／工具／套件以檔案清單、大小與 mtime 核對。兩個使用中 worker lock 無法讀取，保留並只比對 metadata，不宣稱驗證其內容雜湊。
- 測試在受限沙箱遇到暫存目錄權限問題後，依正常流程授權重跑；7 項全數通過。6 個失敗測試留下的空目錄經明確列單、驗證絕對路徑及空白後移除，清單保留於報告。
- 新工具：[cleanup.py](cleanup.py)、[test_cleanup.py](test_cleanup.py)。操作、還原及日後保留 20 份規則：[README.md](README.md)。根 README、資料整理與網站 README 均已連結操作說明。
- 詳細機器可讀核對：[final_verification.json](reports/final_verification.json)。各次逐檔清單與狀態：`maintenance/reports/cleanup_*.json`。

日後使用（預設 dry-run、保留 20 份＋全部特殊命名備份）：

```powershell
.\.venv\Scripts\python.exe maintenance\cleanup.py --caches
.\.venv\Scripts\python.exe maintenance\cleanup.py --caches --apply
```

審圖每次儲存前的原有備份機制維持不變；清理沿用 `.workflow.lock`，遇到他人鎖就停止。
