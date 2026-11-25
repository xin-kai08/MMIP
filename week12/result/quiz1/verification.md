# Quiz 1 驗證報告

驗證日期：2026 年 11 月 25 日（Asia/Taipei）

## 已驗證

- Notebook 透過 nbclient 執行，設定區的 `sys.executable` 顯示 `D:anaconda3_newenvsMMIPpython.exe`（Python 3.13.13）。在 VS Code 可選擇同一個 MMIP kernel。
- Notebook 留存的本機測試輸出顯示四項通過，涵蓋篩選、排程、UTF-8 匯出和 Agent 防護。這段測試使用測試資料，真實 API 的結果記在連線測試與工具展示。
- Groq 連線測試與 Tavily basic 搜尋成功。五個工具均有直接呼叫的輸出，`result/quiz1/` 裡保留了匯出的行程 Markdown。
- `.env` 已列入 `.gitignore`。

## 尚待驗證

- 先前 Agent 執行曾遇到 Groq HTTP 413 與 429。Notebook 留存的 A1、A2、B1、B2 和三輪追問結果均出現 HTTP 429。
- 四題合計有成功呼叫 `search_places` 和 `filter_by_category`。Agent 展示仍缺 `filter_by_area`、`build_itinerary` 和 `export_itinerary` 的成功紀錄。
- 六組模型與提示技巧比較共有 0 組完成。120b 的「直接指令」組執行了搜尋與兩次類型篩選，之後也遇到 HTTP 429。

Groq 用量限制解除後，可先從設定與連線測試開始，再依序重跑四題、三輪追問與六組比較。每次重新匯出會新增一份行程檔。
