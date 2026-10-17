# 固定資料分配與兩階段訓練

此資料夾提供資料資格檢查、固定 manifest、EfficientNet-B0 雙頭模型、兩階段訓練、接續、評估與多圖推論。**目前資料未完成驗收，正式訓練尚未啟動。** 實際資料與環境結果見 [本次執行紀錄](RUN_REPORT.md)。不搬動圖片、不修改 dataset/labels.csv、不重新審圖或生成。

## 環境與目錄

```text
training/
  workflow.py                 命令入口
  data.py                     資格、固定分組分配、manifest 與指紋檢查
  model.py                    共用骨幹、雙頭、保留整圖的前處理
  engine.py                   訓練、checkpoint、短程驗證、評估與 Predictor
  metrics.py                  四類指標、混淆矩陣
  config.json                 實驗設定
  requirements.txt            固定相容套件組合
  residual_eligibility.csv    unknown 原因的明確資格補充清單
  backups/                    建立／重用版本前的 labels、切分及相關紀錄備份
  artifacts/v2/               本次正式準備版本（v1 是初版檢查快照）
    partition.json            全部資料的固定 group → split／stage
    manifest.csv              合格、去重後的訓練／評估清單
    metadata.json             labels／資格表／manifest／分配的 SHA-256
    readiness.json            資料資格、缺類、阻礙、風險
    distribution.csv          split／stage／細類／來源／兩任務類別分布
    issues.csv                未驗收、排除、mixed、未知原因、重複等清單
    unresolved_near_duplicates.csv
    smoke.json                真正執行後的短程驗證結果
    smoke/                    僅供驗證的隨機初始化模型檔
  runs/experiment_v2/         正式訓練時才建立
    stage1_best.pt、stage1_last.pt、stage1_history.json/csv
    stage2_best.pt、stage2_last.pt、stage2_history.json/csv
    stage1_best_validation.json、stage2_best_validation.json
    stage1_best_validation_predictions.csv、stage2_best_validation_predictions.csv
    final_test/               模型選擇完成後的鎖定測試及比較
```

命令均從 `F:\project\MMIP\middle` 執行。既有 `.venv` 已有 Pillow；安裝 CUDA 套件可能下載數 GB，必須經系統權限流程授權。本次安裝是否完成以執行紀錄為準：

```powershell
uv pip install --python .venv\Scripts\python.exe -r training\requirements.txt
.\.venv\Scripts\python.exe training\workflow.py environment
.\.venv\Scripts\python.exe -m unittest discover -s training -p test_training.py -v
```

