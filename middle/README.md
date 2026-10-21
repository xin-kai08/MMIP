# 垃圾分類與容器殘留辨識專題

本專題規劃從圖片資料蒐集開始，經過資料清洗、標註與殘留圖片生成，再進行模型訓練、測試評估，最後建立可使用模型的網站。

這份 README 記錄專題整體進度；各項操作與技術細節可從以下入口查看。

## 重要說明文件

| 說明文件 | 主要內容 |
|---|---|
| [資料處理操作說明](dataset_generate/README.md) | 圖片掃描、資料清洗、人工審核、標籤與圖片生成流程 |
| [模型與訓練說明](training/README.md) | 模型架構、資料切分、兩階段訓練、參數設定、評估與推論 |
| [網站操作與開發說明](website/README.md) | 網站啟動、前後端開發、人工標註、歷史查詢、統計與 CSV 匯出 |
| [安全清理操作說明](maintenance/README.md) | 標籤備份封存、ZIP 驗證與還原、快取清理及保留規則 |

磁碟整理與標籤備份封存請見 [安全清理操作說明](maintenance/README.md)：預設 dry-run、保留最近 20 份自動備份與全部特殊命名備份，舊備份逐檔驗證 ZIP 解壓 SHA-256 後才移除。既有儲存前備份機制保持不變。

[2026-10-20 實際清理報告](maintenance/CLEANUP_REPORT.md)：已封存 2,832 份舊自動備份，保留最新 5 份及特殊備份，專案淨減少約 1.95 GiB；必要資料與環境保留。

## 專題流程與目前階段

資料蒐集 → 資料清洗與標註 → 資料生成 → 模型訓練 → 測試評估 → 網站建置

**目前已完成模型訓練與本機網站第一版**：experiment_v3 的兩階段與正式 test 已完成，網站串接 stage2_best.pt，提供多圖辨識、SQLite 歷史、預測前 Ground Truth／結果後回饋、評估及 CSV。網站上傳資料獨立保存，不修改 dataset、人工標籤、分配、權重或正式測試結果。

2026-10-20 已修正網站人工標註：相同回饋不重複新增歷史，前後端皆檢查變更；評估結果顯示鎖定的預測前答案，額外修正回饋預設收合、選填，統計依來源及最新確認狀態分開計算。操作、驗證及重啟方式見 [網站說明](website/README.md)。

三種人工表單已加入垃圾／殘留連動：先選垃圾類別，一般垃圾／廚餘固定帶入「不適用」但不自動確認，玻璃／其他回收提供四種殘留選項。舊標註唯讀保留、修正另存；這是本專題物品範圍規則，不代表所有一般垃圾皆不可能有殘留。詳見 [本次驗證報告](website/LINKAGE_AND_MODEL_DOC_REPORT.md)。

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

目前使用 **ImageNet 預訓練 EfficientNet-B0 共用骨幹＋兩個四類分類頭**。完整參數、CLI 支援範圍、實驗值與可調項目見 [訓練 README](training/README.md)；以下以本機程式與 experiment_v3 實際產物核對，不把一般模型範例當成專案設定。

### 模型如何同時回答兩個問題

