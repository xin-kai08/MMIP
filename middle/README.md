# 垃圾分類與容器殘留辨識專題

本專題規劃從圖片資料蒐集開始，經過資料清洗、標註與殘留圖片生成，再進行模型訓練、測試評估，最後建立可使用模型的網站。

這份 README 記錄各階段實際做過的工作，之後隨專題推進持續補充。程式操作細節另外整理在 [資料處理操作說明](dataset_generate/README.md)。

## 專題流程與目前階段

資料蒐集 → 資料清洗與標註 → 資料生成 → 模型訓練 → 測試評估 → 網站建置

**目前進行到資料驗收與訓練流程建立階段**：已有 2,500 張原圖及 48 張生成圖，完成固定資料分配、EfficientNet-B0 雙頭、兩階段訓練、評估與推論程式。資料仍有未驗收及必要缺類，正式訓練尚未開始；實際 GPU 驗證結果見 [訓練執行紀錄](training/RUN_REPORT.md)。

| 階段 | 目前狀態 | 已有成果 |
|---|---|---|
| 資料蒐集 | 已有初版資料集 | 10 種物品細類，共 2,500 張原圖 |
| 資料清洗與標註 | 進行中 | 圖片掃描、重複檢查、標籤表、人工複核介面及初步分組切分 |
| 資料生成 | 完成試作及保麗龍擴充，待驗收 | 48 張及來源／品質紀錄 |
| 模型訓練 | 程式已建立，正式訓練尚未開始 | 固定分配、雙頭模型、兩階段訓練與接續 |
| 測試評估 | 模型評估尚未開始 | 已驗證資料處理工具；尚無模型測試結果 |
| 網站建置 | 尚未開始 | 待模型及推論方式確認後設計與整合 |

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

**此階段仍在進行**：2026-10-17 已受委託看完五類目標容器的 1,250 張原圖，包含原本 approved、excluded 的樣本，保留原備註並記錄修正；原先 excluded 未恢復為 approved，五類原圖沒有 pending。看不清楚的殘留仍為 unknown／空白，不因完成審核而硬填 none。其他五類及近似重複確認尚未完成，資料切分仍屬暫定。詳見 [全量原圖複核報告](dataset_generate/ORIGINAL_REVIEW_REPORT.md)。

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

2026-10-17 另依差額擴充 26 張保麗龍食物殘留圖，全部 pending 待人工驗收；其他四類有殘留資料較多，未繼續新增。生成成功不等於驗收，不直接納入訓練。

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

資料驗收與必要檢查通過後，已獲授權開始正式訓練。現有 v2 未通過，程式會列出阻礙並拒絕啟動。完成驗收後沿用 partition 建立 v3，再執行：

```powershell
uv pip install --python .venv\Scripts\python.exe -r training\requirements.txt
.\.venv\Scripts\python.exe training\workflow.py prepare --version v3 --reuse-partition training\artifacts\v2\partition.json
.\.venv\Scripts\python.exe training\workflow.py run --manifest-dir training\artifacts\v3 --run-dir training\runs\experiment_v3 --allow-weight-download
```

run 依序執行 GPU 短程驗證、stage1、stage2 及最終 test。安裝大型套件須經系統授權；ImageNet 權重只有明確開啟下載時取得。分階段、接續與其他命令見 [訓練操作說明](training/README.md)，實際驗證與資料缺口見 [執行紀錄](training/RUN_REPORT.md)。模型及歷史放在 training/runs/，資料版本、資格與分布放在 training/artifacts/。

## 五、測試評估與推論

已建立兩任務各自的 loss、accuracy、Macro-F1、各類 precision／recall／F1、混淆矩陣、樣本數及逐圖預測。original／generated 分開，真實原圖為主要結果。兩階段模型選擇完成後才固定比較 stage1_best／stage2_best 的 test 表現，不依 test 挑 epoch、調參或決定重訓。

