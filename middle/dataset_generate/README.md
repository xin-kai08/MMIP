# 垃圾分類圖片整理與生成工作流程

資料根目錄：`../dataset`。主標籤表：`../dataset/labels.csv`（UTF-8 BOM）。工作狀態、報告、聯絡表及生成紀錄集中於本資料夾的 `dataset_workflow/`。程式依自身位置尋找資料，不依賴終端目前目錄。

標籤備份保存在 `dataset_workflow/backups/`，壓縮封存保存在其 `archives/`。每次儲存前仍建立備份；[備份封存、驗證與還原](../maintenance/README.md) 工具沿用審圖鎖，預設保留最新 20 份與全部特殊命名備份，其餘驗證後封存。預設僅 dry-run，不會自動刪除。

```text
middle/
  dataset/
    labels.csv
    glass_beverage_bottles/  ...原圖及生成圖...
    ...其餘物品細類...
  dataset_generate/
    waste_workflow.py        主流程與本機複核服務
    review_ui.html           本機標註介面
    test_waste_workflow.py   合成測試資料的安全／接續測試
    initial_visual_review.py、finalize_pilot_review.py  本次一次性看圖紀錄
    requirements.txt
    dataset_workflow/
      inventory.json、generation_tasks.json、generation_log.jsonl
      reports/、contacts/、pilot_preview/、backups/
    tmpuosza_cb/             先前沙箱測試留下的暫存資料夾，保留未刪
  .venv/                    專案的 Python 環境，留在原位置
```

## Git 版本管理

根目錄 `.gitignore` 已改為細項規則，不再忽略整個 `dataset_generate/`。

- 保留版本管理：Python 程式、測試、README、requirements、review_ui.html、審核 JSON／CSV、生成任務與事件紀錄、資料清單及報告。
- 特殊命名的備份（例如 `labels_before_original_review_...csv`）仍可納入版本管理；只有完全符合自動時間戳命名長度的 `labels_YYYYMMDDTHHMMSSffffff.csv` 與 `backups/archives/` 被忽略。
- 忽略本機／衍生檔：`tmp*/`、Python bytecode、工作鎖、自動備份與 ZIP 封存、contacts、pilot_preview 的 JPG、reviews 下的 sheets 圖像聯絡表。原始圖片與審核 observations、sheets.json、修改明細仍保留原有管理方式；不對整個 reviews 或 reports 做 blanket ignore。

忽略只控制後續 Git 追蹤，不會刪除本機檔案；備份封存仍須另外保存，不能假設 Git clone 會包含被忽略的備份或安裝環境。曾被 Git 追蹤的測試快取／截圖已使用 `git rm --cached` 取消追蹤，本機檔案完整保留；既有提交歷史沒有重寫。

## 執行

從專案根目錄執行（PowerShell）：

```powershell
# 已建立 .venv 並安裝 Pillow。新環境才需要這兩行：
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r dataset_generate\requirements.txt

.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py scan
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py contacts
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py serve
```

開啟 `http://127.0.0.1:8765`。可依細類、來源、狀態、檔名篩選、看來源對照、修改標籤與確認近似圖。按「儲存」才寫入，換圖不會自動儲存。服務只綁定 localhost；Ctrl+C 結束。不要直接以檔案方式開啟 HTML。

```powershell
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py report
.\.venv\Scripts\python.exe dataset_generate\verify_workflow.py
.\.venv\Scripts\python.exe -m unittest discover -s dataset_generate -p test_waste_workflow.py -v
```

## 原圖與標註規則

原圖不刪除、不改名、不改寫。重掃依相對路徑保留既有人工欄位與額外欄位；每次更新標籤前備份。每次重掃重新計算檔案 SHA-256，圖片內容沒變則重用解碼特徵快取。`original_changes.csv` 會列出相對首次掃描內容變動的圖片。遺失檔案記錄於 `missing_files.csv`，從當前 labels 表移出，舊表仍有備份。

`folder` 保留原始頂層物品資料夾名稱；`waste_class` 採本專題指定對照，未驗證地方垃圾處置規則。未知資料夾列在 `unknown_folders.json`，不自行分類。`food_waste` 不等於容器食物殘留。

