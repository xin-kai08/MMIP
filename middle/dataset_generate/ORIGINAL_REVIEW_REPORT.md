# 五類容器原圖全量複核（2026-10-17）

本次只複核五類目標容器的 origin=original 全部圖片，不生成新圖、不訓練模型、不修改 generated 的既有審核欄位。閱讀專案說明、審核程式及實際 labels.csv 後，先建立備份，再透過 50 頁原尺寸聯絡表逐張看完 1,250 張，另針對透明液體、材質與細小痕跡有歧義的圖片放大檢查。

工作開始時，實際檔案中的五類原圖已無 pending：approved 共 1,057 張、excluded 共 193 張。本次仍重新檢查所有狀態，沒有只處理 pending 或依檔名推論。

## 備份與修改範圍

- [作業前完整 labels.csv 備份](dataset_workflow/backups/labels_before_original_review_2026-10-17T073615.995464_0000.csv)
- [本輪基準副本](dataset_workflow/reviews/original_review_20261017/baseline.csv)
- [最終驗證結果](dataset_workflow/reviews/original_review_20261017/final_verification.json)

原先 193 張 excluded 全數維持排除，另外 49 張因非目標物品、材質／細類明顯不符、圖表或教學拼貼等原因排除。五類原圖合計 1,008 張 approved、242 張 excluded，pending=0。

538 張原圖的殘留、適用性、生成候選或審核狀態有實質修正；1,250 張均追加本次看圖理由與獨立複核來源欄位。原 notes 原文（包含既有亂碼）保留為前綴，原審核者及審核時間欄位未覆蓋。可讀的新理由與修改前後值另行保存，沒有猜測還原亂碼。

全部 2,522 張圖片的檔案清單與 SHA-256 相對本輪開始完全一致；沒有刪除、覆寫或改名。其他五類原圖及全部 22 張 generated 的既有欄位值維持不變。為原圖複核新增的追蹤欄位，在非本輪樣本中為空白；group_id 與 split 均未重算或變動。

## 各類複核結果

下表殘留與 unknown／mixed 數量只計算 approved 的原圖，尚未做完全重複代表圖折算。

| folder | approved | excluded | pending | none | food | liquid | unknown 空白 | mixed 空白 | eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| glass_beverage_bottles | 236 | 14 | 0 | 74 | 0 | 86 | 60 | 16 | 45 |
| paper_cups | 173 | 77 | 0 | 2 | 1 | 20 | 150 | 0 | 0 |
| plastic_water_bottles | 146 | 104 | 0 | 2 | 0 | 70 | 74 | 0 | 0 |
| plastic_food_containers | 234 | 16 | 0 | 45 | 103 | 0 | 70 | 16 | 21 |
| styrofoam_food_containers | 219 | 31 | 0 | 52 | 28 | 0 | 134 | 5 | 38 |
| **合計** | **1,008** | **242** | **0** | **175** | **132** | **176** | **488** | **37** | **104** |

不適用（no）樣本多為圖表、教學及非容器，這輪已排除，故 approved/no 為 0；完整交叉統計含 excluded 的各種殘留／適用性值，見 [狀態與標籤交叉表](dataset_workflow/reviews/original_review_20261017/status_residual_candidate_counts.csv)。

## 生成來源適合度

eligible 僅用於已審核、單一主要容器清楚、可確認無殘留且新增殘留能合理可見的原圖。unknown、已有飲食內容、混合情境、遮擋、多容器及材質待查均不列 eligible。

| folder | eligible 圖片 | 對應群組 | 尚未被既有生成任務使用的來源 |
|---|---:|---:|---:|
| glass_beverage_bottles | 45 | 40 | 43 |
| paper_cups | 0 | 0 | 0 |
| plastic_water_bottles | 0 | 0 | 0 |
| plastic_food_containers | 21 | 20 | 18 |
| styrofoam_food_containers | 38 | 38 | 36 |
| **合計** | **104** | **98** | **97** |