尚無正式模型 accuracy 或 Macro-F1。工具測試、隨機初始化 GPU 短程驗證不代表模型已訓練，合成照片效果也不能代表真實照片效果。已提供單張／多張推論命令與 `Predictor.predict(paths)`，每張限定一個主要物品，回傳垃圾／殘留類別、機率、信心及獨立低信心旗標；本次沒有開發網頁。

本次實際驗證：訓練流程 9 項與既有資料流程 9 項測試通過。GTX 1650 在 224×224、batch size 8、AMP 關閉時，兩階段各 3 次更新通過，峰值 PyTorch allocated 顯存約 899 MiB，無 OOM；AMP 試跑出現非有限梯度，未通過，繼續關閉。現有 734 張 pending、general／food_waste 缺少 approved 樣本，以及 not_assessable 的真實 val 無樣本，仍阻止正式訓練。

## 六、網站建置

**尚未開始。** 後續預計將訓練好的模型整合至網站，提供圖片輸入及辨識結果展示；實際功能、技術選擇與部署方式將在開始開發時記錄。

目前的 `review_ui.html` 是本機資料複核工具，供整理圖片與標籤使用。正式辨識網站尚未開發。

## 階段工作紀錄

| 日期 | 階段 | 工作紀錄 |
|---|---|---|
| 2026-10-15 | 資料清洗 | 完成既有 2,500 張原圖的首次掃描、重複檢查、初版標籤表、聯絡表及本機複核工具 |
| 2026-10-15 | 資料生成 | 完成首輪 10 張、殘留更明顯的 10 張及咖啡液面紙杯 2 張，共 22 張試作，保存來源與生成紀錄 |
| 2026-10-15 | 工具驗證與整理 | 完成回歸測試與資料驗證；程式與工作資料集中至 dataset_generate，標籤放入 dataset |
| 2026-10-17 | 資料清洗與標註 | 備份標籤後完成五類容器共 1,250 張原圖的全量看圖複核，保存逐張修正明細；允許 approved＋unknown／mixed 留白，並將其排除於殘留訓練與比例統計；8 項回歸測試通過。本輪未新增生成圖、未修改生成圖審核結果 |

| 2026-10-17 | 生成擴充 | 完成 26 張保麗龍食品容器殘留擴充，初標後保留 pending 待人工驗收 |
| 2026-10-17 | 模型流程 | 固定 70／20／10 與 train 兩批分配、雙頭模型、兩階段訓練、early stopping、checkpoint 接續、評估及推論程式；正式訓練仍受資料驗收及缺類阻礙 |

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
└─ .venv/                      Python 執行環境
```

從專案根目錄啟動本機複核工具：

```powershell
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py serve
```

開啟 `http://127.0.0.1:8765`。安裝、重新掃描、更新統計與接續生成等詳細指令，請見 [操作說明](dataset_generate/README.md)。

- [兩階段訓練與推論操作](training/README.md)
- [實際驗證及尚未完成事項](training/RUN_REPORT.md)
- [首次資料整理與生成報告](dataset_generate/RUN_REPORT.md)
- [保麗龍食物殘留批次生成紀錄（2026-10-17）](dataset_generate/BALANCE_GENERATION_REPORT.md)：已依缺額擴充生成並完成初檢，待人工驗收；保留來源分組與切分，尚未訓練模型。
- [來源與生成圖片對照](dataset_generate/dataset_workflow/pilot_preview/index.html)
- [各類別與標籤統計](dataset_generate/dataset_workflow/reports/counts.csv)
- [原圖近似重複候選](dataset_generate/dataset_workflow/reports/original_near_duplicates.csv)
- [五類容器的可用數量與補圖差額](dataset_generate/dataset_workflow/reports/balance.csv)

標籤及數量報告留在資料處理檔案中管理；本 README 主要記錄專題各階段做了什麼、產出了什麼，以及目前進行到哪個階段。
