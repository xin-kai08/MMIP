# 垃圾分類與容器殘留辨識專題

本專題規劃從圖片資料蒐集開始，經過資料清洗、標註與殘留圖片生成，再進行模型訓練、測試評估，最後建立可使用模型的網站。

這份 README 記錄各階段實際做過的工作，之後隨專題推進持續補充。程式操作細節另外整理在 [資料處理操作說明](dataset_generate/README.md)。

磁碟整理與標籤備份封存請見 [安全清理操作說明](maintenance/README.md)：預設 dry-run、保留最近 20 份自動備份與全部特殊命名備份，舊備份逐檔驗證 ZIP 解壓 SHA-256 後才移除。既有儲存前備份機制保持不變。

[2026-10-20 實際清理報告](maintenance/CLEANUP_REPORT.md)：已封存 2,832 份舊自動備份，保留最新 5 份及特殊備份，專案淨減少約 1.95 GiB；必要資料與環境保留。

## 專題流程與目前階段

資料蒐集 → 資料清洗與標註 → 資料生成 → 模型訓練 → 測試評估 → 網站建置

**目前已完成模型訓練與本機網站第一版**：experiment_v3 的兩階段與正式 test 已完成，網站串接 stage2_best.pt，提供多圖辨識、SQLite 歷史、預測前 Ground Truth／結果後回饋、評估及 CSV。網站上傳資料獨立保存，不修改 dataset、人工標籤、分配、權重或正式測試結果。

| 階段 | 目前狀態 | 已有成果 |
|---|---|---|
| 資料蒐集 | 已有初版資料集 | 10 種物品細類，共 2,500 張原圖 |
| 資料清洗與標註 | v3 驗收完成，近似風險保留 | 1,920 approved、628 excluded、pending 0；固定分組切分 |
| 資料生成 | 48 張均已驗收 approved | 來源、提示詞、品質與版本紀錄 |
| 模型訓練 | 已完成 | stage1 23 epoch、stage2 28 epoch，best／last 保存 |
| 測試評估 | 正式 test 已完成 | 原圖／生成圖分開結果，未用 test 選模 |
| 網站建置 | 本機第一版完成 | React／FastAPI／SQLite、真實模型與人工驗證 |

## 一、資料蒐集

已整理既有垃圾圖片，依物品細類存放於 `dataset/`。實際清點為 10 類、每類 250 張，共 2,500 張原圖；數量由掃描確認。

| 物品細類 | 原圖數量 |
|---|---:|
| cardboard_boxes | 250 |
| food_waste | 250 |
| glass_beverage_bottles | 250 |
| paper_cups | 250 |
| plastic_cup_lids | 250 |
| plastic_food_containers | 250 |
| plastic_straws | 250 |
| plastic_trash_bags | 250 |
| plastic_water_bottles | 250 |
| styrofoam_food_containers | 250 |
| **合計** | **2,500** |

原始資料的下載網址與蒐集方式尚未記錄於本文件，後續取得資訊時再補充。

## 二、資料清洗與標註

已完成以下整理工作：

- **檢查圖片**：遞迴掃描檔案數量、尺寸及解碼狀態。首次檢查的 2,500 張原圖皆為 256×256，未發現損壞圖片或額外未知類別。
- **建立類別對照**：保留原始資料夾名稱 `folder`，另外建立 `waste_class`，對應 general、glass、food_waste、other_recycling。這是專題標籤對照，不代表已驗證地方垃圾處置規則。
- **檢查重複資料**：以檔案及解碼像素 SHA-256 確認完全重複，初次找到 100 組配對，合組後有 2,403 個群組；另找出 803 組原圖近似候選供人工確認，沒有自動刪圖。
- **建立標籤表**：產生 [dataset/labels.csv](dataset/labels.csv)，記錄物品類別、殘留狀態、來源、來源 ID、分組、資料切分及複核備註，使用 UTF-8 with BOM。
- **建立檢查工具**：提供聯絡表、本機圖片複核介面及來源對照，方便人工修改標籤、排除不適合的圖片及確認近似圖。
- **建立分組切分流程**：固定 random seed=42，目標 train／val／test 為 70%／20%／10%；原圖、生成版本及確認重複圖放在同一 group_id，避免跨組洩漏。
- **保護原始資料與人工標籤**：整理流程不刪除、覆寫或重新命名原圖；重掃保留已有人工標註，更新 CSV 前保留備份。

