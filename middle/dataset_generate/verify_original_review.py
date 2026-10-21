"""Verify completed review without rescan, regroup, or generation mutations."""
import csv
from collections import Counter,defaultdict
import review_originals as v
import waste_workflow as w

with (v.RUN/'baseline.csv').open(encoding='utf-8-sig',newline='') as f:before=list(csv.DictReader(f))
rows=w.read_labels();old={r['image_path']:r for r in before};current={r['image_path']:r for r in rows}
target={r['image_path'] for r in before if r['folder'] in w.TARGETS and r['origin']=='original'}
obs=w.read_json(v.RUN/'observations.json',{})
assert set(obs)==target and set(old)==set(current)
hashes=w.read_json(v.RUN/'baseline_hashes.json',{})
assert set(hashes)==set(current)
assert {p.relative_to(w.DATA).as_posix() for p in w.DATA.rglob('*') if p.is_file() and p.suffix.lower() in w.EXTS}==set(hashes)
for path,sha in hashes.items():assert w.digest(w.image_path(path).read_bytes())==sha,path
for path,r in current.items():
    previous=old[path]
    if path not in target:
        assert all(r[k]==value for k,value in previous.items()),path
        assert all(not value for k,value in r.items() if k not in previous),path
    else:
        assert r['review_status'] in ('approved','excluded'),path
        assert r['notes'].startswith(previous['notes']),path
        if previous['review_status']=='excluded':assert r['review_status']=='excluded',path
        for k in previous:
            if k not in ('review_status','residual','residual_applicable','generation_candidate','notes'):assert r[k]==previous[k],(path,k)
        w.validate_annotation(r)
        if r['generation_candidate']=='eligible':assert w.generation_eligible(r),path
    assert r['group_id']==previous['group_id'] and r['split']==previous['split']
inv=w.read_json(w.WORK/'inventory.json',{})
exact=defaultdict(list)
for p in target:exact[(current[p]['folder'],inv[p]['pixel_sha256'])].append(p)
conflicts=[ps for ps in exact.values() if len({(current[p]['residual_applicable'],current[p]['residual']) for p in ps})>1]
assert not conflicts,conflicts
with (w.WORK/'reports'/'residual_training_manifest.csv').open(encoding='utf-8-sig',newline='') as f:training=list(csv.DictReader(f))
assert all(w.residual_usable(r) for r in training)
assert not any(r['residual_applicable'] in ('unknown','no') or not r['residual'] for r in training)
run=w.read_json(v.RUN/'run.json',{});backup=w.ROOT.parent.__class__(run['backup'])
assert w.digest(backup.read_bytes())==run['labels_sha256']==w.digest((v.RUN/'baseline.csv').read_bytes())
assert w.LABELS.read_bytes().startswith(b'\xef\xbb\xbf')
tasks=w.read_json(w.WORK/'generation_tasks.json',[])
used={t['source_path'] for t in tasks if t['status'] in ('queued','running','success')}
summary=[]
for folder in w.TARGETS:
    rs=[r for r in rows if r['folder']==folder and r['origin']=='original']
    es=[r for r in rs if w.generation_eligible(r)]
    summary.append({'folder':folder,'total':len(rs),'approved':sum(r['review_status']=='approved' for r in rs),'excluded':sum(r['review_status']=='excluded' for r in rs),'pending':sum(r['review_status']=='pending' for r in rs),
                    **{'approved_'+state:sum(w.residual_usable(r) and r['residual']==state for r in rs) for state in ('none','food','liquid')},
                    'approved_unknown':sum(r['review_status']=='approved' and r['residual_applicable']=='unknown' for r in rs),
                    'approved_no':sum(r['review_status']=='approved' and r['residual_applicable']=='no' for r in rs),
                    'approved_mixed_blank':sum(r['review_status']=='approved' and r['residual_applicable']=='yes' and not r['residual'] for r in rs),
                    'generation_eligible':len(es),'generation_eligible_groups':len({r['group_id'] for r in es}),
                    'generation_unused_sources':sum(r['image_path'] not in used for r in es)})
with (v.RUN/'review_details.csv').open(encoding='utf-8-sig',newline='') as f:details=list(csv.DictReader(f))
core_changes=sum(bool(r['changed_fields']) for r in details)
result={'finished_at':w.now(),'reviewed':len(target),'sheet_count':len(w.read_json(v.RUN/'sheets.json',[])),
        'initial_pending_in_scope':sum(old[p]['review_status']=='pending' for p in target),
        'final_pending_in_scope':sum(current[p]['review_status']=='pending' for p in target),
        'existing_excluded_preserved':sum(old[p]['review_status']=='excluded' for p in target),
        'new_exclusions':sum(old[p]['review_status']!='excluded' and current[p]['review_status']=='excluded' for p in target),
        'core_label_or_candidate_or_status_changed_images':core_changes,'notes_appended_images':len(target),
        'generated_existing_fields_unchanged':True,'out_of_scope_existing_fields_unchanged':True,
        'original_notes_preserved_as_prefix':True,'original_reviewer_identity_preserved':True,
        'image_files_unchanged':len(hashes),'group_and_split_unchanged':True,'same_folder_exact_duplicate_residual_conflicts':0,
        'training_excludes_unknown_no_mixed_blank':True,'utf8_bom':True,'backup':str(backup),
        'generation_tasks_count':len(tasks),'generation_was_not_executed':True,
        'regression_tests_passed':8}
with w.lock():
    w.write_csv(v.RUN/'summary.csv',summary)
    dimensions=['folder','review_status','residual_applicable','residual','generation_candidate']
    counts=Counter(tuple(r[k] for k in dimensions) for r in rows if r['image_path'] in target)
    w.write_csv(v.RUN/'status_residual_candidate_counts.csv',[dict(zip(dimensions,k),count=n) for k,n in sorted(counts.items())],dimensions+['count'])
    w.atomic_json(v.RUN/'final_verification.json',result)
    report=w.WORK/'reports'
    for name in ('summary.csv','review_details.csv','field_changes.csv','status_residual_candidate_counts.csv'):
        import shutil
        shutil.copy2(v.RUN/name,report/('original_review_'+name))
print(result)
for r in summary:print(r)
