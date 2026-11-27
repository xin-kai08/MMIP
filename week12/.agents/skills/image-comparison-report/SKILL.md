---
name: image-comparison-report
description: Create a labeled PNG comparison of a left original, a right original, and the resulting panorama. Use for a three-image report with original pixel dimensions.
---

# 影像比較圖

輸入為左原圖、右原圖、已存成 PNG 的全景圖，三張檔案皆須可讀。輸出為一張比較圖 PNG，保留三張圖各自的原始檔。

先查本輪已註冊 Function 是否同時支援三圖排版與尺寸文字。若沒有合適的 Function，自行撰寫 Python，讀取本次提供的三個實際路徑，並只寫到指定的輸出路徑。可使用 Pillow。排版方式、縮放與配色由當次 Agent 決定。

驗收時確認三圖均清楚可見且未改變長寬比例，每張圖各有不重疊、清楚的角色與尺寸標籤。標籤須標原檔寬 × 高，不能用縮圖尺寸替代。最後回讀輸出檔並確認是可讀的 PNG，回報腳本、PNG 路徑及三張原圖的尺寸。