殘留標籤採 `none`、`food`、`liquid`。`none` 必須能從圖片確認無殘留；看不清楚或不適用時留白，再用 `residual_applicable` 區分。`food_waste` 是垃圾類別，不能直接當成容器食物殘留。

2026-10-17 已完成五類容器 1,250 張原圖複核，保存逐張修正且未恢復原 excluded，詳見 [原圖複核報告](dataset_generate/ORIGINAL_REVIEW_REPORT.md)。2026-10-18 全部 pending 已處理，最新 labels 共 approved 1,920、excluded 628，v3 的 readiness=true。去重後 manifest 1,854 張：stage1 636、stage2 661、val 377、test 180。688 張 unknown 的原因資格仍未確認，殘留 loss 保留 mask；820 組未解近似候選仍為資料洩漏風險，不直接合組。這些風險沒有被網站結果取代或掩蓋。

## 三、資料生成

為補充容器殘留樣本，已使用內建影像編輯工具，以原圖為基礎加入液體或食物殘留。生成時盡量保留物品種類、材質、形狀、角度、背景與光線，使殘留清楚可見且不遮擋本體。

| 生成對象 | 殘留類型 | 已生成試作 |
|---|---|---:|
| glass_beverage_bottles | 液體 | 4 張 |
| paper_cups | 液體 | 6 張 |
| plastic_water_bottles | 液體 | 4 張 |
| plastic_food_containers | 食物 | 4 張 |
| styrofoam_food_containers | 食物 | 30 張（含擴充 26 張） |
| **合計** | | **48 張** |

試作過程分為三批：

1. 五類容器各生成 2 張，共 10 張，先檢查編輯效果。
2. 依討論提高殘留的明顯程度，再做五類各 2 張，共 10 張；增加可見液體、米粒與醬痕，同時避免食物殘留出現明顯積液。
3. 紙杯再參考 `Image_30.png` 的咖啡液面，生成 `Image_255.png`、`Image_256.png`，讓液體更容易辨認，並保留杯口下方空間。

生成圖存入對應物品資料夾，從 `Image_251.png` 起避開已存在的編號，不覆寫原圖或舊版本。每次保存來源、提示詞、輸出路徑及狀態，支援中斷後接續。生成圖繼承來源的 group_id 與 split。

已建立 [來源與生成版本對照](dataset_generate/dataset_workflow/pilot_preview/index.html) 及 [生成任務紀錄](dataset_generate/dataset_workflow/generation_tasks.csv)。試作中發現過液面不清楚、原有文字條被改動等問題，已記錄並調整後續來源或生成方式。

2026-10-17 依差額擴充 26 張保麗龍食物殘留圖，2026-10-18 完成驗收後，48 張生成圖均 approved。其他四類當時有殘留資料較多，未繼續新增。生成提示詞不當作驗收標籤；網站上傳圖也不自動加入訓練。

## 四、固定分配、模型與兩階段訓練

已建立 [training/](training/README.md)。使用 ImageNet `EfficientNet_B0_Weights.IMAGENET1K_V1` 預訓練 EfficientNet-B0 features，共用全域平均池化後分接兩個 Dropout＋Linear(1280,4) 頭，移除原 ImageNet classifier。

| 任務 | 固定類別順序 |
|---|---|
| 垃圾 | general、glass、food_waste、other_recycling |
| 殘留 | none、food、liquid、not_assessable |

