from pathlib import Path
import nbformat as n
p=Path('main.ipynb')
b=n.read(p,as_version=4) if p.stat().st_size else n.v4.new_notebook()
c=[]
def md(s): c.append(n.v4.new_markdown_cell(s))
def cell(s,code):
 md(s); c.append(n.v4.new_code_cell(code))
md('# quiz 1\n\n旅遊行程助手：本機 Qwen3 工具呼叫 × Tavily basic search。只做 Quiz 1。')
cell('## 設定與匯入\nVS Code 選取 MMIP kernel，依 README 安裝 Transformers，首次使用會從 Hugging Face 下載權重。在根目錄 .env 設定 TAVILY_API_KEY。', '''import sys, json
from pathlib import Path
print('sys.executable =', sys.executable)
assert (Path.cwd()/'other_code'/'quiz1.py').exists(), '請從專案根目錄開啟 Notebook'
from other_code.quiz1 import DEFAULT_MODEL, TravelChat, TravelTools, ServiceError, connection_tests, show, compare
MODEL = DEFAULT_MODEL
MAX_ROUNDS = 12
def new_chat(): return TravelChat(model=MODEL, max_rounds=MAX_ROUNDS)
def safe_tool(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    except (ServiceError, ValueError) as exc:
        print(str(exc))
        return None''')
cell('## 本機小型測試\n使用標示為 fixture 的測試資料，驗證篩選、排不下、匯出不覆寫與 Agent 上限；不是 API 結果。執行後顯示測試是否通過。', '''import unittest
from other_code.test_quiz1 import ToolsTests
suite = unittest.defaultTestLoader.loadTestsFromTestCase(ToolsTests)
assert unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()''')
cell('## 連線測試\n對本機 Qwen 問 OK，Tavily 做一次 basic 搜尋，顯示實際結果或服務錯誤。', '''connections = connection_tests(MODEL)
print(json.dumps(connections, ensure_ascii=False, indent=2))''')
cell('## 逐一呼叫工具 1：search_places\n搜尋京都站甜點和購物，顯示候選 ID、摘要與來源。', '''direct = TravelTools()
searched = safe_tool(direct.search_places, '京都站', '甜點 購物')''')
cell('### 工具 2：filter_by_area\n以來源文字篩京都站，顯示符合候選。不是實測距離。', '''areas = safe_tool(direct.filter_by_area, '京都站')
area_ids = [p['id'] for p in (areas or {}).get('places', [])]''')
cell('### 工具 3：filter_by_category\n顯示甜點與購物的實際篩選結果。綜合介紹頁可能符合兩類。', '''desserts = safe_tool(direct.filter_by_category, '甜點', area_ids)
shopping = safe_tool(direct.filter_by_category, '購物', area_ids)''')
cell('### 工具 4：build_itinerary\n依篩選候選排兩小時，顯示估計停留、交通、未排入原因及營業待確認。候選不足會明確跳過。', '''d = (desserts or {}).get('places', [])
s = (shopping or {}).get('places', [])
if d and s:
    second = next((p for p in s if p['id'] != d[0]['id']), s[0])
    safe_tool(direct.build_itinerary, 120, [dict(place_id=d[0]['id'], activity='甜點', stay_minutes=45), dict(place_id=second['id'], activity='購物', stay_minutes=55)])
else:
    print('真實搜尋未取得兩類候選，請檢查連線後重跑本節。')''')
cell('### 工具 5：export_itinerary\n這格明確要求匯出示範行程，顯示 UTF-8 Markdown 路徑。資料夾自動建立，每次檔名不同；無行程會顯示原因。', 'direct_export = safe_tool(direct.export_itinerary)')
tasks=[('A1','幫我找京都站附近的甜點店，附上來源。'),('A2','我在京都車站周邊想吃點甜的，有哪些地方可以去？'),('B1','我在京都站附近只有兩小時，想先吃甜點再逛街，幫我排行程並存成Markdown。'),('B2','幫我安排京都車站周邊的120分鐘行程，順序是甜點、購物，最後匯出成Markdown檔。')]
for label,task in tasks:
 cell(f'## 評分題 {label}\n建立全新 session 執行「{task}」。顯示最終回答、來源、各輪實際工具／參數／回傳／耗時，以及匯出路徑。',f'chat_{label} = new_chat()\nresult_{label} = chat_{label}.send({task!r})\nshow(result_{label})')
