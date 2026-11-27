# Panorama run

## 輸入與設定

- 工作根目錄：`/root/MMIP/week12`
- 輸入 1（左）：`data/quiz2/set1/left.jpg`
- 輸入 2（右）：`data/quiz2/set1/right.jpg`
- 實際讀取的 Skill：`.agents/skills/panorama-workflow/SKILL.md`
- 亮度處理：依要求保留原本亮度，`match_exposure` 未呼叫。
- 拼接模式：Quiz 2 `ImageTools.stitch_images`，OpenCV `Stitcher_PANORAMA`。
- 存檔方式：Quiz 2 `ImageTools.save_image`，暫時將其 `RESULT_DIR` 指向 `result/quiz3/codex/`。
- OpenCV 版本：`5.1.0`

## 工具與順序

1. `ImageTools.register_photo(left.jpg)`
2. `ImageTools.register_photo(right.jpg)`
3. 跳過 `ImageTools.match_exposure`
4. `ImageTools.stitch_images([left_id, right_id])`
5. `ImageTools.save_image(panorama_id, "panorama.png")`
6. Pillow `Image.open` 回讀、限制格式為 PNG、`verify()`，再重新開啟並 `load()` 驗證像素與尺寸。

## 實際結果

- 前置啟動重試：首次隔離執行尚未進入拼接即失敗，實際錯誤為 `ModuleNotFoundError: No module named 'other_code'`；將工作根目錄加入 `sys.path` 後重跑。
- 左圖 ID：`photo:data/quiz2/set1/left.jpg`
- 右圖 ID：`photo:data/quiz2/set1/right.jpg`
- 傳入拼接的順序：`["photo:data/quiz2/set1/left.jpg", "photo:data/quiz2/set1/right.jpg"]`
- `stitch_images` 回傳：`{"cache_status": "off", "height": 1368, "image_id": "panorama:3edcee1d", "ok": true, "opencv_executed": true, "opencv_status": 0, "source_ids": ["photo:data/quiz2/set1/left.jpg", "photo:data/quiz2/set1/right.jpg"], "width": 1774}`
- OpenCV 是否實際執行：`True`
- OpenCV 回傳狀態：`0`
- `save_image` 回傳：`{"height": 1368, "image_id": "panorama:3edcee1d", "ok": true, "path": "result/quiz3/codex/panorama_75ee1c23.png", "width": 1774}`
- 輸出路徑：`result/quiz3/codex/panorama_75ee1c23.png`
- 工具回傳尺寸：`1774 × 1368`
- PNG 回讀驗證：成功（格式 `PNG`、模式 `RGB`）
- PNG 回讀尺寸：`1774 × 1368`
- 執行狀態：成功。