預訓練版本是 TorchVision 的 EfficientNet_B0_Weights.IMAGENET1K_V1，來源為 [PyTorch 官方權重](https://download.pytorch.org/models/efficientnet_b0_rwightman-7f5810bc.pth)。取原模型 features，移除 ImageNet classifier，再加全域平均池化和兩個小型頭；不是串接兩個獨立完整模型。

~~~mermaid
flowchart LR
    A["圖片：224×224"] --> B["EfficientNet-B0 共用 features"]
    B --> C["全域平均池化 → 1280 維"]
    C --> D["Dropout 0.2 → Linear 1280→4"]
    C --> E["Dropout 0.2 → Linear 1280→4"]
    D --> F["垃圾 logits → softmax → 類別／信心"]
    E --> G["殘留 logits → softmax → 類別／信心"]
~~~

| index | 垃圾分類 | 殘留分類 |
|---:|---|---|
| 0 | general／一般垃圾 | none／無殘留 |
| 1 | glass／玻璃 | food／食物殘留 |
| 2 | food_waste／廚餘 | liquid／液體殘留 |
| 3 | other_recycling／其他回收 | not_assessable／不適用或無法判斷 |

兩頭各輸出 4 個未正規化分數（logits），推論各自 softmax 成四個機率，取最大者作為類別與信心。food_waste 是垃圾標籤，food 是殘留標籤。模型沒有依垃圾預測強制限制另一頭；網站人工表單的類別連動也不改寫模型輸出。信心不是正確率，低信心不轉成 not_assessable。

### 資料如何分配及取得資格

固定 seed=42、目標 train／val／test **70%／20%／10%**，沿用既有 group 分配。原圖、生成版本與確認重複同組；train 內再以完整群組，兼顧物品細類、兩任務與 original／generated 分布，盡量對半分成 stage1／stage2。群組完整性優先，不為結果重抽；疑似近似圖不直接當已確認重複。

v3 合格 manifest 共 1,854 張：stage1 636、stage2 分配 661、val 377、test 180。stage2 真正使用其中 **416 張殘留有效資料**，不是把 661 張全部當成有殘留標籤。val／test 不進任何階段訓練；生成圖必須驗收，且與來源原圖同組同 split。

approved 只是完成審核，仍按任務判定資格。原 CSV 的 no／unknown 保留：approved＋yes＋none／food／liquid 對應殘留 0／1／2，approved＋no＋空白對應 not_assessable；unknown＋空白只有另具 [明確資格確認](training/residual_eligibility.csv) 才可對應 not_assessable。未知原因、mixed 或衝突用 target=-1／mask 跳過殘留，仍可只供垃圾訓練，不把空白猜成 none。

### 兩階段學什麼、如何更新

| 階段 | 實際訓練資料 | 更新／凍結 | 唯一訓練 loss | best 選擇 |
|---|---|---|---|---|
| stage1 | 636 張（618 原圖＋18 生成） | 更新骨幹＋垃圾頭；凍結殘留頭 | 垃圾 CrossEntropy | 真實原圖 val 垃圾 Macro-F1 |
| stage2 | 416 張（398 原圖＋18 生成） | 更新骨幹＋殘留頭；凍結垃圾頭 | 殘留 CrossEntropy | 真實原圖 val 殘留 Macro-F1 |

stage2 載入已完成模型選擇的 stage1_best.pt，核對 config／資料版本，保存來源 hash，再建立全新的 optimizer／scheduler。沒有沿用 stage1 動量，也沒有使用垃圾 loss、蒸餾或回放。

「凍結」包含兩件事：非活動頭 requires_grad=false 且 eval，頭內 Dropout 停用；活動頭與共用骨幹 train，活動頭 Dropout 啟用，骨幹 BatchNorm 繼續更新 running statistics。驗證／推論則整體 eval，Dropout 停用、BatchNorm 使用已存統計。stage2 即使不更新垃圾 Linear，骨幹權重與 BatchNorm 改變仍可能使垃圾能力退步；保存 checkpoint 只能恢復／比較，不能防止遺忘。

### Loss、optimizer 與起始設定

實際 loss 是 functional.cross_entropy：直接接 N×4 logits 與 N 個 long 整數 target，先用 target>=0 過濾無效標籤。**不先 softmax 再傳入 CE**；類別權重未啟用（None）、label smoothing=0、reduction=mean。每階段只用自己的 CE，沒有多任務加權 loss。

AdamW 分兩個 parameter groups：骨幹初始 LR=1e-5、活動頭 LR=1e-4；weight_decay=1e-4、betas=(0.9,0.999)、eps=1e-8、amsgrad=false。較小骨幹 LR 用來減少預訓練特徵擾動，頭使用較大 LR 學新任務；不是已驗證的最佳值。

ReduceLROnPlateau 每 epoch 驗證後，以當階段原圖 val Macro-F1 更新：mode=max、factor=0.5、patience=2、min_lr=1e-7，threshold=1e-4（relative）、cooldown=0、eps=1e-8。LR 會隨停滯下降；best／early stopping 另以嚴格改善 min_delta=0 判定，patience=5，不與 scheduler 的 patience 混用。

| 項目 | config 起始／預設值 | experiment_v3 實際 |
|---|---|---|
| 輸入／正規化 | 224×224，ImageNet mean/std | 相同 |
| 前處理 | EXIF 修正、等比例 BICUBIC 縮放、白色補邊 | 保留整圖；不中心裁切 |
| 訓練增強 | 水平翻轉 p=.5、亮度／對比 .05 | 相同；無旋轉或隨機裁切 |
| batch／num_workers | 8／0 | 相同，按需讀圖 |
| 每階段 max_epochs／early stopping | 30／patience=5 | 23／28 epoch 提早停止 |
| AMP／裝置 | false／cuda | FP32、GTX 1650 4 GB |
| 權重下載開關 | allow_weight_download=false | 當時明確授權 true |

val／test／推論前處理固定。v3 FP32 smoke 通過：batch=8、每階段 3 次更新、4.20 秒、peak allocated 898.80 MiB、無 OOM；正式訓練歷史最大 allocated 805.70 MiB。這不是整張顯卡占用，不能保證 batch=16 或其他尺寸都安全。舊 AMP smoke 有非有限梯度，v3 未使用 AMP，不聲稱其穩定或加速。

best 與 last 依 stage 分開存，不互相覆蓋；含模型與 BN buffers、optimizer／scheduler／scaler、epoch、指標、設定、類別、seed、資料指紋、RNG 與歷史。接續只支援同 run／同 stage、相同設定與資料的 last，從完整 epoch 邊界恢復；early stop 或已 final_test 鎖定的 v3 不允許繼續訓練。

不換骨幹也可研究 LR、weight decay、batch、Dropout、資料增強與尺寸，但須新實驗及 smoke。optimizer 種類、scheduler、類別權重／smoothing、部分骨幹凍結目前要修改程式；patience 雖在 config 但 CLI 固定要求 5，不能把它描述為任意可調。完整「項目／目前設定／位置／影響」表見 [訓練參數說明](training/README.md)。推論門檻 0.6 可由 Predictor／predict --threshold 調整提示，**不改權重或 argmax**，網站沒有門檻調整 UI。調參依 val，不依 test。

## 五、正式測試與網站實測

experiment_v3 的 stage1 在 epoch 23 停止，best=18、原圖 val 垃圾 Macro-F1 **95.2612%**；stage2 在 epoch 28 停止，best=23、原圖 val 殘留 Macro-F1 **88.8777%**。該 stage2_best 的原圖 val 垃圾 Macro-F1 為 92.4171%，較 stage1 下降 **2.8441 個百分點**。

模型選擇完成後才對保留 test 做預先規劃的兩個 best 比較；以下讀自既有 final_test，沒有重跑測試或用它挑 epoch。

| checkpoint／任務 | 原圖有效 n | 原圖 accuracy | 原圖 Macro-F1 | generated n | generated accuracy | generated Macro-F1 |
|---|---:|---:|---:|---:|---:|---:|
| stage1_best／垃圾 | 176 | 94.89% | 94.02% | 4 | 100% | 25.00% |
| stage2_best／垃圾 | 176 | 93.18% | 91.57% | 4 | 100% | 25.00% |
| stage2_best／殘留 | 108 | 87.04% | 82.11% | 4 | 75% | 41.67% |

原圖 test 垃圾 Macro-F1 下降約 **2.45 個百分點**，與 val 的下降幅度分開解讀。stage1 殘留頭未訓練，不當作有效殘留成果。generated test 只有 4 張，垃圾只有 other_recycling；Macro-F1 固定四類、零 support 類 F1=0，所以 accuracy=100% 不等於 Macro-F1=100%，也不代表真實照片泛化。

v3 仍有 820 組未解近似候選，688 筆 unknown 資格未確認而保持殘留 mask；另有 mixed／未標註資料。原圖 test 的殘留 none 12、food 18、liquid 16、not_assessable 62，樣本有限且不平衡。完整 loss、各類指標、混淆矩陣及逐圖預測見 [正式比較](training/runs/experiment_v3/final_test/comparison.json)。

網站實測是另外保存的上傳紀錄，預設使用預測前 GT，結果後回饋另列，按 checkpoint hash 分開統計，不覆寫正式 test。accuracy 是正確比例、Macro-F1 平衡看四類，信心是單張模型機率且尚未校準。歷史 [2026-10-17 訓練報告](training/RUN_REPORT.md) 保留當時狀態；曾有的「尚未訓練」敘述已依 completed／checkpoint／final_test 更新現況。

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
