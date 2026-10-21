# 人工殘留連動與模型文件更新 — 2026-10-20

## 修改內容

人工選單共用於預測前 GT、一般回饋及評估修正回饋。垃圾未選時殘留停用；general／food_waste 顯示固定「不適用」、選擇時帶入 not_assessable 並取消殘留確認；glass／other_recycling 保留未選與四類選項。答案與確認分開操作，變更答案取消該項確認；離開固定類別或清空垃圾會清空殘留。操作草稿不寫 DB，仍只在明確提交時新增。

後端新提交只接受 general／food_waste 的殘留 null 或 not_assessable；已確認必須有值，兩任務仍可獨立確認。無 schema 遷移、不批次改標。舊不相容值在 GT、最新摘要與歷史顯示原值及提示，修正只追加新回饋，不改原 GT。自動帶入不代表自動確認，也不代表所有一般垃圾都不可能有殘留。

本次沿用先前已完成的交易內防重複提交、原始 GT 鎖定、來源分流及草稿刷新保護，沒有另做第二套儲存流程。新增純前端 draft helper 與後端 schema 驗證，未依模型預測限制人工選項。

## 文件核對

根 README 補完整模型概述／Mermaid／兩階段／loss／optimizer／scheduler／實際結果；training/README 全面依 v3 現況整理，提供設定與可調項目表，保留歷史 RUN_REPORT 的原文與語境。修正舊 README「未開始訓練／未開發網站」、v2 目錄敘述與現有產物的矛盾；同時說明程式 CLI 的路徑預設仍是 v2，不能誤以為程式也已改。

核對重點：

- EfficientNet-B0 官方 IMAGENET1K_V1、1280 維、兩個 Dropout(.2)＋Linear(1280,4)，兩任務類別順序與 logits／softmax。
- stage1／stage2 更新與凍結、BatchNorm running buffers、Dropout train／eval；凍結頭不等於消除骨幹造成的遺忘。
- 直接接 logits 的 masked cross_entropy；weight=None、label_smoothing=0、reduction=mean，無多任務加權 loss。
- AdamW 的兩組 LR、weight decay、betas／eps；stage2 重建 optimizer／scheduler；Plateau 的更新時機與實際參數。
- config 預設與 v3 checkpoint 的差異只有 allow_weight_download=false／true；initial LR 與 best／last 降低後 LR 分開記錄。
- v3 stage1 訓練 636 張；stage2 分配 661 張，實際殘留有效訓練 416 張。固定 70／20／10、seed=42、真實原圖／生成圖、mask、epoch／early stopping／checkpoint 接續限制均說明。
- 23／28 個 epoch，best 在 18／23；原圖 val 選模 F1 95.2612%／88.8777%。垃圾 val 下降 2.8441 個百分點、test 下降 2.4532 個百分點，沒有混用。
- 原圖及 generated 的 val／test 分列；僅 4 張 generated test、缺類與固定四類 Macro-F1 的限制，以及 820 未解近似候選／688 unknown 資格 mask 保留。

文件中的 optimizer／scheduler／loss 預設以本機安裝版本、checkpoint state 和實際函式交叉核對；數值表與既有 val／test JSON 比對通過。另建隨機初始化模型僅檢查結構／模式／參數組，沒有 forward 訓練、backward 或 optimizer step，沒有再次執行 smoke、正式 train 或 final-test。

## 實際驗證

| 驗證 | 結果 |
|---|---|
| website.test_website | 11 項通過；包含兩來源新規則、獨立確認及統計、舊不相容紀錄、防重複並發、GT 鎖定及單張真實 CUDA 推論 |
| TypeScript＋Vite build | 通過，已更新 dist |
| 新連動無頭 Chrome | 17 個情境通過，page errors 0 |
| 既有回饋無頭 Chrome 回歸 | 17 個情境通過，page errors 0 |
| 桌面／手機截圖 | 已實際查看 |
| 文件參數／指標 | 與程式、config、checkpoint 及實驗 JSON 一致 |
| 受保護資料 | 2,632 個 dataset／training 檔案 SHA-256 前後一致；排除本次明確修改的 training/README 及 Python bytecode |
| 訓練步數 | 0；沒有更動模型、訓練程式、config、manifest、checkpoint 或正式測試 |
| 隔離環境 | 新建 DB／圖片／Chrome profile，實際模型使用 CPU；測試正常關閉並清理本次暫存資料，未寫入正式使用者紀錄 |

新連動測試的舊不相容回饋是由隔離測試服務插入的 fixture；該測試 route 只在 runner 的臨時 app 註冊，不存在於正式 create_app。模型輸出皆來自真實 checkpoint，沒有用 fixture 假裝預測。

證據：[linkage_browser.json](verification/linkage_browser.json)、[feedback_browser.json](verification/feedback_browser.json)、[documentation_check.json](verification/documentation_check.json)、[訓練產物摘錄](verification/training_doc_evidence.json)。來源檔案雜湊清單在 verification/linkage_protected_before.json。測試截圖在 verification/screenshots/linkage/ 及 feedback/。

## 修改檔案與套用

- 前端：frontend/src/annotation.ts、frontend/src/main.tsx、frontend/src/style.css。
- 後端：schemas.py；沿用既有 app.py 儲存交易，不改資料庫結構。
- 驗證：test_website.py、verify_feedback.py、frontend/verify_linkage.mjs、verify_feedback.mjs、verify_browser.mjs 及上述驗證產物。
- 文件：根 README.md、training/README.md、website/README.md 及本報告。先前 ANNOTATION_FIX_REPORT.md 作為當次紀錄保留。

前端已重建；現有 Python 服務需重新啟動才會載入後端驗證。在原終端 Ctrl+C，再執行並重新整理頁面：

~~~powershell
cd F:\project\MMIP\middle
.\.venv\Scripts\python.exe -m website.run
~~~

開啟 http://127.0.0.1:8000。不需重裝環境、遷移資料庫或重新訓練。

重跑隔離驗證：

~~~powershell
.\.venv\Scripts\python.exe -m unittest website.test_website -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File website\frontend.ps1 build
.\.venv\Scripts\python.exe -m website.verify_feedback --scenario linkage
.\.venv\Scripts\python.exe -m website.verify_feedback
~~~