food_waste 是垃圾類別，food 是殘留。not_assessable 顯示「不適用／無法判斷」；低信心另回傳旗標，不當作訓練標籤。approved＋yes＋none／food／liquid 對應前三類；approved＋no＋空白對應 not_assessable；approved＋unknown＋空白只有在 [資格補充清單](training/residual_eligibility.csv) 有明確原因、確認者及證據時才轉換。不從模糊備註猜測。未確認、mixed 或衝突用 mask 跳過殘留 loss，可只參與垃圾分類。原 CSV 的 no／unknown 不變，excluded／pending 不進訓練，生成提示詞不當作標籤。

固定 seed=42，沿用 train／val／test **70%／20%／10%**，再把 train 的完整 group 固定分成 stage1／stage2，盡量各半。分配兼顧物品細類、兩任務類別及 original／generated；來源、生成版本及確認重複圖片不能跨 split 或 stage，val／test 不分配階段。群組完整性優先，不搬圖片、不重抽挑結果。分配與 manifest 存版本及 SHA-256；修改標籤後建立新 manifest，沿用 partition。近似候選只列未解風險，不直接合組。

硬體起始設定：GTX 1650 4 GB、約 16 GB RAM；224×224、batch size 8（可設 4／16）、num_workers 0（可設 2）、骨幹 LR 1e-5、當階段頭 LR 1e-4。按需讀圖，整圖等比例縮放加白邊，訓練增強溫和，避免裁掉開口或瓶底；val／test 固定處理。AMP 預設關閉，開啟前須通過對應 GPU 與數值驗證。這些是可調起始值，未宣稱最佳。

1. stage1 更新骨幹＋垃圾頭，殘留頭凍結；依真實原圖 val 的垃圾 Macro-F1 選 stage1_best。
2. stage2 載入已完成模型選擇的 stage1_best，建立新 optimizer／scheduler；只更新骨幹＋殘留頭，垃圾頭凍結，只用殘留 loss。依真實原圖 val 的殘留 Macro-F1 選 stage2_best。
3. 每階段最多 **30 epoch**，early stopping **patience=5**。每 epoch 記錄 loss、兩頭驗證指標、耗時、LR、顯存及第二階段垃圾 Macro-F1 相對 stage1 的下降百分點。
4. best／last 使用獨立 stage 前綴，第二階段不覆蓋第一階段。checkpoint 保存完整模型、optimizer、scheduler、AMP scaler、epoch、最佳指標、設定、類別、seed、切分版本及 RNG；last 支援完整 epoch 接續。

第二階段骨幹繼續改變，仍可能發生災難性遺忘；凍結垃圾頭或保存 checkpoint 都不能防止遺忘。本次不加入垃圾 loss、蒸餾或回放。

2026-10-18 的 experiment_v3 已完成：stage1 在 23 epoch early stop，最佳為 epoch 18；stage2 在 28 epoch early stop，最佳為 epoch 23。權重及歷史位於 [experiment_v3](training/runs/experiment_v3/)，網站使用 stage2_best.pt，SHA-256 為 `572144ea31c0663c3e952e8f8ebd5fb608cca6772ecb5a9bac298f72b4758805`。本次網站開發只讀模型，不重新訓練。

[訓練操作說明](training/README.md) 保留分階段、接續與重現命令；[2026-10-17 執行紀錄](training/RUN_REPORT.md) 是當時尚未驗收的歷史報告，不改寫為當日已訓練。現況以 v3、completed checkpoint 與 final_test 產物為準。不要為了試網站而重跑已完成的訓練或正式 test。

## 五、正式測試與網站實測

模型選擇只用 val；兩階段完成後才固定比較兩個 best，正式 test 不用來挑 epoch 或決定重訓。原圖／生成圖分開統計，真實原圖為主要結果：