- `none`：圖片足以確認無殘留，不能用來代替「沒標」。
- `food`／`liquid`：實際看圖可見的容器殘留或飲食內容。食物和液體明顯並存時設 yes、殘留留白，notes 記錄 mixed；完成複核可設 approved，但不進入單一殘留三分類訓練或比例統計。
- 非容器：`residual_applicable=no`，residual 留白。預設吸管、垃圾袋、食物垃圾、杯蓋不適用容器殘留任務；紙箱先 unknown。
- 看不清、內部不可見：`residual_applicable=unknown`，residual 留白。
- 上方內壁可見但杯底不可見的紙杯：可在內壁試作可見液滴；原圖殘留留白，不推定整杯乾淨。
- `pending` 為尚未完成審核。`approved` 只表示圖片審核完成，允許 unknown／no＋空白，也允許備註 mixed 的 yes＋空白；不代表一定適合殘留辨識。`excluded` 是排除樣本，仍留在磁碟與標籤表。本次受委託全量複核只更新五類 original，維持原先 excluded，未改 generated 審核結果。
- `generation_candidate=eligible/exclude/review` 是編輯來源品質判斷，與整張樣本的 review_status 分開。eligible 僅限單一主要容器清楚、確定無殘留（yes＋none），且現有角度能合理呈現新增殘留的 original；實際排入新任務前也必須 approved。其他需記錄內部不可見、多物品、拼貼、材質有歧義或已有內容等原因。reserve 會再次確認來源仍合格，避免使用舊任務中的失效來源。

一次性 `initial_visual_review.py`、`finalize_pilot_review.py` 保存本次看圖證據，有執行防護。後續請使用本機介面，不重跑這些腳本覆蓋人工標註。

可匯入人工修改 JSON（只允許可編輯標籤欄位）：

```powershell
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py annotate path\to\updates.json
```

```json
[{"image_path":"paper_cups/Image_145.png","residual":"","residual_applicable":"yes","review_status":"pending","notes":"杯底不可見，需複核","visual_review_by":"reviewer"}]
```

## 去重與資料切分

完全重複以檔案 SHA-256 或同尺寸解碼 RGBA 像素 SHA-256 確認並合組，不刪圖。近似候選使用 64-bit dHash 距離 ≤6，加長寬比篩選，跨細類搜尋；候選數是配對數，並非圖片數。此法可能漏掉裁切、翻轉、旋轉等近似圖，也會誤報簡單商品照。`low_information` 提示低資訊圖片；必須人工看圖確認，不能把候選直接當重複。

```powershell
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py duplicate "paper_cups/Image_1.png" "paper_cups/Image_2.png" same
# 確認不同用 different；介面也可操作。
```

原圖、所有生成版本、確認重複圖片形成連通群組。原圖 ID 為 `細類:原始相對路徑`；生成圖保留該 source_id。group_id 由群組相對路徑確定性產生，合組後可能更新。固定 seed=42，以群組為單位，盡量維持細類及 approved 殘留分布，目標 70/20/10。分組防洩漏優先。

scan 保留既有合法群組 split；新生成圖繼承來源。確認跨 split 的重複會同步整組並記錄 `split_conflicts_resolved.csv`。完成近似圖確認及標註後，可明確重新切分：

```powershell
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py split
```

這會依目前人工已確認標籤重算所有群組 split。當前切分在近似圖尚未複核前屬暫定，不應直接宣稱已消除所有近似洩漏。

## 生成、接續與數量

2026-10-17 已依使用者確認的試作效果完成保麗龍食物殘留批次擴充，新增 26 張，全部實際看圖初標並保留 pending 待人工驗收。詳見 [批次報告](BALANCE_GENERATION_REPORT.md) 與 [本批對照頁](dataset_workflow/balance_preview/index.html)。原有 22 張試作的人工標籤保留不變。

balance 排程會以來源 group_id 去重，並扣除 queued／running 及已存檔待審的任務，避免中斷接續或重跑時超量生成。人工排除後才依最新平衡數重新規劃；不自動重試失敗任務。

已使用 ChatGPT 內建 imagegen 編輯工具；Python 本身不呼叫付費 API，也不使用貼圖或一般增強冒充生成。每張獨立編輯原圖。提示詞只代表目標，成功存檔不等於標籤驗收。

首輪五類各兩張，存為各自的 Image_251.png、Image_252.png。使用者後續指定「每張殘留更明顯」，修正版另存新編號，不覆寫首輪。修正版提示目標：透明琥珀色液體約 8–12% 容量；紙杯只處理可見內壁；食物約 10–15% 內底面積，保留輪廓、材質、主要表面並避免積液。比例是提示，不是實測保證。

使用者進一步要求紙杯像 Image_30 一樣清楚呈現咖啡液面，已另做 Image_255.png、Image_256.png（coffee-surface-v3），保留杯口下方明顯空間；優先查看這兩張。首輪 10 張＋visible-v2 修正版 10 張＋咖啡液面紙杯 2 張，共 22 張生成檔。對照總覽為 `dataset_workflow/pilot_preview/index.html`。

`generation_tasks.json` 是目前任務狀態的權威紀錄；CSV 為易讀匯出。`generation_log.jsonl` 逐事件記錄來源、hash、提示詞、輸出路徑、嘗試次數與成功／失敗。`status=success` 只表示檔案已保存；品質問題另列 `generated_needs_rework.csv` 及各批 QA 表。原圖及生成圖的所有初標仍需人工確認。

