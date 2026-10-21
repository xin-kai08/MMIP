# 保麗龍食物殘留批次生成紀錄（2026-10-17）

使用者確認先前試作後，授權依五類容器各自的殘留比例擴充。本批使用內建 image_gen 編輯工具，實際生成並保存 26 張保麗龍食品容器的食物殘留照片；沒有使用付費 API、貼圖或一般增強取代生成。

## 數量與驗收

| 類別 | 本次新增 | 原因 |
|---|---:|---|
| glass_beverage_bottles | 0 | 已確認有殘留數量高於無殘留 |
| paper_cups | 0 | 已確認有殘留數量高於無殘留 |
| plastic_water_bottles | 0 | 已確認有殘留數量高於無殘留 |
| plastic_food_containers | 0 | 已確認有殘留數量高於無殘留 |
| styrofoam_food_containers | 26 | 生成前去重可用資料為無殘留 54、有殘留 28 |

新圖存於 `../dataset/styrofoam_food_containers/`，編號在 Image_255.png 至 Image_288.png 之間，共 26 張。跳號是已預留但失敗／跳過的任務，不代表遺失圖片；不重用預留編號、不覆寫檔案。

全部新圖均已實際看圖初標為 yes／food、未見明顯積液，**review_status=pending，待人工複核**。這是初標，不是驗收通過；尚未加入殘留訓練清單或正式平衡數量。若 26 張全數驗收為 food，保麗龍可用資料才達到 54：54；若排除部分結果，需依驗收後統計重新計算缺額。

## 看圖及儲存標籤

[本批原圖／生成圖對照頁](dataset_workflow/balance_preview/index.html) 可用瀏覽器直接開啟，僅供查看。

要修改標籤，在專案根目錄執行：

```powershell
.\.venv\Scripts\python.exe dataset_generate\waste_workflow.py serve
```

開啟 http://127.0.0.1:8765，選 `styrofoam_food_containers`、`generated`、`pending`。逐張確認，按「儲存」才寫入。不要用直接開啟 HTML 的方式操作標註介面。

需特別複核的結果包括：

- Image_256、Image_257、Image_285：背景白邊／構圖改變。
- Image_265、Image_284：原有下方圖庫文字未保留，建議排除或改選來源。
- Image_273：盒蓋內側也加入食物，建議排除或重新製作。
- Image_261、Image_263、Image_267、Image_269：角度、內底細節、食物自然度或物品比例需比對原圖。

所有逐張意見見 [品質初檢清單](dataset_workflow/reports/balance_visual_qa.csv)。圖片可見食物不代表構圖與細節一定合格。

## 提示詞、失敗與接續

主要提示詞要求保留容器種類、材質、形狀、角度、背景與光線，在可見內底加入少量清楚米粒、碎屑、薄醬痕；目標約 10–15% 內底覆蓋，避免積液，不遮擋盒緣或外形。提示比例不是實測值。替代來源另外強調只編輯下盒、上蓋保持乾淨及保留既有文字。Image_257 的額外視角限制、失敗請求的實際提示詞另記 effective_prompt。

共 34 個任務：26 個 success、8 個 failed。8 個中只有 1 個是影像工具拒絕輸出；其餘 7 個在送交工具前，因材質疑義、浮水印／文字保留疑慮或重複場景跳過。失敗原因均保留，不自動重試。

- [任務與完整提示詞](dataset_workflow/reports/balance_batch_tasks.csv)
- [失敗／跳過清單](dataset_workflow/reports/balance_batch_failures.csv)
- [權威任務狀態](dataset_workflow/generation_tasks.json)
- [逐事件紀錄](dataset_workflow/generation_log.jsonl)

每張輸出立即透過 reserve／complete 保存，使用 exclusive create，記錄來源、hash、提示詞、輸出及狀態。已保存但 pending 的成果會占用待驗收缺額，重跑 balance 排程不會在人工確認前繼續補圖。成功存檔不代表品質通過。

## 核對與程式調整

來源來自 26 個不同 group；新圖繼承來源 group_id 與 split，分布 train 19、val 5、test 2。原有 2,522 張圖片及其標籤欄位均未變動；總圖片數為 2,548，其中 original 2,500、generated 48。labels.csv 保持 UTF-8 BOM，每次寫入前備份。

修正新增圖造成既有 group_id 變動的情況，既有單一群組 ID 保留；新排程以來源群組去重，並將已保存待審成果納入占用量。9 項回歸測試通過，重跑 balance 排程為 Queued: 0。[本批核對結果](dataset_workflow/reports/balance_batch_verification.json) 保存備份路徑與統計。

本次只擴充資料，沒有訓練模型。合成測試圖片的效果不能代表真實照片效果，仍須分開檢查真實殘留測試資料。
