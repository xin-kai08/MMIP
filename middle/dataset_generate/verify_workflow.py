"""Read/audit originals, verify rescan preservation and local HTTP endpoints.

Writes validation.json and updates derived scan reports; never changes images.
"""
import contextlib
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from collections import Counter,defaultdict
import waste_workflow as w

def run():
    before=w.read_labels();labels_hash=hashlib.sha256(w.LABELS.read_bytes()).hexdigest()
    inv=w.read_json(w.WORK/'inventory.json',{})
    for r in before:
        if r['origin']=='original':
            actual=hashlib.sha256(w.image_path(r['image_path']).read_bytes()).hexdigest()
            assert actual==inv[r['image_path']]['first_sha256'],r['image_path']
    with w.lock(),contextlib.redirect_stdout(io.StringIO()):w.scan()
    after=w.read_labels();assert before==after,'Rescan changed annotations/assignments'
    assert labels_hash==hashlib.sha256(w.LABELS.read_bytes()).hexdigest()
    assert w.LABELS.read_bytes().startswith(b'\xef\xbb\xbf')
    groups=defaultdict(set);sources={r['source_id']:r for r in after if r['origin']=='original'}
    for r in after:
        groups[r['group_id']].add(r['split'])
        if r['origin']=='generated':
            src=sources[r['source_id']]
            assert (r['group_id'],r['split'])==(src['group_id'],src['split'])
    assert all(len(s)==1 for s in groups.values())
    tasks=w.read_json(w.WORK/'generation_tasks.json',[])
    for t in tasks:
        if t['status']=='success':assert w.digest(w.image_path(t['output_path']).read_bytes())==t['output_sha256']
    server=subprocess.Popen([sys.executable,str(w.ROOT/'waste_workflow.py'),'serve','--port','8766'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        base='http://127.0.0.1:8766'
        for i in range(40):
            try:html=urllib.request.urlopen(base+'/',timeout=2).read().decode('utf-8');break
            except OSError:
                if server.poll() is not None:raise RuntimeError('HTTP server failed to start (port busy?)')
                time.sleep(.1)
        else:raise RuntimeError('HTTP server did not start')
        assert '人工複核' in html and '__TOKEN__' not in html
        assert len(json.load(urllib.request.urlopen(base+'/api/rows')))==len(after)
        assert urllib.request.urlopen(base+'/image/paper_cups/Image_255.png').headers.get_content_type()=='image/jpeg'
        pair_count=len(json.load(urllib.request.urlopen(base+'/api/duplicates')))
        # Rejected mutation must leave all labels intact.
        req=urllib.request.Request(base+'/api/annotate',data=b'{}',method='POST',headers={'Content-Type':'application/json'})
        try:urllib.request.urlopen(req);raise AssertionError('Missing token was accepted')
        except urllib.error.HTTPError as e:assert e.code==403
        token=re.search("const token='([^']+)'",html).group(1)
        req=urllib.request.Request(base+'/api/annotate',data=json.dumps({'image_path':'paper_cups/Image_255.png','residual':'invalid'}).encode(),method='POST',headers={'Content-Type':'application/json','X-Review-Token':token})
        try:urllib.request.urlopen(req);raise AssertionError('Invalid label was accepted')
        except urllib.error.HTTPError as e:assert e.code==400
        assert w.read_labels()==after
    finally:
        server.terminate();server.wait(timeout=10)
    def records(name):
        with (w.WORK/'reports'/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    result={'verified_at':w.now(),'original_unchanged':sum(r['origin']=='original' for r in after),
            'generated_count':sum(r['origin']=='generated' for r in after),'all_generated_checksums_ok':True,
            'rescan_preserves_labels_bytes':True,'utf8_bom':True,'all_groups_single_split':True,
            'all_generated_inherit_source_group_split':True,'http_utf8_rows_images_ok':True,
            'http_rejects_unauthorized_and_invalid_mutations':True,'browser_visual_qa':'not available: no connected browser',
            'exact_duplicate_pairs':len(records('exact_duplicates.csv')),'near_candidate_pairs':pair_count,
            'pending':sum(r['review_status']=='pending' for r in after),'preliminary_visual_reviewed':sum(bool(r['visual_review_by']) for r in after),
            'generation_success':sum(t['status']=='success' for t in tasks),'generation_failed':sum(t['status'] in ('failed','interrupted') for t in tasks),
            'generation_needs_rework':len(records('generated_needs_rework.csv')),
            'original_splits':dict(Counter(r['split'] for r in after if r['origin']=='original')),
            'generated_splits':dict(Counter(r['split'] for r in after if r['origin']=='generated'))}
    w.atomic_json(w.WORK/'reports'/'validation.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':run()
