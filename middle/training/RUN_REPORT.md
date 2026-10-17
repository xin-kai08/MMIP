# 訓練流程建立與短程驗證（2026-10-17）

已閱讀專案及上層適用位置，未找到 AGENTS.md；已閱讀根 README、dataset_generate 說明、現有審核／分組程式與 labels。沿用既有成果，未重新審圖或生成圖片。依最新規格使用 70／20／10、seed=42、每階段最多 30 epoch、early stopping patience=5。

**程式與 GPU 短程驗證完成，正式訓練未開始。資料驗收尚未通過，沒有正式 best／last、模型 accuracy 或 Macro-F1，也沒有評估實際保留 test。**

## 已建立的程式

data.py 建立資格與固定 manifest；model.py 建立 EfficientNet-B0 共用 features、全域平均池化與兩個 Dropout＋Linear 頭；engine.py 提供兩階段純 loss 訓練、完整 epoch 接續、best／last、驗證、鎖定 test 比較及 Predictor 多圖推論；workflow.py 提供可實際執行的命令。

只在 stage1 正式啟動時載入官方 IMAGENET1K_V1 預訓練權重；本次 GPU smoke 使用隨機初始化，不下載 ImageNet 權重，不把 smoke 模型當正式模型。

## 資料與分配

主標籤共 2,548 筆：2,500 original、48 generated。original 為 approved 1,208、excluded 584、pending 708；generated 為 approved 22、pending 26。既有原始 split 為 train 1,786、val 508、test 254，約 70.1%／19.9%／10.0%，原樣沿用。

去除未驗收、排除與確認重複代表後，manifest 有 1,181 張：

| 用途 | 總數 | original | generated | 有效殘留標籤 | 殘留 mask |
|---|---:|---:|---:|---:|---:|
| stage1（train） | 408 | 400 | 8 | 169（本階段不用殘留 loss） | 239 |
| stage2（train） | 418 | 409 | 9 | 173 | 245 |
| val | 239 | 236 | 3 | 92 | 147 |
| test | 116 | 114 | 2 | 48 | 68 |

stage2 實際殘留訓練會只讀 173 張有效樣本；245 張垃圾分類可用、殘留不可用的圖片不進殘留 loss。各細類／垃圾／殘留／來源完整交叉分布見 [distribution.csv](artifacts/v2/distribution.csv)。以上 test 僅為資料數量檢查，不是模型評估。

v1 為初版檢查快照；v2 使用完全相同的 partition，補充分開列示阻礙與風險、以及真實原圖 val 的必要缺類檢查。v1／v2 partition 位元組一致，沒有第二次抽樣。labels、資格表、manifest 與 partition 都保存 SHA-256；重跑同版本不改分配，變更標籤後須建立新版本並重用 partition。

## 資料阻礙與風險

正式訓練的阻礙：

1. **734 張 pending**：708 張原圖及 26 張新生成圖，未納入有效資料。
2. **general 與 food_waste 沒有 approved 樣本**，stage1 與 val 無法完成四類垃圾訓練／選模。
3. **not_assessable 的真實 val 無樣本**；目前只有一張已批准的 generated／no 樣本進 stage2，不能支撐此類驗證。

另有以下尚未解決事項，均明確報告，不靠猜測轉標籤：

- 688 張 approved unknown 缺少明確不可判讀原因資格（含紙箱與容器）。[補充清單](residual_eligibility.csv) 初建全 pending；只有 reason、reviewer、evidence 與目前 label_fingerprint 都齊全時，才可轉 not_assessable。原因未確認時保留殘留 mask，仍可只用於垃圾分類。
- 37 張 approved yes／空白為 mixed 或未能表示單一殘留，保留 mask，不硬標 food／liquid／none。
- 49 張合格原圖在確認重複群組內已有代表，不重複計數，也未刪圖。
- 820 個未解近似候選（已知同來源組之外）仍有潛在洩漏風險；不把候選自動當已確認重複。確認重複的現有標籤衝突為 0。
- 現有真實 test 的垃圾類別只有 glass 23、other_recycling 91；有效殘留只有 none 12、food 18、liquid 16，not_assessable 0。資料驗收完成後需按固定 split 重新檢查，不保證每類都有足夠樣本。

