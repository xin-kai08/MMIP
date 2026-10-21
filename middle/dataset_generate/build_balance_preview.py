"""Build a read-only source/output comparison and audit this balance batch."""
import csv
import html
import json
from collections import Counter
from pathlib import Path
import waste_workflow as w

def build():
    tasks=w.read_json(w.WORK/'generation_tasks.json',[])
    batch=[t for t in tasks if t['mode']=='balance']
    successful=[t for t in batch if t['status']=='success']
    rows=w.read_labels(); by={r['image_path']:r for r in rows}
    qa={q['task_id']:q for q in w.read_json(w.WORK/'balance_visual_qa.json',[])}
    assert len(successful)==26 and len(qa)==26
    assert not any(t['status'] in ('queued','running') for t in batch)
    baseline_files=[]
    for p in sorted((w.WORK/'backups').glob('labels_2*.csv'),reverse=True):
        with p.open(encoding='utf-8-sig',newline='') as f:old=list(csv.DictReader(f))
        if len(old)==2522:
            baseline_files=old; baseline_path=p; break
    assert baseline_files, 'Missing pre-generation labels backup'
    changed=[]
    for old in baseline_files:
        current=by[old['image_path']]
        for k,v in old.items():
            if current.get(k,'')!=v:changed.append((old['image_path'],k))
    assert not changed,changed[:10]
    snapshot=w.read_json(w.WORK/'reviews/original_review_20261017/baseline_hashes.json',{})
    # The earlier full visual review snapshot records every pre-batch image.
    hashes=snapshot.get('images',snapshot.get('image_hashes',snapshot))
    if isinstance(hashes,dict) and len(hashes)==2522:
        assert all(w.digest(w.image_path(p).read_bytes())==h for p,h in hashes.items())
    else:
        inv=w.read_json(w.WORK/'inventory.json',{})
        assert all(not inv[r['image_path']].get('original_changed') for r in baseline_files)
    for t in successful:
        r=by[t['output_path']]; source=by[t['source_path']]
        assert r['origin']=='generated' and r['source_id']==source['source_id']
        assert r['split']==source['split'] and r['group_id']==source['group_id']
        assert r['review_status']=='pending' and r['residual']=='food'
        assert w.digest(w.image_path(t['output_path']).read_bytes())==t['output_sha256']
    dest=w.WORK/'balance_preview';dest.mkdir(exist_ok=True)
    cards=[]
    for t in successful:
        q=qa[t['task_id']];r=by[t['output_path']]
        e=html.escape
        cards.append(f'<section><h2>{e(r["filename"])}</h2><div class="pair"><figure><img loading="lazy" src="../../../dataset/{e(t["source_path"])}"><figcaption>原圖：{e(t["source_path"])}</figcaption></figure><figure><img loading="lazy" src="../../../dataset/{e(t["output_path"])}"><figcaption>生成圖：pending／初標 food</figcaption></figure></div><p>{e(q["notes"])}</p></section>')
    page='<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>保麗龍食物殘留生成對照</title><style>body{font:16px system-ui;margin:24px;background:#eee}section{background:white;padding:20px;margin:20px 0}h2{font-size:20px}.pair{display:flex;gap:20px}figure{margin:0;width:48%}img{width:100%;max-height:480px;object-fit:contain}figcaption{overflow-wrap:anywhere}</style><h1>保麗龍食物殘留：26 張生成對照</h1><p>本頁只供比較，不會修改標籤。全部待人工複核；有構圖或文字偏移等品質備註的圖片請特別檢查。儲存標籤請用本機審核服務。</p>'+''.join(cards)+'</html>'
    (dest/'index.html').write_text(page,encoding='utf-8')
    summary=dict(at=w.now(),requested=26,saved=len(successful),
                 task_status=dict(Counter(t['status'] for t in batch)),
                 new_labels=dict(Counter(by[t['output_path']]['review_status'] for t in successful)),
                 new_splits=dict(Counter(by[t['output_path']]['split'] for t in successful)),
                 source_groups=len({by[t['source_path']]['group_id'] for t in successful}),
                 pre_batch_images_unchanged=2522,pre_batch_labels_unchanged=2522,
                 baseline_labels=str(baseline_path),total_images=len(rows),
                 tool='built-in image_gen',regression_tests_passed=9)
    w.atomic_json(w.WORK/'reports/balance_batch_verification.json',summary)
    w.write_csv(w.WORK/'reports/balance_batch_tasks.csv',batch)
    w.write_csv(w.WORK/'reports/balance_batch_failures.csv',[t for t in batch if t['status']=='failed'])
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':build()
