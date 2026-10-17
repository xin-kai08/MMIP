"""Read-only label qualification, immutable manifests and fixed group allocation."""
from __future__ import annotations
import csv
import hashlib
import json
import random
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
DATA = PROJECT / 'dataset'
LABELS = DATA / 'labels.csv'
STATE = PROJECT / 'dataset_generate/dataset_workflow'
WASTE = ['general', 'glass', 'food_waste', 'other_recycling']
RESIDUAL = ['none', 'food', 'liquid', 'not_assessable']
UNKNOWN_REASONS = {'interior_not_visible', 'occluded_interior', 'unreadable_interior'}
QUAL_FIELDS = ['image_path', 'label_fingerprint', 'decision', 'reason', 'reviewer', 'evidence']

def sha(data): return hashlib.sha256(data).hexdigest()
def read_csv(p):
    with Path(p).open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
def read_json(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def write_json(p, value):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix(p.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(p)
def write_csv(p, rows, fields=None):
    rows = list(rows); p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0]) if rows else ['image_path', 'reason'])
    with p.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
def image_path(rel, data=None):
    data = data or DATA
    p = (data / rel).resolve()
    if not p.is_relative_to(data.resolve()): raise ValueError('Image outside dataset: ' + rel)
    return p
def fingerprint(r):
    return sha(json.dumps({k:r.get(k,'') for k in ('image_path','review_status','residual_applicable','residual','notes')},sort_keys=True,ensure_ascii=False).encode())

def residual_target(r, qualification=None):
    """Never infer an unknown reason from filenames, free text, or confidence."""
    if r['review_status'] != 'approved': return -1, 'not_approved'
    app, label = r['residual_applicable'], r['residual']
    if app == 'yes' and label in RESIDUAL[:3]: return RESIDUAL.index(label), ''
    if app == 'no' and not label: return 3, ''
    if app == 'unknown' and not label:
        q = qualification or {}
        if (q.get('decision') == 'confirmed' and q.get('reason') in UNKNOWN_REASONS
            and q.get('reviewer','').strip() and q.get('evidence','').strip()
            and q.get('label_fingerprint') == fingerprint(r)):
            return 3, ''
        return -1, 'unknown_reason_requires_explicit_confirmation'
    if app == 'yes' and not label: return -1, 'mixed_or_unannotated_requires_resolution'
    return -1, 'invalid_residual_combination'

def assign_stages(rows, seed=42):
    """Greedy balanced allocation of entire train groups; no split reshuffling."""
    groups = defaultdict(list)
    for r in rows:
        if r['split'] == 'train': groups[r['group_id']].append(r)
    vectors = {}
    for gid, members in groups.items():
        c = Counter()
        for r in members:
            # Include every member, even pending ones, to preserve future allocation.
            c[('folder', r['folder'])] += 1
            c[('origin', r['origin'])] += 1
            c[('folder_origin', r['folder'], r['origin'])] += 1
            c[('waste', r['waste_class'])] += 1
            target, _ = residual_target(r)
            c[('residual', str(target))] += 1
            if r['origin'] == 'generated': c[('generated_source', r['folder'])] += 1
            c[('size',)] += 1
        vectors[gid] = c
    totals = sum(vectors.values(), Counter())
    rng = random.Random(seed); order = sorted(groups); rng.shuffle(order)
    order.sort(key=lambda g:-len(groups[g]))
    counts = {'stage1':Counter(), 'stage2':Counter()}; result = {}
    for gid in order:
        v = vectors[gid]
        def cost(stage):
            return sum(((counts[stage][k]+v[k]-totals[k]/2)**2
                        - (counts[stage][k]-totals[k]/2)**2) / max(totals[k],1) for k in v)
        stage = min(counts, key=cost); counts[stage].update(v); result[gid] = stage
    return result