```powershell
# 只建立任務，不自行呼叫生成工具：
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py plan
# 修正版清單固定每類兩個來源；同一 revision 重跑不重建既有任務：
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py plan-revision dataset_generate\dataset_workflow\visible_revision_sources.json --revision visible-v2
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py plan-revision dataset_generate\dataset_workflow\coffee_surface_sources.json --revision coffee-surface-v3 --folders paper_cups --strength coffee-surface

# 從 generation_tasks.json 複製 task_id：
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py reserve TASK_ID
# 用任務提示詞及 source_path 交給影像編輯工具；完成後立即登記工具輸出：
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py complete TASK_ID C:\path\to\generated.png
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py fail TASK_ID "工具失敗原因"
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py recover
```

reserve 挑選 ≥251 且未被檔案或任務佔用的編號；complete 使用 exclusive create，禁止覆寫。成功任務重複 complete 會跳過。copy 前先存輸出 hash，中斷後 recover 可採認已完成 copy 的檔案。running 任務絕不自動重新生成；若工具已輸出，用 complete 登記。若沒有輸出，人工確認後先 fail，再 retry TASK_ID。部分寫入／checksum 不符檔案保留待處理，不覆寫。

若流程異常結束而留下 `.workflow.lock`，先確認沒有工作程序在跑，再移除這個鎖檔。不要在服務儲存時用 Excel 同時修改 labels.csv；Excel 若持有檔案鎖，關閉後重試。

`balance.csv` 只按五種容器各自計算，以 approved、residual_applicable=yes、residual 為 none／food／liquid 且未損壞的圖片為可用；unknown、no、mixed／空白皆不納入。確認重複的原圖每細類每群組計一次，生成版本另計。重複原圖標籤衝突另列 `duplicate_label_conflicts.csv`，衝突群組不列殘留可用清單。

`usable_manifest.csv` 與 `residual_training_manifest.csv` 都只保存可用的殘留三分類樣本；一般垃圾類別分類可用清單另存 `classification_manifest.csv`。`reviewed_residual_unknown.csv` 列出已審核但不適用單一殘留標籤的樣本。這些都是資料清單，本次沒有訓練模型。

補有殘留數 = max(0, 無殘留原圖＋已驗收無殘留生成圖－有殘留原圖－已驗收有殘留生成圖)。若有殘留較多，報告會提示應補 none，而非繼續加殘留。原圖尚有 pending 時 `final_add_residual` 留白，僅列 provisional 差額；不能預設各類都補 250 張。

原圖複核完成且試作品質已確認後，`plan --mode balance` 可依差額建立後續任務。它仍只排任務，不執行 API。來源 eligible 不足時不強行湊數。

## 報告與驗證

`dataset_workflow/reports/` 提供 counts、folder_summary、residual_counts、split_counts、dimensions、balance、pending_review、candidate_exclusions、exact_duplicates、near_duplicates、damaged_images、generation_failures、generated_needs_rework 等 CSV（均為 UTF-8 BOM）。原圖與生成圖分開統計。

`original_near_duplicates.csv` 只列原圖配對；總 near_duplicates 表另外帶有兩側 origin 與 same_known_group 欄位，已知同來源的生成版本不必誤當作新來源。各批品質紀錄是當時初檢的證據；後續人工決定以 labels.csv 為準。

`pilot_preview/` 是來源與生成對照圖；`contacts/` 為全部圖片每頁 48 張聯絡表。這些是縮圖預覽，不改動資料集。

真實殘留測試圖需獨立驗證。approved 原圖殘留 test 數量見 balance.csv 的 real_residual_test；生成圖測試表現不能代表真實照片效能。五類目標容器 original 已完成 2026-10-17 的全量看圖複核；未知殘留仍留空，近似圖去重仍待確認。最新標籤以 dataset/labels.csv 為準；專案各階段工作紀錄見 [README](../README.md)。

本輪全量複核的備份、50 張原尺寸聯絡表、1,250 筆觀察、修改前後值及驗證結果集中於 `dataset_workflow/reviews/original_review_20261017/`，摘要見 [完整複核報告](ORIGINAL_REVIEW_REPORT.md)。`review_originals.py prepare/record/apply` 支援分批記錄、完整覆蓋檢查及基準檔案衝突檢查；已 apply 的紀錄不可再覆蓋。`verify_original_review.py` 可只讀核對圖片、生成圖結果、原備註及群組不變，並更新本輪摘要，不重新切分或生成圖片。

已執行五項回歸測試，驗證標籤保留、BOM、原圖內容不變、去重及可重現切分、編號避撞／禁止覆寫、生成來源繼承、成功接續及可用數量去重。Windows 沙箱的暫存 ACL 可能導致測試無法清理；本次在獲准後於沙箱外通過測試。

本機 HTML、圖片及資料 API 已以 HTTP 檢查。當前工具未提供可連線瀏覽器，尚未完成瀏覽器視覺與點擊驗證。未訓練模型，未建置正式網站。