| checkpoint／任務 | 真實原圖有效張數 | Accuracy | Macro-F1 |
|---|---:|---:|---:|
| stage1_best／垃圾 | 176 | 94.89% | 94.02% |
| stage2_best／垃圾 | 176 | 93.18% | 91.57% |
| stage2_best／殘留 | 108 | 87.04% | 82.11% |

垃圾 Macro-F1 從 stage1 到 stage2 下降約 **2.45 百分點**，顯示共用骨幹仍有遺忘。原始結果、各類 support、混淆矩陣及逐圖預測見 [正式比較](training/runs/experiment_v3/final_test/comparison.json)；本次沒有重新執行模型測試。stage1 殘留頭未訓練，不把它的輸出視為已學會殘留。

網站另計上傳資料的實測結果，預設使用辨識前 Ground Truth；辨識後回饋另外分流，模型版本依 checkpoint hash 分開。沒有有效標註時顯示「尚無可評估資料」，信心不是正確率。網站結果不覆寫正式 test，也不能抹除近似候選尚未確認的限制。

## 六、本機網站：循物

已完成 React＋Vite＋TypeScript 前端、FastAPI 後端、SQLite、獨立 uploads/images/ 與單一模型推論佇列。以 ID 查詢歷史，支援一次多圖、縮圖、真實進度、雙頭結果、人工確認、歷史分頁、刪單圖／整批、統計及 UTF-8 BOM CSV。每張照片一個主要物品；預設 JPEG／PNG／WebP、每批 20 張、每張 8 MiB／16 MP，實際解碼檢查。

ID 僅限 ASCII 英文字母／數字 4～20 字元，大小寫合併為小寫。新 ID 填暱稱，已有 ID 進歷史；暱稱可重複。**知道相同 ID 的人可查看及修改該 ID 資料，這不是安全登入或私人帳戶。** 沒有密碼、驗證碼、第三方登入、XAI 或 threshold 調整。

一般辨識：先顯示模型結果，再存 post_feedback。實驗評估：辨識前獨立填兩項 Ground Truth（可尚未確認），先固定保存再推論，後續修正另留紀錄。預測、預測前標註與結果後回饋不互相覆蓋；人工未確認或低信心不能當成 not_assessable。

**日常啟動不需要重新下載或 npm install：**

```powershell
cd F:\project\MMIP\middle
.\.venv\Scripts\python.exe -m website.run
```

瀏覽器開啟 **http://127.0.0.1:8000**。同一個 FastAPI 程序提供前端與 API，啟動載入一次模型，單一 worker 逐張推論；不要開多個 GPU workers。Ctrl+C 停止。

第一次安裝／前端修改後才需要：

```powershell
uv pip install --cache-dir website\.cache\uv --python .venv\Scripts\python.exe -r website\requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\bootstrap_node.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\frontend.ps1 install
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\frontend.ps1 build
```

Python 套件在 F 槽 .venv，Node 在 website/.tools，node_modules 與下載快取也在 F 槽。保留環境及 dist，往後直接啟動 Python 即可。前端開發另執行 frontend.ps1 dev，使用 5173 與 Vite proxy。設定集中於 website/config.json，可設模型、裝置、API、埠號及限制。

SQLite 在 website/data/app.sqlite3，上傳圖片在 uploads/images/，不混入 dataset；DB、圖片、執行暫存與套件快取均 gitignore。資料庫 v1 保存關聯與標註修訂，重啟可恢復中斷排程；刪除需確認且不可刪處理中資料，檔案清理可追蹤。停止服務後可用 `python -m website.backup` 備份 SQLite 與其引用圖片。

網站 API 測試含真實 checkpoint E2E；TypeScript／production build 及獨立無頭 Chrome 的桌面／手機畫面與流程已驗證。詳見 [完整網站操作說明](website/README.md) 與 [瀏覽器驗證](website/verification/browser.json)。現有 review_ui.html 仍是資料標註工具，與新辨識網站分開。

## 階段工作紀錄

