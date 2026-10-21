# 固定資料分配與兩階段訓練

現況核對：**experiment_v3 已完成**，stage1 共 23 epoch（最佳 18）、stage2 共 28 epoch（最佳 23），正式 test 已鎖定。網站使用 stage2_best.pt，見 [網站說明](../website/README.md)。本次只讀程式、checkpoint 與既有結果來補文件，沒有修改模型、config、manifest、權重或重新訓練。

資料來源是 [model.py](model.py)、[engine.py](engine.py)、[data.py](data.py)、[workflow.py](workflow.py)、[config.json](config.json)，以及 [experiment_v3](runs/experiment_v3/) 的 checkpoint metadata、optimizer／scheduler state、history、completed、best_validation、final_test。程式預設不等於實驗實際值；下文分別列示。

## 環境與成果位置

~~~text
training/
  model.py、engine.py          模型、loss、訓練、評估與 Predictor
  data.py、workflow.py         資格、固定分組分配及命令入口
  metrics.py、config.json      指標與預設設定
  residual_eligibility.csv     unknown 原因的明確資格補充
  backups/                    建立資料版本前的標籤／切分等備份
  artifacts/v3/               v3 manifest、partition、readiness、distribution、issues、smoke
  artifacts/v1/、v2/           歷史版本；不重新抽籤
  runs/experiment_v3/
    stage1_best.pt、stage1_last.pt、stage1_history.json/csv
    stage2_best.pt、stage2_last.pt、stage2_history.json/csv
    stage1_completed.json、stage2_completed.json
    stage1_best_validation.json、stage2_best_validation.json
    *_best_validation_predictions.csv
    final_test/               鎖定 hash、原圖／生成圖指標、逐圖預測及比較
~~~

既有環境是 torch 2.5.1+cu121／torchvision 0.20.1+cu121、CUDA build 12.1、GTX 1650 4096 MiB。日常使用沿用專案 .venv，不必重裝。新環境才依權限流程安裝 requirements.txt；不自動升級 CUDA 組合。

~~~powershell
cd F:\project\MMIP\middle
# 已安裝時不需再執行這行：
uv pip install --python .venv\Scripts\python.exe -r training\requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s training -p test_training.py -v
~~~

[2026-10-17 RUN_REPORT](RUN_REPORT.md) 的「未驗收／未開始」是當時狀態，原文保留。先前 README 沿用該敘述、v2 目錄與「尚未開發網站」，與現有產物矛盾，已在本文件改正。workflow.py 的 CLI 路徑預設仍是 v2／experiment_v2，程式本次不改；目前操作須明確指定 v3 路徑。environment.json 的 cuda_verified=false 只是環境盤點沒有宣稱數值驗證，不能推翻 v3 實際 smoke／訓練產物。

## 模型、預訓練來源與輸出