def check_groups(rows):
    splits, stages, sources = defaultdict(set), defaultdict(set), {}
    for r in rows:
        if r['split'] not in ('train','val','test'): raise ValueError('Invalid split')
        splits[r['group_id']].add(r['split'])
        stage = r.get('stage','')
        if r['split'] != 'train' and stage: raise ValueError('Validation/test assigned to training stage')
        if r['split'] == 'train' and 'stage' in r and stage not in ('stage1','stage2'): raise ValueError('Missing stage')
        if stage: stages[r['group_id']].add(stage)
        if r['origin'] == 'original': sources[r['source_id']] = r
    if any(len(v)>1 for v in splits.values()) or any(len(v)>1 for v in stages.values()):
        raise ValueError('Group crosses split or stage')
    for r in rows:
        if r['origin'] == 'generated':
            s = sources.get(r['source_id'])
            if s is None or s['group_id'] != r['group_id'] or s['split'] != r['split']:
                raise ValueError('Generated image detached from source: '+r['image_path'])

def check_confirmed_duplicates(rows):
    by={r['image_path']:r for r in rows}
    pairs=[]
    report=STATE/'reports/exact_duplicates.csv'
    if report.exists():pairs+=read_csv(report)
    decisions=STATE/'duplicate_decisions.json'
    if decisions.exists():pairs += [p for p in read_json(decisions) if p['decision']=='same']
    for pair in pairs:
        if pair['a'] in by and pair['b'] in by and by[pair['a']]['group_id']!=by[pair['b']]['group_id']:
            raise ValueError('Confirmed duplicate crosses groups: '+pair['a']+' / '+pair['b'])