| 日期 | 階段 | 工作紀錄 |
|---|---|---|
| 2026-10-15 | 資料清洗 | 完成既有 2,500 張原圖的首次掃描、重複檢查、初版標籤表、聯絡表及本機複核工具 |
| 2026-10-15 | 資料生成 | 完成首輪 10 張、殘留更明顯的 10 張及咖啡液面紙杯 2 張，共 22 張試作，保存來源與生成紀錄 |
| 2026-10-15 | 工具驗證與整理 | 完成回歸測試與資料驗證；程式與工作資料集中至 dataset_generate，標籤放入 dataset |
| 2026-10-17 | 資料清洗與標註 | 備份標籤後完成五類容器共 1,250 張原圖的全量看圖複核，保存逐張修正明細；允許 approved＋unknown／mixed 留白，並將其排除於殘留訓練與比例統計；8 項回歸測試通過。本輪未新增生成圖、未修改生成圖審核結果 |

| 2026-10-17 | 生成擴充 | 完成 26 張保麗龍食品容器殘留擴充，初標後保留 pending 待人工驗收 |
| 2026-10-17 | 模型流程 | 固定 70／20／10 與 train 兩批分配、雙頭模型、兩階段訓練、early stopping、checkpoint 接續、評估及推論程式；正式訓練仍受資料驗收及缺類阻礙 |

| 2026-10-18 | 訓練完成 | v3 驗收與兩階段完成，stage1 23／stage2 28 epoch；完成鎖定正式 test 比較 |
| 2026-10-20 | 網站第一版 | React／FastAPI／SQLite、真實模型、多圖、ID-only 歷史、盲測 GT／回饋分流、評估、CSV 及刪除；依賴與快取安裝在 F 槽 |

## 專案檔案與操作入口

```text
middle/
├─ README.md                    專題流程與階段工作紀錄
├─ dataset/
│  ├─ labels.csv                主標籤表
│  └─ 各物品細類/              原圖與對應生成圖
├─ dataset_generate/
│  ├─ README.md                 資料處理操作說明
│  ├─ waste_workflow.py         掃描、複核、去重、切分及生成接續
│  ├─ review_ui.html            本機圖片複核介面
│  ├─ RUN_REPORT.md             首次整理與生成報告
│  └─ dataset_workflow/         統計、聯絡表、對照圖、任務及備份
├─ training/                   固定 manifest、模型、訓練、評估、推論與報告
├─ website/                    前後端、SQLite、設定、測試與操作說明
├─ uploads/images/             網站上傳圖片，獨立於 dataset
└─ .venv/                      Python 執行環境
```

從專案根目錄啟動本機複核工具：

```powershell
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py serve
```

開啟 `http://127.0.0.1:8765`。安裝、重新掃描、更新統計與接續生成等詳細指令，請見 [操作說明](dataset_generate/README.md)。

- [本機網站操作與備份](website/README.md)
- [兩階段訓練與推論操作](training/README.md)
- [實際驗證及尚未完成事項](training/RUN_REPORT.md)
- [首次資料整理與生成報告](dataset_generate/RUN_REPORT.md)
- [保麗龍食物殘留批次生成紀錄（2026-10-17）](dataset_generate/BALANCE_GENERATION_REPORT.md)：2026-10-17 的歷史生成報告；後續已驗收並完成 v3 訓練。
- [來源與生成圖片對照](dataset_generate/dataset_workflow/pilot_preview/index.html)
- [各類別與標籤統計](dataset_generate/dataset_workflow/reports/counts.csv)
- [原圖近似重複候選](dataset_generate/dataset_workflow/reports/original_near_duplicates.csv)
- [五類容器的可用數量與補圖差額](dataset_generate/dataset_workflow/reports/balance.csv)

標籤及數量報告留在資料處理檔案中管理；本 README 主要記錄專題各階段做了什麼、產出了什麼，以及目前進行到哪個階段。