紙杯只有少數多杯俯視照片能確認 none，沒有同時滿足本輪嚴格生成條件的單杯來源。多數紙杯只露出內壁上方；塑膠水瓶常有標籤遮擋、手部遮擋、透明液體／反光或低解析度歧義，因此不強行保留 eligible。review 仍可作日後個別核實的候選，但不會進入生成任務。

以上是來源品質清點，不是本輪生成任務；本次沒有排入或執行新的生成。

## 主要修正與保留原則

- 看不見內底的紙杯、閉蓋泡棉餐盒不再因外觀乾淨而標 none。
- 已有可見飲料的瓶子移出 eligible；不以品牌、背景或商品照慣例推定液體。
- 水果浸泡飲料、湯與食物、食物碎屑加明顯積液，記為 yes＋空白並註記 mixed。
- 原本 `plastic_food_containers/Image_94.png` 的完整餐食修正為 food；`styrofoam_food_containers/Image_190.png` 可見橘色食物／醬痕，修正原 none／eligible。
- 明顯 PET 瓶出現在 glass 細類、透明薄壁塑膠盒出現在 styrofoam 細類、紙纖維盒與非容器用品等，記錄排除原因，沒有搬動圖片或自行改 waste_class 對照。
- 同細類的完全相同像素圖片已交叉核對，殘留判斷衝突為 0。原先 excluded 保留排除，不因本次看圖認為清楚就恢復 approved。

food／liquid 數量包含照片中已裝食物或飲料的內容情境，不代表都是「用過後只剩少量殘留」；每筆 notes 說明這項差異，後續建模應另外檢視場景分布。

## 程式與篩選規則

1. `approved` 表示圖片完成審核。unknown／no＋空白可核准；明確 mixed 也可記 yes＋空白並核准。
2. 殘留訓練及比例統計必須同時滿足 approved、residual_applicable=yes，以及 residual ∈ {none, food, liquid}。unknown、no、mixed 與其他空白均排除，沒有硬填 none。
3. [residual_training_manifest.csv](dataset_workflow/reports/residual_training_manifest.csv) 與 usable_manifest.csv 是殘留三分類清單；classification_manifest.csv 另供一般垃圾類別分類，兩種用途分開。
4. `generation_eligible()` 僅接受 approved／original／yes／none／eligible；排任務及 reserve 均檢查，舊任務若來源已不合格也不能直接執行。
5. 本次 `review_originals.py` 保存逐張觀察，要求完整覆蓋與 labels 基準未變才一次寫回；完成後重跑 apply 會跳過，避免覆蓋後續人工標籤。

最新 [balance.csv](dataset_workflow/reports/balance.csv) 已依合格且去重的原圖、以及未更改的既有生成圖標籤重新計算。它與本報告「原圖逐張數」的統計基準不同；原始場景也含滿裝飲食，差額不能直接取代資料品質判斷。本輪沒有依差額生成圖片。

## 修改明細與驗證

- [逐張複核明細：前後標籤、候選、原備註、新備註與原因](dataset_workflow/reviews/original_review_20261017/review_details.csv)
- [逐欄修改明細](dataset_workflow/reviews/original_review_20261017/field_changes.csv)
- [各類數量摘要](dataset_workflow/reviews/original_review_20261017/summary.csv)
- [全部 1,250 筆看圖觀察與頁面索引](dataset_workflow/reviews/original_review_20261017/observations.json)
- [聯絡表清單與每頁對應原圖路徑](dataset_workflow/reviews/original_review_20261017/sheets.json)

8 項回歸測試通過，涵蓋 approved unknown／no／mixed 不進入殘留訓練或比例、禁止不確定來源列 eligible、核准前不能排生成、失效舊來源不能 reserve，以及原有標籤保留、去重、避撞與接續行為。最終驗證另外確認全量覆蓋、原先 excluded 保留、原備註與審核者保留、生成圖及範圍外欄位不變、全部圖片不變、分組切分不變與 UTF-8 BOM。