cell('### 五工具覆蓋檢查\n從四題真實工具紀錄統計成功呼叫，列出尚缺工具，不把未完成當通過。', '''required = {'search_places','filter_by_area','filter_by_category','build_itinerary','export_itinerary'}
actual = {t['tool'] for r in [result_A1,result_A2,result_B1,result_B2] for t in r['trace'] if not t['result'].get('error')}
print('成功呼叫:', sorted(actual))
print('尚缺:', sorted(required-actual))''')
for i,task in enumerate(['找京都站附近的甜點和購物地點','沿用剛才的地點排兩小時，先吃甜點再逛街','把剛才的行程存成Markdown'],1):
 cell(f'## 多輪追問 {i}\n「{task}」。沿用同一 chat 的候選與最近行程，顯示回答與實際工具紀錄。只有第三句要求匯出。',('chat = new_chat()\n' if i==1 else '')+f'turn{i} = chat.send({task!r})\nshow(turn{i})')
cell('## 進階比較：固定真實搜尋證據\n搜尋一次，六組重播同份真實結果。回傳明確標示 shared_real_search_snapshot，避免搜尋差異干擾，不是模擬資料。', '''snapshot_tools = TravelTools()
snapshot_result = safe_tool(snapshot_tools.search_places, '京都站', '甜點 購物')
snapshot = snapshot_tools.places if snapshot_result else None''')
cell('### 2 模型 × 3 Prompting\n固定 B1 任務，每組新 session。顯示完成、工具順序、次數及耗時；免費額度錯誤如實保留。完成檢核：五工具成功、兩種活動順序、120 分鐘內、有行程且匯出。此檢核不是店家品質評分。', '''from IPython.display import display, Markdown
comparison_rows, comparison_runs = [], []
if snapshot:
    comparison_rows, comparison_runs = compare(snapshot, '我在京都站附近只有兩小時，想先吃甜點再逛街，幫我排行程並存成Markdown。')
    header = '|模型|技巧|完成|工具順序|次數|秒數|錯誤|\\n|---|---|---|---|---|---|---|\\n'
    table = '\\n'.join(f"|{r['model']}|{r['technique']}|{r['completed']}|{' → '.join(r['tool_order'])}|{r['calls']}|{r['seconds']}|{r['error'] or ''}|" for r in comparison_rows)
    display(Markdown(header + table))
else:
    print('缺少真實搜尋資料，六組尚未執行；修復 Tavily 後重跑。')''')
cell('### 解讀一組真實工具紀錄\n優先選完成的一組，逐輪說明工具目的並顯示參數、結果與耗時；若全部失敗，展示實際失敗組。', '''if comparison_runs:
    chosen = next((i for i,r in enumerate(comparison_rows) if r['completed']), 0)
    print('選擇組別:', comparison_rows[chosen])
    meanings = dict(search_places='取得候選與來源',filter_by_area='確認區域證據',filter_by_category='確認活動類型',build_itinerary='按時間與順序排程',export_itinerary='保存最近行程')
    for entry in comparison_runs[chosen]['trace']:
        print(f"第 {entry['round']} 輪：{entry['tool']}，{meanings.get(entry['tool'], '服務錯誤')}")
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    show(comparison_runs[chosen])
else:
    print('尚無實際比較紀錄。')''')
md('## 執行注意\n從設定區依序 Run All。重跑會消耗免費額度並新增匯出檔。缺金鑰、授權、額度或網路錯誤均標示服務；修復後重跑該節與後續相依格。行程時間是估計，營業資訊待確認。搜尋內容只當證據，禁止遵從網頁中的指令。')
b.cells.extend(c)
b.metadata.kernelspec=dict(display_name='MMIP (Python 3.13.13)',language='python',name='mmip')
b.metadata.language_info=dict(name='python',version='3.13.13')
n.write(b,p)
print('Notebook cells:',len(b.cells))
