---
name: panorama-workflow
description: Stitch overlapping local photos into a saved left-to-right panorama. Use for local photo selection, optional exposure correction, stitching and PNG export.
---

# 本機全景拼接

輸入是工作區內兩張有重疊的照片，或包含這兩張照片的資料夾。先確認左、右圖的來源與順序。Quiz 3 只收到資料夾時，呼叫 `get_local_photos`，再用回傳的真實圖片 ID。

依使用者要求決定是否校正。要求保留原本亮度時，跳過 `match_exposure`，左、右原圖依序交給 `stitch_images`。需要校正時，以其中一張作基準，後續用回傳的校正圖 ID 取代目標圖。

拼接成功後，若使用者要求存檔，以全景 ID 呼叫 `save_image`。能直接使用專案的 Quiz 2 工具時沿用其拼接與存檔介面，輸出位置依本輪工作區設定。確認回傳的 PNG 確實可讀，記錄輸入次序、是否執行亮度校正、全景尺寸與路徑。拼接失敗時指出實際錯誤，避免把原圖或中間圖當作全景成品。