def prepare(version='v1', reuse_partition=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', version): raise ValueError('Unsafe version name')
    folder = ROOT / 'artifacts' / version
    qualification_path = ROOT / 'residual_eligibility.csv'
    # Snapshot before creating ANY qualification or allocation record.
    backup = ROOT / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    backup.mkdir(parents=True)
    for p in (LABELS, qualification_path, folder/'partition.json', folder/'manifest.csv', folder/'metadata.json', STATE/'inventory.json', STATE/'duplicate_decisions.json', STATE/'reports/split_counts.csv', STATE/'reports/split_conflicts_resolved.csv'):
        if p.exists(): shutil.copy2(p, backup/p.name)
    rows = read_csv(LABELS)
    if len({r['image_path'] for r in rows}) != len(rows): raise ValueError('Duplicate CSV paths')
    check_groups(rows)
    check_confirmed_duplicates(rows)
    if not qualification_path.exists():
        write_csv(qualification_path, [dict(image_path=r['image_path'],label_fingerprint=fingerprint(r),decision='pending',reason='',reviewer='',evidence='')
                  for r in rows if r['review_status']=='approved' and r['residual_applicable']=='unknown' and not r['residual']], QUAL_FIELDS)
    quals = read_csv(qualification_path)
    if len({q['image_path'] for q in quals}) != len(quals): raise ValueError('Duplicate eligibility paths')
    qualification = {q['image_path']:q for q in quals}
    labels_hash = sha(LABELS.read_bytes()); qualification_hash = sha(qualification_path.read_bytes())
    if folder.exists():
        old = read_json(folder/'metadata.json')
        if old['labels_sha256'] != labels_hash or old['eligibility_sha256'] != qualification_hash:
            raise ValueError('Frozen version differs from current labels/eligibility; create a new version with --reuse-partition')
        verify(folder); return folder
    partition_source = Path(reuse_partition) if reuse_partition else None
    if partition_source:
        partition = read_json(partition_source)
        for r in rows:
            g = partition.get(r['group_id'])
            if not g or g['split'] != r['split']: raise ValueError('Existing partition changed; reconcile groups explicitly')
    else:
        stages = assign_stages(rows)
        partition = {r['group_id']:dict(split=r['split'],stage=stages.get(r['group_id'],'')) for r in rows}
    for r in rows: r['stage'] = partition[r['group_id']]['stage']
    check_groups(rows)
    issues = []; manifest = []; original_groups = defaultdict(list)
    for r in rows:
        if r['origin']=='original' and r['review_status']=='approved': original_groups[r['group_id']].append(r)
    waste_conflicts = {g for g,rs in original_groups.items() if len({r['waste_class'] for r in rs})>1}
    residual_conflicts = {g for g,rs in original_groups.items() if len({residual_target(r,qualification.get(r['image_path']))[0] for r in rs if residual_target(r,qualification.get(r['image_path']))[0]>=0})>1}
    seen_original = set()
    from PIL import Image
    for r in rows:
        reason = ''
        if r['review_status'] != 'approved': reason = r['review_status']
        elif r['waste_class'] not in WASTE: reason = 'unknown_waste_class'
        elif r['group_id'] in waste_conflicts: reason = 'confirmed_duplicate_waste_conflict'
        p = image_path(r['image_path'])
        try:
            with Image.open(p) as im: im.verify()
            file_hash = sha(p.read_bytes())
        except (OSError,ValueError) as e: reason='image_decode_error'; file_hash=''
        if reason:
            issues.append(dict(image_path=r['image_path'],reason=reason,origin=r['origin'],folder=r['folder'])); continue
        target, residual_reason = residual_target(r,qualification.get(r['image_path']))
        if r['group_id'] in residual_conflicts: target=-1; residual_reason='confirmed_duplicate_residual_conflict'
        if residual_reason: issues.append(dict(image_path=r['image_path'],reason=residual_reason,origin=r['origin'],folder=r['folder']))
        # Count confirmed original duplicates once; generated variants are separate.
        duplicate_key = (r['group_id'], r['folder'])
        if r['origin']=='original' and duplicate_key in seen_original:
            issues.append(dict(image_path=r['image_path'],reason='canonical_original_duplicate',origin=r['origin'],folder=r['folder']));continue
        if r['origin']=='original':seen_original.add(duplicate_key)
        manifest.append(dict(image_path=r['image_path'],folder=r['folder'],origin=r['origin'],source_id=r['source_id'],group_id=r['group_id'],split=r['split'],stage=r['stage'],
                             waste_target=WASTE.index(r['waste_class']),residual_target=target,residual_mask=int(target>=0),
                             residual_applicable=r['residual_applicable'],residual=r['residual'],image_sha256=file_hash))
    near = read_csv(STATE/'reports/near_duplicates.csv') if (STATE/'reports/near_duplicates.csv').exists() else []
    unresolved = [r for r in near if r['decision']=='pending' and r.get('same_known_group')!='True']
    distribution = Counter((r['split'],r['stage'],r['folder'],r['origin'],WASTE[int(r['waste_target'])],RESIDUAL[int(r['residual_target'])] if int(r['residual_target'])>=0 else 'masked') for r in manifest)
    missing=[]
    for task, classes, column in [('waste',WASTE,'waste_target'),('residual',RESIDUAL,'residual_target')]:
        for subset in (('stage1','val') if task=='waste' else ('stage2','val')):
            selected=[r for r in manifest if (r['stage']==subset or r['split']==subset) and (subset!='val' or r['origin']=='original')]
            for i,c in enumerate(classes):
                if not any(int(r[column])==i for r in selected):missing.append(f'{task}:{subset}:{c}')
    pending = Counter(r['origin'] for r in rows if r['review_status']=='pending')
    blockers=[]
    if pending: blockers.append('Unreviewed images: '+str(dict(pending)))
    if missing:blockers.append('Missing training/validation classes: '+', '.join(missing))
    if waste_conflicts or residual_conflicts:blockers.append('Confirmed duplicate label conflicts require resolution')
    unknown_count=sum(r['reason']=='unknown_reason_requires_explicit_confirmation' for r in issues)
    risks=[f'Unresolved near-duplicate candidates: {len(unresolved)}; not automatically grouped',
           f'Unknown residual reasons without explicit qualification: {unknown_count}; masked from residual loss']
    test_support={task:dict(Counter(classes[int(r[column])] for r in manifest if r['split']=='test' and r['origin']=='original' and int(r[column])>=0))
                  for task,classes,column in [('waste',WASTE,'waste_target'),('residual',RESIDUAL,'residual_target')]}
    summary = dict(version=version,seed=42,ratios=[.7,.2,.1],existing_split_reused=True,partition_source=str(partition_source or LABELS),
                   source_rows=len(rows),manifest_rows=len(manifest),original_review=dict(Counter(r['review_status'] for r in rows if r['origin']=='original')),
                   generated_review=dict(Counter(r['review_status'] for r in rows if r['origin']=='generated')),
                   all_split_counts=dict(Counter(r['split'] for r in rows)),manifest_split_counts=dict(Counter(r['split'] for r in manifest)),
                   stage_counts=dict(Counter(r['stage'] for r in manifest if r['stage'])),
                   issue_counts=dict(Counter(r['reason'] for r in issues)),missing_classes=missing,blockers=blockers,risks=risks,real_test_support=test_support,ready=not blockers)
    folder.mkdir(parents=True)
    write_json(folder/'partition.json',partition)
    write_csv(folder/'manifest.csv',manifest, ['image_path','folder','origin','source_id','group_id','split','stage','waste_target','residual_target','residual_mask','residual_applicable','residual','image_sha256'])
    write_csv(folder/'issues.csv',issues)
    write_csv(folder/'unresolved_near_duplicates.csv',unresolved,list(near[0]) if near else None)
    write_csv(folder/'distribution.csv',[dict(split=k[0],stage=k[1],folder=k[2],origin=k[3],waste_class=k[4],residual_class=k[5],count=n) for k,n in sorted(distribution.items())])
    write_json(folder/'readiness.json',summary)
    write_json(folder/'metadata.json',dict(version=version,seed=42,labels_sha256=labels_hash,eligibility_sha256=qualification_hash,
        manifest_sha256=sha((folder/'manifest.csv').read_bytes()),partition_sha256=sha((folder/'partition.json').read_bytes()),
        created_at=datetime.now(timezone.utc).isoformat(),backup=str(backup),waste_classes=WASTE,residual_classes=RESIDUAL))
    verify(folder);return folder

def verify(folder, check_images=True):
    folder = Path(folder);meta = read_json(folder/'metadata.json');rows=read_csv(folder/'manifest.csv')
    if sha((folder/'manifest.csv').read_bytes())!=meta['manifest_sha256']:raise ValueError('Manifest changed')
    if sha((folder/'partition.json').read_bytes())!=meta['partition_sha256']:raise ValueError('Partition changed')
    if sha(LABELS.read_bytes())!=meta['labels_sha256']:raise ValueError('Live labels differ; build new manifest version, reuse partition')
    if sha((ROOT/'residual_eligibility.csv').read_bytes())!=meta['eligibility_sha256']:raise ValueError('Eligibility differs from frozen manifest')
    partition=read_json(folder/'partition.json'); labels=read_csv(LABELS)
    check_groups(labels)
    check_confirmed_duplicates(labels)
    for r in labels:
        if r['group_id'] not in partition or partition[r['group_id']]['split']!=r['split']:raise ValueError('Partition does not match labels')
        r['stage']=partition[r['group_id']]['stage']
    check_groups(labels)
    for r in rows:
        if not 0<=int(r['waste_target'])<4 or int(r['residual_target']) not in (-1,0,1,2,3):raise ValueError('Invalid targets')
        if int(r['residual_mask'])!=int(int(r['residual_target'])>=0):raise ValueError('Invalid residual mask')
        if partition[r['group_id']]!={'split':r['split'],'stage':r['stage']}:raise ValueError('Manifest allocation mismatch')
        if check_images and sha(image_path(r['image_path']).read_bytes())!=r['image_sha256']:raise ValueError('Image changed: '+r['image_path'])
    return read_json(folder/'readiness.json')