詳見 [readiness.json](artifacts/v2/readiness.json)、[issues.csv](artifacts/v2/issues.csv) 與 [未解近似候選](artifacts/v2/unresolved_near_duplicates.csv)。本次實際執行正式 run 命令，確認它因未驗收與必要缺類而拒絕啟動，未下載權重或建立正式 checkpoint。

## 環境與 GPU 實測

大型套件下載經系統權限流程核准後完成：torch 2.5.1+cu121、torchvision 0.20.1+cu121；CUDA runtime 12.1，NVIDIA driver 551.76。GPU 為 NVIDIA GeForce GTX 1650，4,096 MiB、compute capability 7.5。不是只憑 nvidia-smi 宣稱通過。

FP32 實際試跑：

- 224×224、batch size 8、num_workers 0、AMP 關閉。
- 使用 train 中 8 張圖片，stage1／stage2 各 3 次更新，不接觸實際 test。
- 兩頭輸出皆為 8×4；各階段只有骨幹及對應分類頭更新，凍結頭權重不變。
- loss／gradient／參數均有限，checkpoint 的模型、optimizer、scheduler、scaler 與 RNG 可重載，重載推論完全一致。
- 核心試跑約 **2.93 秒**（不含 Python／CUDA 初次載入時間），峰值 PyTorch allocated 顯存 **898.8 MiB**，**OOM=false**。這不是完整訓練的時間或顯存保證。

[FP32 原始結果](artifacts/v2/smoke.json)。AMP 另做短程檢查時出現 **Non-finite gradient**，未通過；[AMP 失敗結果](artifacts/v2/smoke_amp.json) 已保存。未擅自降低 scaler 或重試到通過，不宣稱 AMP 加速或穩定，繼續使用預設關閉 AMP。AMP 未通過不影響已通過的 FP32 證明。

## 測試與完整性

訓練流程 **9 項測試通過**，未跳過模型測試：

- 明確殘留轉換、unknown 證據指紋、pending／generated 提示詞不能轉標籤。
- 群組不跨 split／stage，生成與來源一致；確認重複不跨 group。
- 固定分配可重現、版本重用、不修改原 labels、舊 manifest 的變更偵測。
- 四類指標與零樣本處理、兩頭輸出維度、無效殘留梯度為零、兩階段預期參數更新。
- 隔離的微型模型／合成資料檢查 epoch 中斷接續：權重、optimizer 及重要歷史欄位與不中斷結果一致。
- 固定驗證指標時，兩階段各在 epoch 6 停止（初次改善＋5 次無改善）；stage1_best 未被 stage2 覆寫，stage2 使用新 optimizer。
- 隔離合成 test 驗證最終鎖定與多圖推論重現。這些合成測試指標不是本專題模型結果，暫存測試資料已清理。

既有 dataset_generate 的 **9 項回歸測試也通過**。

逐一核對 2,548 張實際圖片 SHA-256 與既有 inventory 一致，labels.csv 與修改前指紋一致；確認 group 跨 split／stage 數為 0，v1／v2 分配一致，沒有正式 runs／checkpoint，沒有用實際 test 做模型評估。[完整驗證結果](artifacts/v2/validation_report.json) 保存證據。

建立與重用版本前備份 labels.csv、資格清單及現有切分／相關紀錄，備份位置見 [metadata.json](artifacts/v2/metadata.json)。原有審圖／生成程式與資料未重做，無原圖或人工標籤修改。

## 正式訓練的下一步

先完成 pending 的驗收及必要類別資格確認；本次不代替人工審核，也不把問題圖直接當有效資料。完成後使用原 partition 建立 v3，再執行已授權的完整流程：

```powershell
.\.venv\Scripts\python.exe training\workflow.py prepare --version v3 --reuse-partition training\artifacts\v2\partition.json
.\.venv\Scripts\python.exe training\workflow.py run --manifest-dir training\artifacts\v3 --run-dir training\runs\experiment_v3 --allow-weight-download
```

此命令先做對應資料版本與設定的 GPU 短程驗證，再訓練每階段最多 30 epoch、patience=5，最後才鎖定兩個 best 做 test。checkpoint、操作與接續命令見 [README](README.md)。網站仍未實作。