固定使用 torch 2.5.1+cu121／torchvision 0.20.1+cu121，不自動升級到其他 CUDA 版本。[官方相容安裝組合](https://pytorch.org/get-started/previous-versions/) 與 [官方 EfficientNet-B0 權重說明](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.efficientnet_b0.html) 為實作依據。只使用官方 ImageNet 權重，不會呼叫付費服務。

## 標籤與資格

類別順序固定，checkpoint 與推論均保存相同順序：

| 任務 | index 0 | index 1 | index 2 | index 3 |
|---|---|---|---|---|
| 垃圾分類 | general | glass | food_waste | other_recycling |
| 殘留分類 | none | food | liquid | not_assessable |

food_waste 是垃圾類別，food 是殘留狀態。not_assessable 顯示「不適用／無法判斷」。低信心是另外的 `low_confidence` 欄位，絕不當成 not_assessable 訓練標籤。

只有 approved、垃圾類別有效、圖片能解碼且無確認重複標籤衝突的樣本進 manifest。excluded／pending 不進模型資料；生成圖同樣須 approved。確認重複的原圖每 group／folder 保留一個代表，生成版本另計；不刪除實體圖片。

| 原始標註 | 殘留訓練 target |
|---|---|
| approved＋yes＋none／food／liquid | 對應 0／1／2 |
| approved＋no＋空白 | not_assessable（3） |
| approved＋unknown＋空白，另有已確認不可判讀原因 | not_assessable（3） |
| unknown 原因未確認、mixed、標籤組合無效 | -1，residual_mask=0 |

最後一列仍可只用於垃圾分類。第二階段跳過無有效殘留標籤的圖片；底層 loss 也會 mask 無效標籤。CSV 原本的 no／unknown 不變。生成提示詞不能作為標籤。

`residual_eligibility.csv` 初建時，approved unknown 全部留 `decision=pending`。只有確認後才填：

- `decision=confirmed`
- `reason=interior_not_visible`、`occluded_interior` 或 `unreadable_interior`
- `reviewer`：確認者
- `evidence`：對應既有複核紀錄或人工確認依據
- `label_fingerprint`：對應目前標籤的指紋，不能挪用其他圖片或舊標籤

程式不搜尋 notes 關鍵字猜資格；原審核 U／B 同時包含不可見、多容器、材質等不同原因，不能整批自動轉換。修改 labels 後，舊資格指紋可能失效，應重新確認補充清單。

## 固定切分與兩批分配

固定 seed=42，目標 train／val／test **70%／20%／10%**。沿用 labels.csv 現有切分，檢查每個 group 及來源／生成關係，不再次抽樣。若現有切分不一致，直接拒絕建立資料，不默默修正標籤。

train 內以完整 group 分配 stage1／stage2，盡量各半。分配同時衡量細類、垃圾類別、已確認殘留、original／generated、每細類來源數量及總量；來源與所有生成版本同階段，val／test 的 stage 為空白。群組大小、奇數與之後的驗收可能造成差距，distribution.csv 會報告實際分布。

疑似近似圖不自動合組；未解決候選列於報告，包括潛在切分洩漏風險。真實原圖是主要驗證／測試結果，生成圖及混合結果另外列出。樣本不足時報告缺類，不能強迫某個 split 一定有足夠樣本。

本次 v2 沿用 v1 的同一 partition，沒有第二次抽籤。重跑 v2 不改既有 manifest；labels／資格清單有變時，建立新版本並沿用分配：

```powershell
# 檢查目前 v2：不重新切分
.\.venv\Scripts\python.exe training\workflow.py verify --manifest-dir training\artifacts\v2

# 完成驗收及資格確認後，建立 v3，沿用同一組分配
.\.venv\Scripts\python.exe training\workflow.py prepare --version v3 --reuse-partition training\artifacts\v2\partition.json
```

備份在建立／檢查版本前執行，labels 只讀。已有模型使用的分配不可為提高結果而重抽。新圖片或確認重複合組使既有 group 不匹配時，程式會拒絕，需另行明確處理新版本，不能默默跨組。

## 模型與 GTX 1650 起始設定

圖片 → EfficientNet-B0 features → AdaptiveAvgPool2d → flatten → 兩個獨立 Dropout＋Linear(1280,4)。原 ImageNet classifier 不註冊進模型，沒有額外大型全連接層。

權重固定 `EfficientNet_B0_Weights.IMAGENET1K_V1`。尚未快取時，只有明確加 `--allow-weight-download` 才下載官方約 20.5 MB 權重；短程驗證使用隨機初始化模型，不會偷偷下載。

| 設定 | 初始值 |
|---|---|
| 輸入 | 224×224 |
| batch size | 8，可用 4／16 |
| num_workers | 0，可用 2 |
| 骨幹 learning rate | 1e-5 |
| 當階段頭 learning rate | 1e-4 |
| 每階段 epoch 上限 | 30 |
| early stopping | patience=5；Macro-F1 嚴格改善才重置 |
| optimizer | AdamW，weight_decay=1e-4 |
| scheduler | ReduceLROnPlateau；只看當階段驗證 Macro-F1 |
| AMP | 預設關閉，可加 --amp；須通過對應 GPU 試跑 |

以上為可調起始值，未宣稱最佳。按需讀圖，不把全部圖片載入 RAM。整張照片等比例縮放加白邊；ImageNet mean/std 正規化。訓練只有水平翻轉與 ±5% 亮度／對比變動，不隨機裁切或旋轉。val／test／推論固定前處理。此整圖處理刻意不同於官方預設中心裁切，以保留瓶底與開口。

## 短程驗證與正式訓練

```powershell
# 少量 train 圖片，每階段各 3 次更新；不使用 test
.\.venv\Scripts\python.exe training\workflow.py smoke --manifest-dir training\artifacts\v2
```

檢查兩頭輸出維度、有限 loss／gradient、凍結頭不變、骨幹與當階段頭更新、checkpoint／optimizer／scheduler／scaler 可讀，以及權重重載推論完全一致；記錄 GPU 名稱、耗時、PyTorch 峰值 allocated 顯存與 OOM。CUDA 不可用不自動退回 CPU。`--device cpu` 僅供功能檢查，不能充當正式訓練的 GPU 通過證明。

AMP 開啟時另比對 FP32／FP16 機率差異，要求不超過 0.03，並檢查所有短程梯度／參數有限。沒有保證 GTX 1650 使用 AMP 一定更快。正式訓練的資料／設定指紋必須匹配成功的 GPU smoke。

本次 FP32 試跑通過，AMP 試跑因非有限梯度未通過，結果分別保存為 smoke.json／smoke_amp.json；目前應使用預設關閉 AMP 的設定，不聲稱 AMP 已穩定。

資料驗收及必要檢查通過後，已獲授權執行完整兩階段。以下以完成驗收後的 v3 為例：

```powershell
# 一次執行 GPU 試跑 → stage1 → stage2 → 預先規劃的最終 test 比較
.\.venv\Scripts\python.exe training\workflow.py run --manifest-dir training\artifacts\v3 --run-dir training\runs\experiment_v3 --allow-weight-download
```

`ready=false` 時會阻止正式訓練，明確列出未驗收及必要缺類。unknown／mixed 可只用於垃圾分類，不會強迫轉殘留標籤；未解近似風險獨立報告，不把候選當已確認重複。未來若採用排除部分未驗收資料的實驗，需先明確決定資料範圍，不能在程式內偷改 review_status。

也可分開執行。第一次下載權重需加上開關；**smoke 與訓練須使用相同設定開關**，因設定指紋會比對：

```powershell
.\.venv\Scripts\python.exe training\workflow.py smoke --manifest-dir training\artifacts\v3 --allow-weight-download
.\.venv\Scripts\python.exe training\workflow.py train --stage stage1 --manifest-dir training\artifacts\v3 --run-dir training\runs\experiment_v3 --allow-weight-download
.\.venv\Scripts\python.exe training\workflow.py train --stage stage2 --manifest-dir training\artifacts\v3 --run-dir training\runs\experiment_v3 --from-stage1 training\runs\experiment_v3\stage1_best.pt --allow-weight-download
```

第一階段只更新共用骨幹＋垃圾頭，殘留頭凍結。依 **真實原圖 val 的垃圾 Macro-F1** 選 stage1_best。第二階段載入已完成模型選擇的 stage1_best，建立新 optimizer／scheduler，只更新共用骨幹＋殘留頭，垃圾頭凍結；僅用殘留 loss，不加垃圾 loss、蒸餾或回放。依 **真實原圖 val 的殘留 Macro-F1** 選 stage2_best。

第二階段每 epoch 評估兩頭，紀錄 `waste_drop_percentage_points = (stage1 最佳垃圾驗證 Macro-F1 − 當前垃圾 Macro-F1) × 100`。可為負數，代表垃圾分類改善。凍結垃圾頭不會阻止骨幹變動導致遺忘；保存 checkpoint 只能恢復／比較，不能防止遺忘。後續若要降低 LR、部分凍結或加入其他 loss，應另開實驗，不能依 test 表現決定重訓。

## 中斷接續與評估

```powershell
.\.venv\Scripts\python.exe training\workflow.py train --stage stage1 --manifest-dir training\artifacts\v3 --run-dir training\runs\experiment_v3 --resume training\runs\experiment_v3\stage1_last.pt --allow-weight-download
.\.venv\Scripts\python.exe training\workflow.py train --stage stage2 --manifest-dir training\artifacts\v3 --run-dir training\runs\experiment_v3 --resume training\runs\experiment_v3\stage2_last.pt --allow-weight-download

# 僅評估 val，不接受 test 作為模型調整依據
.\.venv\Scripts\python.exe training\workflow.py evaluate --checkpoint training\runs\experiment_v3\stage2_best.pt --manifest-dir training\artifacts\v3 --output training\runs\experiment_v3\validation_check

# 分開訓練時：兩階段結束後，才執行這個最終比較
.\.venv\Scripts\python.exe training\workflow.py final-test --manifest-dir training\artifacts\v3 --run-dir training\runs\experiment_v3
```

best／last 使用獨立 stage 前綴與原子存檔，第二階段不覆蓋第一階段。checkpoint 包含完整 state_dict、optimizer、scheduler、scaler、epoch、最佳指標、patience 計數、設定、類別、seed、資料版本與指紋、Python／Torch／CUDA／DataLoader RNG 狀態及歷史。last 以完整 epoch 為接續點，epoch 中斷時回復前一完成 epoch，不宣稱逐 batch 接續；開始時保存 epoch=0 的 last。已 early stop 的 last 不會被自動繼續訓練。

每 epoch 寫 loss、兩頭驗證結果、時間、LR、顯存及遺忘幅度。正式比較預先固定 stage1_best／stage2_best，不按 test 挑 epoch。final-test 先鎖定 checkpoint hash，完成後不可在同一 run 重新訓練或重開測試挑結果。若最終測試中斷，保留其目錄與鎖定紀錄，先確認狀態，不刪檔重抽資料。

兩任務各自保存 loss、accuracy、固定 4 類 Macro-F1、各類 precision／recall／F1／support、4×4 混淆矩陣及逐圖預測。all／original／generated 分開；original 為主要結果。零樣本類別 precision／recall／F1 記 0 並列 support，無任何有效標籤的任務指標為 null。stage1 的殘留頭尚未訓練，其輸出不應解讀為已學會殘留。

## 單張／多張推論

```powershell
.\.venv\Scripts\python.exe training\workflow.py predict --checkpoint training\runs\experiment_v3\stage2_best.pt --images dataset\paper_cups\Image_30.png dataset\styrofoam_food_containers\Image_255.png --device cpu --output training\runs\experiment_v3\predictions.json
```

每張圖限定一個主要物品。`engine.Predictor(checkpoint, device).predict(paths)` 是未來網頁可呼叫的介面，每張回傳兩個類別、機率、信心、low_confidence 與 not_assessable 的中文顯示；損壞圖片逐筆回傳 error。未開發網站或上傳端點。信心門檻 0.6 為可調提示值，尚未校準，不更改模型預測類別。

未來在專案根目錄可使用 `from training.engine import Predictor`，建立一次 Predictor 後重複呼叫 `.predict(paths)`；載入自己產生的 checkpoint，不需要再次下載 ImageNet 權重。
