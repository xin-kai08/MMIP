# 本次資料整理與生成試作（2026-10-15）

本文件保留首次整理及 22 張試作的歷史結果。2026-10-17 後續新增 26 張保麗龍食物殘留圖，見 [批次生成報告](BALANCE_GENERATION_REPORT.md)；最新總圖片數為 2,548，generated 共 48 張，新批次尚待人工驗收。

已檢查專案及上層適用 AGENTS.md，未找到。沒有額外未知類別。使用本專題指定 waste_class 對照，不代表已驗證地方垃圾處置規則。

2,500 張原圖皆為 256×256 且可正常解碼，原圖 SHA-256 相對首次掃描全數一致。未刪除、覆寫或重新命名原圖。生成圖 22 張為 1254×1254，存入對應物品細類資料夾；解析度與來源差異應在未來建模前處理，以免形成捷徑特徵。

| folder | 原圖 | 生成圖 | 生成檔名 |
|---|---:|---:|---|
| cardboard_boxes | 250 | 0 | |
| food_waste | 250 | 0 | |
| glass_beverage_bottles | 250 | 4 | Image_251–254.png |
| paper_cups | 250 | 6 | Image_251–256.png |
| plastic_cup_lids | 250 | 0 | |
| plastic_food_containers | 250 | 4 | Image_251–254.png |
| plastic_straws | 250 | 0 | |
| plastic_trash_bags | 250 | 0 | |
| plastic_water_bottles | 250 | 4 | Image_251–254.png |
| styrofoam_food_containers | 250 | 4 | Image_251–254.png |

全部以內建 imagegen 編輯原圖，沒有另外啟用付費 API。首輪每類兩張，接著依使用者要求「每張殘留更明顯」另做每類兩張，最後紙杯依 Image_30 的清楚咖啡液面再做兩張。舊版本完整保留。最新紙杯為 [Image_255.png](../dataset/paper_cups/Image_255.png)、[Image_256.png](../dataset/paper_cups/Image_256.png)；杯口下方仍有明顯空間，杯身可辨。

[來源與各版本對照總覽](dataset_workflow/pilot_preview/index.html)；完整提示詞、來源與輸出路徑見 [生成任務 CSV](dataset_workflow/generation_tasks.csv) 及 generation_log.jsonl。

工具成功存檔 22 張，工具失敗紀錄 0 張；初檢需修正 2 張：首輪 plastic_water_bottles/Image_252 的透明液體／液面不清，及 plastic_food_containers/Image_252 的原有文字條被改動。它們仍保留 pending 並列 candidate exclude，不列合格樣本。後續版本改換適合來源或更清楚的液體呈現。品質與人工作業以 labels.csv 為準。

完全重複配對 100 組，原圖合組後有 2,403 個群組；未自動刪圖。原圖近似候選 803 組；加入生成圖後總候選 841 組。近似配對均待人工確認，dHash 候選不等於已確定重複，可能漏掉裁切、翻轉等變形。

| 來源 | train | val | test |
|---|---:|---:|---:|
| original | 1750 | 500 | 250 |
| generated | 17 | 3 | 2 |
| 合計 | 1767 | 503 | 252 |

固定 seed=42；生成圖繼承來源 group_id 與 split。所有群組內 split 一致。切分目前仍為暫定：先完成人工近似圖確認，必要時重新按組切分。

| 初步殘留標籤（全部 pending） | 原圖 | 生成圖 |
|---|---:|---:|
| none | 8 | 0 |
| food | 1 | 8 |
| liquid | 8 | 13 |
| 空白 | 2483 | 1 |

原圖空白分為：不適用 no 1,000 張、unknown 1,478 張、適用但尚不能確認 yes 5 張。沒有將未標註原圖自動當成 none。已記錄 352 張原圖及 22 張生成圖的初步看圖意見，均待人工複核；其餘沒有編造殘留標籤。

目前 approved=0，因此不聲稱已達成可用資料 1:1，也不能把 balance.csv 的暫時差額當最終補圖量。五種容器需要完成原圖複核後各自計算，非容器不納入。真實殘留 test 目前沒有已核准樣本；生成圖測試結果不能代表真實照片效果。

報告入口：

- [各類、來源、殘留、split、狀態統計](dataset_workflow/reports/counts.csv)
- [待複核圖片](dataset_workflow/reports/pending_review.csv)
- [原圖完全重複配對](dataset_workflow/reports/exact_duplicates.csv)
- [原圖近似候選](dataset_workflow/reports/original_near_duplicates.csv)
- [候選排除清單](dataset_workflow/reports/candidate_exclusions.csv)
- [生成需修正清單](dataset_workflow/reports/generated_needs_rework.csv)
- [生成失敗清單（目前空）](dataset_workflow/reports/generation_failures.csv)
- [五類容器的可用數量與差額](dataset_workflow/reports/balance.csv)
- [完整驗證結果](dataset_workflow/reports/validation.json)

5 項回歸測試通過。已驗證重掃前後 labels.csv 位元組一致、UTF-8 BOM、原圖內容不變、生成輸出 checksum、同組防洩漏、成功接續、編號避撞與禁止覆寫。本機 HTTP 已驗證 HTML、圖片、資料 API，以及拒絕無 token／無效標籤的更新。工具未提供可連線瀏覽器，尚未完成瀏覽器畫面與點擊驗證。

程式與資料工作目錄已依使用者要求集中於 dataset_generate，labels.csv 位於 dataset 內；tmpuosza_cb 原樣搬入，未刪除。Python 虛擬環境 .venv 留在專案根目錄，以維持環境可用。

下一步：依 [操作說明](README.md) 啟動本機複核介面，先確認生成品質、原圖殘留及近似圖，再重算切分與各容器補圖差額。未訓練模型、未開發正式網站。
