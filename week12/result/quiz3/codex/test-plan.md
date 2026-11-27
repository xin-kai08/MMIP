# VS Code Codex Skill 測試

狀態：待在遠端 VS Code Codex 對話手動執行。這裡保存待貼的輸入與驗收方式。特化 Agent 的輸出另存於 `result/quiz3/agent/`。

## 測試 1：全景拼接

```text
$panorama-workflow
工作根目錄是 ~/MMIP/week12。請依這份 Skill，把 data/quiz2/set1/left.jpg 與 data/quiz2/set1/right.jpg 依左、右順序拼接。保留原本亮度，跳過 match_exposure，沿用 Quiz 2 的拼接與存檔工具。所有檔案更動、腳本與輸出限在 week12，成品及紀錄放在 result/quiz3/codex/，保留 Quiz 1、Quiz 2 的程式與成果。請回讀 PNG 驗證，將輸入檔、實際讀取的 Skill、工具與順序、OpenCV 回傳狀態、輸出路徑和尺寸寫進 result/quiz3/codex/panorama-run.md。若失敗，記錄實際錯誤。
```

截圖請包含 `$panorama-workflow` 的選取或讀取紀錄、實際拼接與存檔回傳，以及 VS Code 中開啟的輸出全景。建議放在 `result/quiz3/codex/panorama-skill.png`。

## 測試 2：比較圖

```text
$image-comparison-report
工作根目錄是 ~/MMIP/week12。請依這份 Skill，使用 data/quiz2/set1/left.jpg、data/quiz2/set1/right.jpg，以及 result/quiz3/codex/panorama-run.md 裡第一輪實際產出的全景 PNG。請將三圖排成一張比較圖，標註每張圖原始寬 × 高。排版請自行撰寫 Python，將腳本和比較圖存到 result/quiz3/codex/，並回讀輸出的 PNG 驗證。把本輪實際輸入、讀取的 Skill、腳本與成品路徑和尺寸標籤寫進 result/quiz3/codex/comparison-run.md。所有更動限在 week12。若第一輪沒有可用的全景，記錄原因並停止。
```

截圖請包含 `$image-comparison-report` 的選取或讀取紀錄、生成腳本或執行輸出，以及三張圖和原始尺寸標籤可見的比較圖。建議放在 `result/quiz3/codex/comparison-skill.png`。