WasteModel 使用 TorchVision EfficientNet-B0 的 features，官方權重版本固定為 EfficientNet_B0_Weights.IMAGENET1K_V1（ImageNet-1K 預訓練）。來源 URL 由本機 TorchVision enum 核對：
[efficientnet_b0_rwightman-7f5810bc.pth](https://download.pytorch.org/models/efficientnet_b0_rwightman-7f5810bc.pth)；
[官方模型說明](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.efficientnet_b0.html)。

WasteModel 建構子的 pretrained 預設是 false；正式 stage1 新訓練才傳 pretrained=true。未快取權重且 allow_download=false 時直接拒絕，不偷偷下載。stage2、接續及 Predictor 由既有 checkpoint 恢復，不再次取 ImageNet 權重。

~~~mermaid
flowchart TD
    A["RGB 圖片：N×3×224×224"] --> B["共用 EfficientNet-B0 features"]
    B --> C["AdaptiveAvgPool2d(1)"]
    C --> D["flatten：N×1280"]
    D --> E["垃圾頭：Dropout(p=0.2) → Linear(1280,4)"]
    D --> F["殘留頭：Dropout(p=0.2) → Linear(1280,4)"]
    E --> G["垃圾 logits：N×4"]
    F --> H["殘留 logits：N×4"]
~~~

原 ImageNet classifier 沒有註冊進新模型；兩頭各有 5,124 個參數，完整雙頭共 4,017,796 個參數。pool 對空間維度做全域平均，1280 是骨幹通道／特徵維度，不是額外的大型全連接層。

| index | 垃圾頭 | 殘留頭 |
|---:|---|---|
| 0 | general（一般垃圾） | none（無殘留） |
| 1 | glass（玻璃） | food（食物殘留） |
| 2 | food_waste（廚餘） | liquid（液體殘留） |
| 3 | other_recycling（其他回收） | not_assessable（不適用／無法判斷） |

Linear 輸出是未正規化的 logits。評估／推論對每個頭各自 softmax，得到四個和為 1 的機率，再用 argmax 選最終類別；最大機率作為信心。softmax 不把兩個任務混在一起，也沒有依垃圾預測硬改殘留預測。accuracy 是正確張數比例，Macro-F1 是四類 F1 平均，單張信心是模型機率，三者不能混用。

## 標籤資格與 mask

垃圾分類使用 approved、垃圾類別有效、能解碼、無確認重複標籤衝突的資料。excluded／pending 不進 manifest；生成圖必須已人工驗收，提示詞不是標籤。確認重複的原圖依 group／folder 保留一個代表，生成版本另列，實體圖片不刪除。

| dataset 原始資料 | 殘留整數 target |
|---|---|
| approved＋residual_applicable=yes＋none／food／liquid | 0／1／2 |
| approved＋no＋殘留空白 | 3：not_assessable |
| approved＋unknown＋空白，另有合格的不可判讀確認 | 3：not_assessable |
| unknown 原因未確認、mixed、無效組合、確認重複殘留衝突 | -1：不進殘留 loss／指標 |

unknown 只接受 residual_eligibility.csv 中 decision=confirmed、reason 為 interior_not_visible／occluded_interior／unreadable_interior、有 reviewer／evidence 且 label_fingerprint 匹配的資格。程式不從檔名、notes 模糊文字或模型信心猜測原因。原 CSV 的 no／unknown 不變；food_waste 與殘留 food 分屬不同任務。

manifest 的 residual_mask=0 對應 target=-1。真正 loss 依 target>=0 建 mask，不是把空白轉成類別 3。無效殘留仍可只供垃圾任務；正式 stage2 在建 loader 前已排除 target<0，底層 loss 再防護一次。網站新人工表單的垃圾／殘留連動是網站操作範圍規則，**沒有回寫 dataset、重新映射 v3 manifest 或更改模型輸出**。

## 固定 70／20／10 與 train 兩批

seed=42。原圖、生成版本與確認重複以 group_id 為單位，同組不得跨 split 或 stage。目標 train／val／test=70%／20%／10%，沿用既有 labels 的 split；v3 重用 v2 partition，不為成績重抽。train 內以完整 group 貪婪平衡細類、垃圾類別、有效殘留／masked、original／generated、細類×來源及總數，盡量對半；val／test 的 stage 空白。疑似近似圖僅列風險，不能當已確認重複自動合組。

| v3 manifest 用途 | original | generated | 合計 | 實際使用方式 |
|---|---:|---:|---:|---|
| stage1 分配 | 618 | 18 | 636 | 全部做垃圾訓練；239 張殘留 masked 不影響本階段 |
| stage2 分配 | 643 | 18 | 661 | 其中 245 張殘留無效，不進 stage2 loader |
| stage2 有效訓練 | 398 | 18 | 416 | 僅殘留 loss |
| val | 369 | 8 | 377 | 垃圾全有效；殘留 222 原圖＋8 生成＝230 |
| test | 176 | 4 | 180 | 垃圾全有效；殘留 108 原圖＋4 生成＝112 |

manifest 共 1,854 張，train 1,297／val 377／test 180；分配比例是目標，資格／去重／完整群組優先。全 labels 2,548 張的既有 split 為 1,786／508／254，不能把這個數量當成實際訓練樣本數。詳見 artifacts/v3/distribution.csv 與 readiness.json。

## 兩階段與 train／eval 的實際行為

| 項目 | stage1 | stage2 |
|---|---|---|
| 資料 | stage1 的 636 張 | stage2 殘留有效的 416 張 |
| 更新 | features＋waste_head | features＋residual_head |
| 凍結 | residual_head 的參數 | waste_head 的參數 |
| 唯一訓練目標 | 垃圾 CE | 殘留 CE |
| 選模、scheduler、early stopping | 真實原圖 val 垃圾 Macro-F1 | 真實原圖 val 殘留 Macro-F1 |
| 監控 | 兩頭驗證 | 兩頭驗證＋垃圾退步百分點 |

stage2 必須指定已完成 stage1 model selection 的 stage1_best.pt，檢查 stage、完整 config、data_metadata 與 stage1_completed.json，再載入完整 model state_dict；來源 hash 保存於 stage2。**建立新的 optimizer／scheduler**，不沿用 stage1 的 AdamW 動量或已降過的 LR。純殘留 loss，不加垃圾 loss、蒸餾或回放。

每個 epoch 開始呼叫 model.stage(stage)：先所有參數 requires_grad=true，再把非當階段頭 requires_grad=false；呼叫整體 train()，接著只把凍結頭切 eval()。所以：

- features 的 BatchNorm 在訓練使用當批統計，running_mean／running_var 等 buffers 繼續更新；骨幹原有隨機層也處於 train 模式。
- 活動頭 Dropout(p=0.2) 在 train 隨機丟棄特徵；凍結頭的 Dropout 在 eval 停用。兩個 Linear 各自仍產生 logits，但只有當階段 loss 反傳。
- evaluate_rows／Predictor 令整體 eval()：所有 Dropout 停用，BatchNorm 用已保存的 running statistics；評估用 inference_mode。下一 epoch 再呼叫 stage() 恢復上列模式。
- 凍結垃圾 Linear 只固定最後的映射。stage2 骨幹權重、BatchNorm buffers 改變，輸入垃圾頭的特徵也變，因此仍會遺忘；存 checkpoint 只能恢復與比較，不能防止遺忘。

## Loss：直接接 logits

model.masked_loss 實際呼叫 torch.nn.functional.cross_entropy(logits[valid], target[valid])，等價於預設 CrossEntropyLoss：

| 參數 | 程式／v3 實際值 |
|---|---|
| input | 浮點 logits，形狀 N×4；不先 softmax |
| target | torch.long 整數類別，形狀 N，合法值 0～3 |
| valid | target>=0；先篩除 -1，不依賴 ignore_index=-1 |
| weight | None：未啟用類別權重 |
| label_smoothing | 0.0：未啟用 |
| reduction | mean：該批有效樣本 CE 平均 |
| ignore_index | 函式預設 -100；本流程的 -1 已先被 mask 移除 |

CE 內含 log_softmax 的數值穩定計算，**不能先 softmax 再當 logits 傳入**。對正確類別 y，單例 loss 是 -log(softmax(z)[y])。stage1 的 L=CE(z_waste,y_waste)，stage2 的 L=CE(z_residual,y_residual)，都只平均有效樣本。全部 target 無效時 masked_loss 回 None，step 不做 backward／optimizer step；正式 stage2 預篩防止此批次。

沒有實作 alpha×垃圾 loss＋beta×殘留 loss。每 epoch training_loss 將各批 mean 按有效張數加權，等於整個 epoch 的有效樣本平均；evaluate_rows 逐圖累計 CE，再依 original／generated／all 及任務計算平均。

## Optimizer、兩組 LR 與 scheduler

兩階段都使用 AdamW（解耦 weight decay），由 optimizer_for 硬編碼選用；不是可在 JSON 選擇其他 optimizer。config 提供兩組初始 LR：features 1e-5、當階段頭 1e-4；凍結頭不在 optimizer groups。weight_decay=1e-4 套用兩組全部參數，沒有另做 bias／BatchNorm 的免衰減分組。

checkpoint 核對 AdamW betas=(0.9,0.999)、eps=1e-8、amsgrad=false、maximize=false、foreach=None、fused=None、capturable=false、differentiable=false。除 weight_decay／兩組 LR 外由安裝的 PyTorch 預設提供；AdamW 不使用 SGD 的 momentum 參數。小骨幹 LR 減少預訓練特徵擾動，較大的頭 LR 幫助新任務頭學習；提高骨幹 LR 可能加速適應也加重遺忘，過低則可能收斂不足，須另以 val 驗證。

scheduler 是 ReduceLROnPlateau，mode=max、factor=0.5、patience=2、min_lr=1e-7；其餘由 checkpoint／本機函式預設核對為 threshold=1e-4、threshold_mode=rel、cooldown=0、eps=1e-8。**每 epoch 驗證完成後 scheduler.step(score)**，score 就是當階段「原圖 val」Macro-F1。超過 2 個未改善 epoch 才減半（通常第 3 個）；不看 train loss 或 test。scheduler 的相對改善 threshold 與 best／early stopping 的 min_delta=0 嚴格改善判定不同。

| LR 時點 | stage1 骨幹／頭 | stage2 骨幹／頭 |
|---|---|---|
| 階段起始 | 1e-5／1e-4 | 1e-5／1e-4（重新建立） |
| best checkpoint 當 epoch | 2.5e-6／2.5e-5 | 5e-6／5e-5 |
| last checkpoint 的下一 epoch LR | 1.25e-6／1.25e-5 | 2.5e-6／2.5e-5 |

history 的 learning_rates 是本 epoch 開始值，learning_rates_next 才是 scheduler 更新後值；不能把 config 初始值當成整段訓練不變的 LR。

## 設定：預設、v3 實際及未來調整

| 設定 | 程式預設（config／CLI） | experiment_v3 實際 |
|---|---|---|
| model／weights | efficientnet_b0／IMAGENET1K_V1 | 相同 |
| seed／split_ratios | 42／[0.7,0.2,0.1]，CLI 驗證固定 | 沿用 v2 partition |
| input_size／dropout | 224／0.2 | 相同 |
| batch_size／num_workers | 8／0 | 相同；stage1 每 epoch 636、stage2 416 張 |
| backbone_lr／head_lr／weight_decay | 1e-5／1e-4／1e-4 | 起始相同，後由 scheduler 降 LR |
| max_epochs／patience／min_delta | 30／5／0.0 | 30／5／0.0；實際於 23／28 epoch early stop |
| amp／device | false／cuda | FP32、cuda，無 AMP |
| horizontal_flip／brightness_contrast | 0.5／0.05 | 相同 |
| confidence_threshold | 0.6 | 相同，只作推論提示 |
| allow_weight_download | config=false | checkpoint=true（當時明確授權） |
| CLI manifest／run 路徑 | artifacts/v2／runs/experiment_v2 | 明確使用 artifacts/v3／runs/experiment_v3 |

前處理：EXIF 方向修正 → RGBA 合成到白底（處理透明）→ RGB → BICUBIC 等比例縮放到 224 方框內 → 置中白色補邊 → ToTensor → ImageNet mean [0.485,0.456,0.406]／std [0.229,0.224,0.225] 正規化。不使用官方預設中心裁切，以保留開口、瓶底及殘留線索。訓練只加水平翻轉 p=0.5 與 ColorJitter 的 brightness／contrast=0.05；無隨機裁切、旋轉、色相或飽和增強。val／test／推論用固定前處理。按需讀圖，不預載整個資料集到 RAM；train shuffle=true、drop_last=false，CUDA pin_memory=true。Python／Torch／CUDA／loader generator 固定種子，deterministic algorithms 開啟、cuDNN benchmark 關閉。

AMP CLI 有 --amp／--no-amp，但不是已通過的 v3 選項。GPU capability 至少 7 且另有 AMP／FP32 機率差≤0.03與有限梯度檢查；舊 v2 AMP smoke 曾 Non-finite gradient。v3 用 FP32，未宣稱 AMP 穩定或更快。

| 項目 | 目前設定 | 設定位置或參數名稱／支援方式 | 用途與影響 |
|---|---|---|---|
| 骨幹 LR | 初始 1e-5 | config backbone_lr；現有 --config 載入 | 調整特徵適應速度與遺忘風險 |
| 分類頭 LR | 初始 1e-4 | config head_lr；現有 --config | 新任務頭的學習速度 |
| optimizer | AdamW | engine.optimizer_for 寫死；換種類須改程式，未提供 CLI | 影響更新規則；不可把其他 optimizer 說成已使用 |
| weight decay | 1e-4 | config weight_decay；現有 --config | L2 型衰減的解耦正則化 |
| scheduler | Plateau(max,.5,2,min=1e-7) | engine.optimizer_for 寫死；種類／參數須改程式 | 停滯時降 LR；不改資料切分 |
| batch size | 8 | --batch-size 4／8／16；或 config batch_size | 顯存、更新噪音；新值須重新 smoke |
| epoch 上限 | 30 | config max_epochs；現有驗證僅允許 1～30 | 最多訓練輪數，不代表必跑滿 |
| early stopping patience | 5 | config patience 但 workflow 強制等於 5；換值須改驗證程式 | 連續未改善的容忍度 |
| early stopping min_delta | 0.0 | config min_delta，允許≥0 | 決定嚴格改善幅度，不等於 scheduler threshold |
| loss 類別權重 | None | model.masked_loss／engine.evaluate_rows 均未接設定；須改程式 | 未來可處理不平衡；不應單改 train 而誤報 eval loss |
| label smoothing | 0.0 | 同上，須改程式；未提供 config／CLI | 未來可調軟化 target 正則化 |
| 頭 Dropout | p=0.2 | config dropout；現有 --config，新建模型時用 | 頭的正則化，推論 eval 停用 |
| 凍結範圍 | 骨幹皆更新，凍結另一頭 | model.stage＋engine.optimizer_for 寫死；部分骨幹凍結須改程式並處理 BN 模式 | 未來可減少遺忘，但不是 v3 實驗 |
| 資料增強 | flip .5、亮度／對比 .05 | config horizontal_flip／brightness_contrast；現有 --config | 改善泛化，過強可能破壞殘留線索；新操作須改 preprocessing |
| 輸入尺寸 | 224×224 | config input_size（正整數）；現有 --config | 改顯存、速度與細節；preprocessing 名稱字串不會自動改運算 |
| num_workers／AMP／device | 0／false／cuda | CLI --num-workers 0／2、--amp／--no-amp、--device cpu／cuda | 資源與數值策略；正式訓練仍須 CUDA smoke 通過 |
| 推論低信心門檻 | 0.6 | predict --threshold；或 Predictor(confidence_threshold=...) | 僅改 low_confidence 旗標，不改權重／argmax；網站沿用 checkpoint，無調整 UI |

表中的未來選項本次都沒有新增實作。修改 config 應另存新設定並用 --config 指向，重新 smoke、使用新 run；不能修改已鎖定 v3 的設定接續。stage2 要求與來源 stage1 config 完全相等。**所有調參依 val，不依 test**；低信心門檻是推論設定，不是訓練超參數。

## GTX 1650 實測與 checkpoint

v3 FP32 smoke：batch=8、224、每階段各 3 次更新，4.2018 秒，PyTorch peak allocated 898.80 MiB，oom=false；隨機初始化，不作模型準確率證明。正式兩階段歷史 peak allocated 最大均為 805.70 MiB，stage1 epoch 耗時加總 405.13 秒、stage2 362.36 秒（不含初始載入／下載、smoke、最終 test 等）。這不是整張顯卡占用或 RAM 峰值，其他程序、CUDA context／reserved memory 另計；不能據此保證 batch=16、大尺寸或 AMP 都安全／更快。

每階段上限 30、early stopping patience=5；原圖 val 當階段 Macro-F1 > best+min_delta 才視為改善，平手不改善。stage1_best 依垃圾、stage2_best 依殘留選擇；每 epoch 同時評估兩頭並記錄完整 loss、樣本數、指標、耗時、當前／下一 LR、顯存和 stage2 垃圾下降百分點。

best／last 按 stage 獨立原子存檔。保存完整 model state_dict（含 BN buffers）、optimizer、scheduler、scaler、epoch、best_metric、bad_epochs、config、preprocessing、weights ID、類別順序、seed、資料版本／指紋、Python／Torch／CUDA／loader RNG、history、stage1 基準與來源 hash、Torch／TorchVision 版本。FP32 也有 scaler 欄位（停用時空 state），不能把其存在當 AMP 已啟用。

接續只接受同 run／同 stage 的 last、完全相同 config／data_metadata；從下一完整 epoch 開始，epoch 中斷會重做該 epoch，不宣稱逐 batch 接續。已 early stop 不自動再跑；有 final_test 目錄就禁止該 run 再訓練。stage1 檔案不被 stage2 覆蓋。

## experiment_v3 實際結果

| 階段 | 完成 epoch | best epoch | 用於選擇的原圖 val Macro-F1 | 同一 best 的原圖 val 垃圾 Macro-F1 |
|---|---:|---:|---:|---:|
| stage1 | 23 | 18 | 垃圾 95.2612% | 95.2612% |
| stage2 | 28 | 23 | 殘留 88.8777% | 92.4171% |

stage2_best 的原圖 val 垃圾 Macro-F1 比 stage1 基準下降 **2.8441 個百分點**。這與下列最終 test 的下降不同，不混用。

各 best checkpoint 的驗證結果按來源分開如下；generated 不參與 best 的選擇：

| checkpoint／任務 | 原圖 val n | 原圖 accuracy | 原圖 Macro-F1 | generated val n | generated accuracy | generated Macro-F1 |
|---|---:|---:|---:|---:|---:|---:|
| stage1_best／垃圾 | 369 | 95.9350% | 95.2612% | 8 | 100.0000% | 25.0000% |
| stage2_best／垃圾 | 369 | 93.7669% | 92.4171% | 8 | 100.0000% | 25.0000% |
| stage2_best／殘留 | 222 | 92.3423% | 88.8777% | 8 | 100.0000% | 75.0000% |

正式測試在兩階段模型選擇完成後，按預定比較 stage1_best／stage2_best；selection_locked.json 鎖定 hash。以下只讀既有 final_test，沒有重跑或依 test 調參。

| checkpoint／任務 | 原圖 n | 原圖 accuracy | 原圖 Macro-F1 | generated n | generated accuracy | generated Macro-F1 |
|---|---:|---:|---:|---:|---:|---:|
| stage1_best／垃圾 | 176 | 94.8864% | 94.0192% | 4 | 100.0000% | 25.0000% |
| stage2_best／垃圾 | 176 | 93.1818% | 91.5659% | 4 | 100.0000% | 25.0000% |
| stage2_best／殘留 | 108 | 87.0370% | 82.1091% | 4 | 75.0000% | 41.6667% |

stage1 殘留頭未訓練，雖然檔案有其指標，不當成有效殘留成果。stage2 原圖 test 垃圾 Macro-F1 下降 **2.4532 個百分點**（94.0192→91.5659），accuracy 下降 1.7045 個百分點。all 混合結果保留於原檔，不用它取代真實照片主要結果。

Macro-F1 固定平均四類，零 support 類 F1=0；generated test 垃圾只有 other_recycling，所以即使 accuracy=100%，Macro-F1 也只有25%。生成測試僅 4 張，不代表真實照片泛化。原圖 test 殘留 support：none 12、food 18、liquid 16、not_assessable 62，存在樣本小及不平衡限制。

readiness=true 不表示風險消失：仍有 820 組未解近似候選、688 筆 unknown 原因未明確資格確認，另有 37 筆 mixed／未標註問題列入報告；各清單是來源級問題數，不等於當階段實際 masked 數。不能從空白推定 none／not_assessable，也不能把生成圖效果當成真實殘留測試效果。信心未校準，不宣稱其百分比就是正確率。

## 操作命令與禁止覆寫已完成實驗

目前查看資格只需：

~~~powershell
.\.venv\Scripts\python.exe training\workflow.py verify --manifest-dir training\artifacts\v3
~~~

下列是**未來另開實驗**的流程範例，本次不執行，不重跑 experiment_v3。先有明確新資料／設定，建立新版本並沿用固定分配；prepare 會先備份 labels、資格與分配等，不改原圖。

~~~powershell
# 僅在需要新版本時執行；不是目前待辦：
.\.venv\Scripts\python.exe training\workflow.py prepare --version v4 --reuse-partition training\artifacts\v3\partition.json
# my_config.json 需自行建立；--config 為主命令參數，放在子命令前。
.\.venv\Scripts\python.exe training\workflow.py --config training\my_config.json smoke --manifest-dir training\artifacts\v4
.\.venv\Scripts\python.exe training\workflow.py --config training\my_config.json train --stage stage1 --manifest-dir training\artifacts\v4 --run-dir training\runs\experiment_v4
.\.venv\Scripts\python.exe training\workflow.py --config training\my_config.json train --stage stage2 --manifest-dir training\artifacts\v4 --run-dir training\runs\experiment_v4 --from-stage1 training\runs\experiment_v4\stage1_best.pt
# 尚未 early stop／final test 的相同 run，才可用對應 last 接續：
.\.venv\Scripts\python.exe training\workflow.py --config training\my_config.json train --stage stage2 --manifest-dir training\artifacts\v4 --run-dir training\runs\experiment_v4 --resume training\runs\experiment_v4\stage2_last.pt
# 兩階段模型選擇完成後才執行一次：
.\.venv\Scripts\python.exe training\workflow.py final-test --manifest-dir training\artifacts\v4 --run-dir training\runs\experiment_v4
~~~

若新環境未快取 ImageNet 權重，須按權限流程明確授權 --allow-weight-download，且 smoke／train 設定開關必須相同，因會比對 config 指紋。正式 train 要求 ready=true、同 config／manifest 指紋的 CUDA smoke 通過；CPU smoke 僅功能檢查。run 子命令可串 smoke→stage1→stage2→final-test，但不應拿已完成的 v3 再執行。

只想評估 val 或推論，可將新輸出寫到獨立資料夾，不覆寫正式 test：

~~~powershell
.\.venv\Scripts\python.exe training\workflow.py evaluate --checkpoint training\runs\experiment_v3\stage2_best.pt --manifest-dir training\artifacts\v3 --output verification\validation_check
.\.venv\Scripts\python.exe training\workflow.py predict --checkpoint training\runs\experiment_v3\stage2_best.pt --images dataset\paper_cups\Image_30.png --device cpu
~~~

Predictor(checkpoint,device,confidence_threshold=None) 啟動時載入一次、eval；predict(paths) 逐圖 inference_mode，同次 forward 產生兩頭，損壞圖片逐筆 error。網站已重用此介面，詳見 [網站 README](../website/README.md)。前端人工選單規則不限制模型 softmax 或改寫預測。
