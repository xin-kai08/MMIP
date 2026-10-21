"""Local, resumable waste image curation. Never edits original images.

Python 3.12+, Pillow. See DATASET_WORKFLOW.md for commands and review policy.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import os
import random
import re
import secrets
import shutil
import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / 'dataset'
WORK = ROOT / 'dataset_workflow'
LABELS = DATA / 'labels.csv'
MAPPING = {'plastic_straws':'general','plastic_trash_bags':'general',
           'glass_beverage_bottles':'glass','food_waste':'food_waste',
           **{k:'other_recycling' for k in ('cardboard_boxes','paper_cups','plastic_cup_lids',
              'plastic_food_containers','plastic_water_bottles','styrofoam_food_containers')}}
TARGETS = {k:('food' if 'food_containers' in k else 'liquid') for k in
           ('glass_beverage_bottles','paper_cups','plastic_water_bottles',
            'plastic_food_containers','styrofoam_food_containers')}
NONCONTAINERS = {'plastic_straws','plastic_trash_bags','food_waste','plastic_cup_lids'}
EXTS = {'.png','.jpg','.jpeg','.webp','.bmp','.gif','.tif','.tiff','.avif','.heic','.heif'}
FIELDS = ['image_path','folder','filename','waste_class','residual','residual_applicable',
          'origin','source_id','group_id','split','review_status','notes',
          'generation_candidate','visual_review_by','visual_review_at']
EDITABLE = {'waste_class','residual','residual_applicable','review_status','notes',
            'generation_candidate','visual_review_by'}
ENUMS = {'waste_class':set(MAPPING.values())|{''}, 'residual':{'','none','food','liquid'},
         'residual_applicable':{'yes','no','unknown'}, 'review_status':{'pending','approved','excluded'},
         'generation_candidate':{'','eligible','exclude','review'}}

def now(): return datetime.now(timezone.utc).isoformat()
def residual_usable(row):
    """Approval means reviewed; only an observed single residual label trains."""
    return row.get('review_status')=='approved' and row.get('residual_applicable')=='yes' and row.get('residual') in ('none','food','liquid')
def generation_eligible(row):
    """Candidate flag represents visual single-container/visibility assessment."""
    return row.get('origin')=='original' and residual_usable(row) and row.get('residual')=='none' and row.get('generation_candidate')=='eligible'
def validate_annotation(candidate):
    if candidate['residual'] and candidate['residual_applicable']!='yes':
        raise ValueError('Residual label requires applicability yes')
    if candidate['review_status']=='approved' and candidate['residual_applicable']=='yes' and not candidate['residual']:
        if not any(term in candidate['notes'].lower() for term in ('mixed','並存','食物與液體','食物和液體')):
            raise ValueError('Uncertain residue should be applicability unknown; mixed food/liquid may stay blank with notes')
    if candidate['generation_candidate']=='eligible' and (candidate['origin']!='original' or candidate['residual_applicable']!='yes' or candidate['residual']!='none' or candidate['review_status']=='excluded'):
        raise ValueError('Generation eligible requires a retained original with confirmed no residue; otherwise use exclude/review')
def digest(b): return hashlib.sha256(b).hexdigest()
def sid(path): return path.split('/')[0] + ':' + path
def natural(s): return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)',s)]
def read_json(p, default):
    return json.loads(p.read_text('utf-8')) if p.exists() else default
def atomic_json(p, obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp = p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,p)
def write_csv(p, rows, fields=None):
    rows = list(rows)
    fields = fields or (list(rows[0]) if rows else [])
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp = p.with_name(p.name+'.tmp')
    with tmp.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader();w.writerows(rows)
    os.replace(tmp,p)
def read_labels():
    if not LABELS.exists(): return []
    with LABELS.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def save_labels(rows):
    if LABELS.exists():
        dest=WORK/'backups'/f'labels_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")}.csv'
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(LABELS,dest)
    write_csv(LABELS,rows,list(dict.fromkeys(FIELDS+[k for r in rows for k in r])))
def event(kind, **kw):
    WORK.mkdir(exist_ok=True)
    with (WORK/'generation_log.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'at':now(),'event':kind,**kw},ensure_ascii=False)+'\n'); f.flush();os.fsync(f.fileno())
@contextmanager
def lock():
    WORK.mkdir(exist_ok=True)
    p=WORK/'.workflow.lock'
    try: fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise RuntimeError('Workflow busy. If a process crashed, verify it stopped before removing dataset_workflow/.workflow.lock.')
    try:
        os.write(fd,str(os.getpid()).encode());os.close(fd);yield
    finally: p.unlink(missing_ok=True)
def image_path(rel):
    p=(DATA/rel).resolve()
    if not p.is_relative_to(DATA.resolve()): raise ValueError('Path outside dataset')
    return p
def inspect_file(p):
    b=p.read_bytes(); info={'sha256':digest(b),'bytes':len(b),'error':''}
    try:
        with Image.open(io.BytesIO(b)) as im: im.verify()
        with Image.open(io.BytesIO(b)) as im:
            fmt=im.format or '';im=ImageOps.exif_transpose(im);im.load()
            info.update(width=im.width,height=im.height,format=fmt,mode=im.mode)
            rgba=im.convert('RGBA')
            info['pixel_sha256']=digest(f'{im.width}x{im.height}'.encode()+rgba.tobytes())
            gray=im.convert('L').resize((9,8),Image.Resampling.LANCZOS)
            px=list(gray.get_flattened_data())
            h=0
            for y in range(8):
                for x in range(8): h=(h<<1)|int(px[y*9+x]>px[y*9+x+1])
            info['dhash']=f'{h:016x}'
            info['low_information']=min(h.bit_count(),64-h.bit_count())<5
    except Exception as e: info['error']=f'{type(e).__name__}: {e}'
    return info

class DSU:
    def __init__(self, keys): self.p={k:k for k in keys}
    def find(self,k):
        if self.p[k]!=k:self.p[k]=self.find(self.p[k])
        return self.p[k]
    def union(self,a,b):
        if a not in self.p or b not in self.p:return
        a,b=self.find(a),self.find(b)
        self.p[max(a,b)]=min(a,b)

def regroup(rows, inventory, reset=False):
    d=DSU(r['image_path'] for r in rows)
    origins={r['source_id']:r['image_path'] for r in rows if r['origin']=='original'}
    for r in rows:
        if r['source_id'] in origins:d.union(r['image_path'],origins[r['source_id']])
    for key in ('sha256','pixel_sha256'):
        seen={}
        for r in rows:
            v=inventory.get(r['image_path'],{}).get(key)
            if v:
                if v in seen:d.union(r['image_path'],seen[v])
                else:seen[v]=r['image_path']
    for pair in read_json(WORK/'duplicate_decisions.json',[]):
        if pair['decision']=='same':d.union(pair['a'],pair['b'])
    groups=defaultdict(list)
    for r in rows:groups[d.find(r['image_path'])].append(r)
    conflicts=[]
    for key,rs in groups.items():
        # New generated filenames must not change the original group's ID.
        group_key=min((r['image_path'] for r in rs if r['origin']=='original'),default=key)
        prior_groups={r['group_id'] for r in rs if r.get('group_id')}
        gid=next(iter(prior_groups)) if len(prior_groups)==1 else 'g_'+digest(group_key.encode())[:20]
        old={r['split'] for r in rs if r.get('split') in ('train','val','test')}
        if len(old)>1:conflicts.append({'group_id':gid,'previous_splits':','.join(sorted(old)), 'paths':' | '.join(r['image_path'] for r in rs)})
        for r in rs:r['group_id']=gid
    # One deterministic assignment per connected component. Confirmed labels only
    # contribute residual strata. Originals determine targets; variants add no weight.
    strata={}
    for key,rs in groups.items():
        c=Counter((r['folder'],r['residual'] if r['review_status']=='approved' and r['residual'] else 'unconfirmed')
                  for r in rs if r['origin']=='original')
        strata[key]=c or Counter({(rs[0]['folder'],'unconfirmed'):1})
    totals=Counter()
    for c in strata.values():totals.update(c)
    counts={s:Counter() for s in ('train','val','test')};weights={'train':.7,'val':.2,'test':.1}
    todo=[]
    for key,rs in groups.items():
        old={r['split'] for r in rs if r.get('split') in weights}
        if len(old)==1 and not reset:
            chosen=next(iter(old));counts[chosen].update(strata[key])
            for r in rs:r['split']=chosen
        else:todo.append(key)
    rng=random.Random(42);rng.shuffle(todo)
    todo.sort(key=lambda k:-sum(strata[k].values()))
    for key in todo:
        c=strata[key]
        # Largest normalized deficit summed over all component strata.
        chosen=max(weights,key=lambda s:sum(n*(totals[t]*weights[s]-counts[s][t])/max(1,totals[t]*weights[s]) for t,n in c.items()))
        counts[chosen].update(c)
        for r in groups[key]:r['split']=chosen
    write_csv(WORK/'reports'/'split_conflicts_resolved.csv',conflicts,['group_id','previous_splits','paths'])
    assert all(len({r['split'] for r in rs})==1 for rs in groups.values())

def scan():
    old={r['image_path']:r for r in read_labels()}
    cache=read_json(WORK/'inventory.json',{})
    tasks=read_json(WORK/'generation_tasks.json',[])
    generated={t['output_path']:t for t in tasks if t.get('output_path') and t['status']=='success'}
    rows=[];inventory={};ignored=[]
    paths=sorted((p for p in DATA.rglob('*') if p.is_file()),key=lambda p:natural(p.as_posix()))
    for i,p in enumerate(paths):
        if p.resolve()==LABELS.resolve():continue
        rel=p.relative_to(DATA).as_posix()
        if p.suffix.lower() not in EXTS:
            ignored.append({'image_path':rel,'reason':'not_supported_image_extension'});continue
        stat=p.stat(); prior=cache.get(rel,{})
        # Always hash originals, even when metadata is unchanged.
        sha=digest(p.read_bytes())
        info=prior.copy() if prior.get('sha256')==sha else inspect_file(p)
        info.update(mtime_ns=stat.st_mtime_ns)
        info.setdefault('first_sha256',sha)
        if prior.get('first_sha256'):info['first_sha256']=prior['first_sha256']
        info['original_changed']=info['first_sha256']!=sha
        inventory[rel]=info
        folder=rel.split('/')[0] if '/' in rel else ''
        t=generated.get(rel)
        r=old.get(rel)
        if r is None:
            r={k:'' for k in FIELDS}
            r.update(image_path=rel,folder=folder,filename=p.name,waste_class=MAPPING.get(folder,''),
                     residual_applicable='no' if folder in NONCONTAINERS else 'unknown',
                     origin='generated' if t else 'original',source_id=t['source_id'] if t else sid(rel),review_status='pending')
            if folder in NONCONTAINERS:r['notes']='此細類的容器殘留標註不適用；非 none。'
            if info['error']:r.update(review_status='excluded',notes='decode_error: '+info['error'])
            if t:r.update(notes='生成成功；目標 '+t['target_residual']+' 尚未驗收。',residual_applicable='unknown')
        else:
            # Preserve every existing annotation, including blank/manual values.
            for k in FIELDS:r.setdefault(k,'')
        rows.append(r)
        if i%250==0:print(f'scan {i}/{len(paths)}',flush=True)
    # Keep missing entries for audit, but exclude them from new split/report counts.
    missing=[r for rel,r in old.items() if rel not in inventory]
    write_csv(WORK/'reports'/'missing_files.csv',missing,FIELDS)
    regroup(rows,inventory)
    atomic_json(WORK/'inventory.json',inventory)
    save_labels(rows)
    write_csv(WORK/'reports'/'non_image_files.csv',ignored,['image_path','reason'])
    duplicate_report(rows,inventory)
    reports(rows,inventory)
    return rows

def duplicate_report(rows,inventory):
    exact=[];suspects=[];decisions={tuple(sorted((p['a'],p['b']))):p['decision'] for p in read_json(WORK/'duplicate_decisions.json',[])}
    bypath={r['image_path']:r for r in rows}
    items=[(r['image_path'],inventory[r['image_path']]) for r in rows if not inventory[r['image_path']]['error']]
    for i,(a,ia) in enumerate(items):
        for b,ib in items[i+1:]:
            if ia['sha256']==ib['sha256'] or ia['pixel_sha256']==ib['pixel_sha256']:
                exact.append({'a':a,'b':b,'method':'file_sha256' if ia['sha256']==ib['sha256'] else 'decoded_RGBA_sha256','decision':'same'})
            else:
                dist=(int(ia['dhash'],16)^int(ib['dhash'],16)).bit_count()
                ratio_a=ia['width']/ia['height'];ratio_b=ib['width']/ib['height']
                if dist<=6 and abs(math.log(ratio_a/ratio_b))<.18:
                    suspects.append({'a':a,'b':b,'dhash_distance':dist,'low_information':ia['low_information'] or ib['low_information'],
                                     'decision':decisions.get(tuple(sorted((a,b))),'pending')})
    write_csv(WORK/'reports'/'exact_duplicates.csv',exact,['a','b','method','decision'])
    for pair in suspects:
        pair.update(origin_a=bypath[pair['a']]['origin'],origin_b=bypath[pair['b']]['origin'],same_known_group=bypath[pair['a']]['group_id']==bypath[pair['b']]['group_id'])
    nearfields=['a','b','dhash_distance','low_information','decision','origin_a','origin_b','same_known_group']
    write_csv(WORK/'reports'/'near_duplicates.csv',sorted(suspects,key=lambda r:r['dhash_distance']),nearfields)
    write_csv(WORK/'reports'/'original_near_duplicates.csv',[r for r in sorted(suspects,key=lambda r:r['dhash_distance']) if r['origin_a']==r['origin_b']=='original'],nearfields)

def reports(rows=None,inventory=None):
    rows=rows if rows is not None else read_labels(); inventory=inventory if inventory is not None else read_json(WORK/'inventory.json',{})
    out=WORK/'reports';out.mkdir(parents=True,exist_ok=True)
    counts=Counter((r['folder'],r['waste_class'],r['residual'] or '(blank)',r['residual_applicable'],r['origin'],r['split'],r['review_status']) for r in rows)
    dims=['folder','waste_class','residual','residual_applicable','origin','split','review_status']
    write_csv(out/'counts.csv',[dict(zip(dims,k),count=v) for k,v in sorted(counts.items())],dims+['count'])
    write_csv(out/'pending_review.csv',[r for r in rows if r['review_status']=='pending'],FIELDS)
    write_csv(out/'candidate_exclusions.csv',[r for r in rows if r['generation_candidate']=='exclude'],FIELDS)
    write_csv(out/'damaged_images.csv',[dict(image_path=k,error=v['error']) for k,v in inventory.items() if v['error']],['image_path','error'])
    write_csv(out/'original_changes.csv',[dict(image_path=k,first_sha256=v['first_sha256'],sha256=v['sha256']) for k,v in inventory.items() if v.get('original_changed')],['image_path','first_sha256','sha256'])
    write_csv(out/'dimensions.csv',[dict(image_path=k,**v) for k,v in inventory.items()],['image_path','width','height','format','mode','bytes','sha256','pixel_sha256','dhash','error'])
    unknown=sorted(set(r['folder'] for r in rows)-set(MAPPING))
    atomic_json(out/'unknown_folders.json',{'folders':unknown,'root_directories':sorted(p.name for p in DATA.iterdir() if p.is_dir() and p.name not in MAPPING)})
    # Canonical usable originals: keep duplicates on disk/in labels, but count
    # one approved original per confirmed group and fine category for balancing.
    canonical=[];label_conflicts=[];seen=defaultdict(list)
    approved=[r for r in rows if r['review_status']=='approved' and not inventory.get(r['image_path'],{}).get('error') and not inventory.get(r['image_path'],{}).get('original_changed')]
    for r in approved:
        if r['origin']=='original':seen[(r['folder'],r['group_id'])].append(r)
        else:canonical.append(r)
    for (folder,gid),rs in seen.items():
        states={(r['residual_applicable'],r['residual']) for r in rs}
        if len(states)>1:
            label_conflicts.append({'folder':folder,'group_id':gid,'paths':' | '.join(r['image_path'] for r in rs),'states':str(sorted(states))})
        else:canonical.append(min(rs,key=lambda r:natural(r['image_path'])))
    write_csv(out/'classification_manifest.csv',canonical,FIELDS)
    residual_rows=[r for r in canonical if residual_usable(r)]
    write_csv(out/'usable_manifest.csv',residual_rows,FIELDS)
    write_csv(out/'residual_training_manifest.csv',residual_rows,FIELDS)
    write_csv(out/'reviewed_residual_unknown.csv',[r for r in rows if r['review_status']=='approved' and not residual_usable(r)],FIELDS)
    write_csv(out/'generation_eligible.csv',[r for r in rows if generation_eligible(r) and not inventory.get(r['image_path'],{}).get('error') and not inventory.get(r['image_path'],{}).get('original_changed')],FIELDS)
    write_csv(out/'duplicate_label_conflicts.csv',label_conflicts,['folder','group_id','paths','states'])
    balance=[]
    for folder,target in TARGETS.items():
        selected=[r for r in rows if r['folder']==folder]
        valid=[r for r in residual_rows if r['folder']==folder]
        original=[r for r in valid if r['origin']=='original'];generated=[r for r in valid if r['origin']=='generated']
        n=sum(r['residual']=='none' for r in original); p=sum(r['residual'] in ('food','liquid') for r in original)
        gn=sum(r['residual']=='none' for r in generated);gp=sum(r['residual'] in ('food','liquid') for r in generated)
        unreviewed=sum(r['origin']=='original' and r['review_status']=='pending' for r in selected)
        balance.append(dict(folder=folder,target=target,original_none=n,original_residual=p,generated_none=gn,generated_residual=gp,
                            original_pending=unreviewed,provisional_add_residual=max(0,n+gn-p-gp),
                            final_add_residual='' if unreviewed else max(0,n+gn-p-gp),
                            add_none_instead=max(0,p+gp-n-gn),
                            real_residual_test=sum(r['residual'] in ('food','liquid') and r['split']=='test' for r in original)))
    write_csv(out/'balance.csv',balance)
    tasks=read_json(WORK/'generation_tasks.json',[])
    write_csv(WORK/'generation_tasks.csv',tasks,['task_id','mode','folder','source_path','source_id','target_residual','prompt','output_path','status','error','source_sha256','output_sha256','attempts'])
    write_csv(out/'generation_failures.csv',[t for t in tasks if t['status'] in ('failed','interrupted')],['task_id','source_path','prompt','output_path','status','error'])
    write_csv(out/'generated_needs_rework.csv',[r for r in rows if r['origin']=='generated' and r['generation_candidate']=='exclude'],FIELDS)
    write_csv(out/'folder_summary.csv',[{'folder':f,'original':sum(r['folder']==f and r['origin']=='original' for r in rows),'generated':sum(r['folder']==f and r['origin']=='generated' for r in rows),
                                       'damaged':sum(bool(v['error']) for k,v in inventory.items() if k.split('/')[0]==f),'groups':len({r['group_id'] for r in rows if r['folder']==f})} for f in sorted({r['folder'] for r in rows})],['folder','original','generated','damaged','groups'])
    dcounts=Counter((r['folder'],r['origin'],r['split']) for r in rows)
    write_csv(out/'split_counts.csv',[{'folder':k[0],'origin':k[1],'split':k[2],'count':v} for k,v in sorted(dcounts.items())],['folder','origin','split','count'])
    scounts=Counter((r['origin'],r['residual'] or '(blank)',r['residual_applicable'],r['review_status']) for r in rows)
    write_csv(out/'residual_counts.csv',[{'origin':k[0],'residual':k[1],'residual_applicable':k[2],'review_status':k[3],'count':v} for k,v in sorted(scounts.items())],['origin','residual','residual_applicable','review_status','count'])
    summary={'image_count':len(rows),'by_folder':dict(sorted(Counter(r['folder'] for r in rows).items())),
             'by_origin':dict(Counter(r['origin'] for r in rows)), 'by_split':dict(Counter(r['split'] for r in rows)),
             'by_review_status':dict(Counter(r['review_status'] for r in rows)),
             'unique_groups':len(set(r['group_id'] for r in rows)), 'damaged':sum(bool(v['error']) for v in inventory.values()),
             'unknown_folders':unknown,'seed':42,'ratios':{'train':.7,'val':.2,'test':.1},
             'near_duplicate_method':'dHash64 distance <= 6, aspect log distance < .18; candidates only, not exhaustive',
             'labels_notice':'Prompt targets are not labels. Only approved visual labels count for balance. Split currently provisional while duplicate review is pending.',
             'test_warning':'Evaluate original real residual test images separately. Synthetic test accuracy does not establish real photo accuracy.'}
    atomic_json(out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

def contacts():
    rows=read_labels();out=WORK/'contacts';out.mkdir(exist_ok=True)
    by=defaultdict(list)
    for r in rows:by[r['folder']].append(r)
    for folder,rs in by.items():
        for offset in range(0,len(rs),48):
            part=rs[offset:offset+48];canvas=Image.new('RGB',(1200,math.ceil(len(part)/6)*174),'#eeeeee');draw=ImageDraw.Draw(canvas)
            for i,r in enumerate(part):
                x=(i%6)*200;y=(i//6)*174
                try:
                    with Image.open(image_path(r['image_path'])) as im:
                        im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((192,145));canvas.paste(im,(x+(200-im.width)//2,y))
                except Exception:draw.text((x+5,y+40),'DECODE ERROR',fill='red')
                draw.text((x+4,y+146),r['filename'][:30],fill='black')
                draw.text((x+4,y+160),f"{r['origin']} {r['review_status']}",fill='black')
            canvas.save(out/f'{folder}_{offset//48+1:02d}.jpg',quality=88)
    print('Contact sheets:',out)

def annotate(updates):
    rows=read_labels();index={r['image_path']:r for r in rows}
    for u in updates:
        if u['image_path'] not in index:raise ValueError('Unknown image '+u['image_path'])
        r=index[u['image_path']];changes={k:v for k,v in u.items() if k in EDITABLE}
        if any(k not in EDITABLE and k!='image_path' for k in u):raise ValueError('Read-only field')
        for k,v in changes.items():
            if not isinstance(v,str):raise ValueError('Fields must be strings')
            if k in ENUMS and v not in ENUMS[k]:raise ValueError('Invalid '+k)
        candidate={**r,**changes}
        validate_annotation(candidate)
        r.update(changes);r['visual_review_at']=now()
    save_labels(rows);reports(rows)

def decide(a,b,decision):
    paths={r['image_path'] for r in read_labels()}
    if a not in paths or b not in paths or a==b:raise ValueError('Invalid pair')
    ds=read_json(WORK/'duplicate_decisions.json',[])
    ds=[p for p in ds if {p['a'],p['b']}!={a,b}]
    ds.append({'a':a,'b':b,'decision':decision,'at':now()});atomic_json(WORK/'duplicate_decisions.json',ds)
    rows=read_labels();inv=read_json(WORK/'inventory.json',{});regroup(rows,inv);save_labels(rows);duplicate_report(rows,inv);reports(rows,inv)

def prompt_for(row,strength='small'):
    target=TARGETS[row['folder']]
    add=('Add only a few small stuck rice grains, dry crumbs and tiny sauce smears on the visible inner bottom, less than 5 percent coverage. No puddle, pooled liquid, soup, beverage or wet sheen.' if target=='food' else
         'Add only a shallow small amount of visibly realistic leftover beverage at the visible interior bottom (about 1 to 3 percent capacity), with a plausible meniscus and a few inner droplets. Do not fill the container. No food.')
    if row['folder']=='paper_cups':
        add='Add only three to six small realistic brown coffee droplets and one thin short coffee streak on the already visible REAR INNER WALL just below the rim. The bottom is not visible: do not expose it, do not move the camera, and do not invent a visible bottom pool. Keep the cup almost empty. No food, no full drink, no splashes outside the cup.'
    if strength=='visible':
        if target=='food':
            add='Make food residue clearly visible but modest: approximately 10 to 15 percent of the visible inner bottom covered by about 15 to 25 scattered cooked rice grains in two or three small loose clusters, dry crumbs, and two small thin orange-brown sauce smears. Leave at least 85 percent of the interior surface visible. No mound, meal, large food chunks, puddle, pooled liquid, soup, beverage, glossy wet pool or food outside the container. Keep the entire rim, walls and outline unobstructed.'
        elif row['folder']=='paper_cups':
            add='Make liquid residue more clearly visible on the already visible REAR INNER WALL: six to ten distinct medium brown coffee droplets, two short thin run trails and a small translucent coffee smear on the inner wall just below the rim. These must look like wet beverage residue, not food crumbs or painted decoration. Do not expose the hidden bottom or move the camera. Do not fill the cup. Leave at least 85 percent of the visible inner wall clean; keep the rim, outer surface, graphics and whole silhouette unobstructed.'
        else:
            add='Make a clearly visible shallow layer of translucent amber leftover tea at the lowest visible interior bottom, approximately 8 to 12 percent of container capacity, with a distinct physically plausible horizontal meniscus and a few visible inner droplets. The upper 85 percent of the bottle must visibly remain empty air, not filled clear water. No full drink, opaque liquid, food, liquid outside the bottle, or obstruction of the bottle outline, ridges or labels. Respect gravity and the existing pose; for a crushed bottle adapt the shallow liquid to the bottom recesses.'
    if strength=='coffee-surface':
        if row['folder']!='paper_cups':raise ValueError('Coffee surface style applies only to paper cups')
        add='The user wants a clearly recognizable COFFEE LIQUID SURFACE, like the dark coffee in paper_cups/Image_30.png, not merely wall droplets. Add a modest low pool of dark brown leftover coffee, roughly 20 to 25 percent of cup capacity. Render a clear glossy horizontal coffee surface with a small natural highlight and a few tiny bubbles at the far edge, visible only where physically possible through the EXISTING opening and viewing angle. Keep the liquid level well below the rim and leave most of the cavity empty. Do not fill to the top. Do not add food, a muffin, new props, a new background, or a collage. Preserve the entire paper cup, graphics, handle if present, silhouette, existing inner walls, and camera view. The coffee must not cover or obscure the cup exterior. No decorative brown dots or thick paint on the wall as a substitute for liquid.'
    return ('Use case: precise-object-edit. Asset type: waste container dataset photograph. Input image 1 is the edit target: '+row['image_path']+'. '+add+
            ' Preserve the exact object category, material, shape, count, camera angle, framing, background, light, shadows, labels, and existing image detail. Change only the interior residue. Keep the original image aspect ratio. Do not open lids, alter opacity, move objects, invent a new view, add captions, panels, collage, logos or watermark. Output one edited photograph. If residue cannot be visible from this view, this source is unsuitable; do not change the view to make it possible.')

def plan(mode='pilot'):
    rows=read_labels();tasks=read_json(WORK/'generation_tasks.json',[]);inv=read_json(WORK/'inventory.json',{})
    bypath={r['image_path']:r for r in rows}
    for folder,target in TARGETS.items():
        existing=[t for t in tasks if t['folder']==folder and t.get('mode')==mode]
        # Pilot is a hard cap of two distinct source tasks per folder. Failed
        # tasks remain explicit; retry requires the separate retry command.
        if mode=='pilot':needed=max(0,2-len(existing))
        else:
            with (WORK/'reports'/'usable_manifest.csv').open(encoding='utf-8-sig',newline='') as f:usable=list(csv.DictReader(f))
            valid=[r for r in usable if r['folder']==folder and r['residual_applicable']=='yes']
            if any(r['folder']==folder and r['origin']=='original' and r['review_status']=='pending' for r in rows):continue
            awaiting=sum(t['status'] in ('queued','running') or
                         (t['status']=='success' and bypath.get(t.get('output_path'),{}).get('review_status')=='pending')
                         for t in tasks if t['folder']==folder)
            needed=max(0,sum(r['residual']=='none' for r in valid)-sum(r['residual'] in ('food','liquid') for r in valid)-awaiting)
        used={t['source_path'] for t in tasks}
        used_groups={bypath[p]['group_id'] for p in used if p in bypath}
        sources=[r for r in rows if r['folder']==folder and generation_eligible(r)
                 and r['image_path'] not in used and r['group_id'] not in used_groups
                 and not inv[r['image_path']]['error'] and not inv[r['image_path']].get('original_changed')]
        selected=[]
        for r in sources:
            if r['group_id'] in used_groups:continue
            used_groups.add(r['group_id']);selected.append(r)
        for r in selected[:needed]:
            tasks.append({'task_id':'t_'+digest((r['source_id']+':'+mode+':residue-v1').encode())[:20],
                          'mode':mode,'folder':folder,'source_id':r['source_id'],'source_path':r['image_path'],
                          'source_sha256':inv[r['image_path']]['sha256'],'target_residual':target,'prompt':prompt_for(r,'visible' if mode=='balance' else 'small'),
                          'status':'queued','output_path':'','error':'','created_at':now(),'attempts':0})
    atomic_json(WORK/'generation_tasks.json',tasks)
    write_csv(WORK/'generation_tasks.csv',tasks,['task_id','mode','folder','source_path','source_id','target_residual','prompt','output_path','status','error'])
    reports();print('Queued:',sum(t['status']=='queued' for t in tasks))

def get_task(taskid):
    tasks=read_json(WORK/'generation_tasks.json',[])
    t=next((t for t in tasks if t['task_id']==taskid),None)
    if t is None:raise ValueError('Unknown task id; copy task_id from generation_tasks.json')
    return tasks,t

def plan_revision(source_file,revision,folders=None,strength='visible'):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',revision):raise ValueError('Use letters, digits, underscore or hyphen for revision')
    paths=read_json(source_file,[]);rows={r['image_path']:r for r in read_labels()};inv=read_json(WORK/'inventory.json',{})
    folders=folders or list(TARGETS)
    if not isinstance(paths,list) or len(set(paths))!=len(paths) or Counter(rows[p]['folder'] for p in paths)!=Counter({f:2 for f in folders}):
        raise ValueError('Revision pilot requires exactly two distinct sources in each selected category')
    tasks=read_json(WORK/'generation_tasks.json',[]);existing={t['task_id'] for t in tasks}
    for path in paths:
        r=rows[path]
        tid='t_'+digest((r['source_id']+':'+revision).encode())[:20]
        if tid in existing:continue
        if not generation_eligible(r) or inv[path]['error'] or inv[path].get('original_changed'):
            raise ValueError('Source not visually eligible: '+path)
        tasks.append({'task_id':tid,'mode':revision,'revision':revision,'strength':strength,'folder':r['folder'],
                      'source_id':r['source_id'],'source_path':path,'source_sha256':inv[path]['sha256'],
                      'target_residual':TARGETS[r['folder']],'prompt':prompt_for(r,strength),'status':'queued',
                      'output_path':'','error':'','created_at':now(),'attempts':0})
    atomic_json(WORK/'generation_tasks.json',tasks);event('revision_planned',revision=revision,sources=paths,strength=strength);reports()
def reserve(taskid):
    tasks,t=get_task(taskid)
    if t['status']!='queued':raise ValueError('Only queued task may start; running/success tasks are never automatically regenerated')
    source=next((r for r in read_labels() if r['image_path']==t['source_path']),None)
    if not source or not generation_eligible(source):raise ValueError('Source no longer an approved, visually eligible no-residue original')
    if digest(image_path(t['source_path']).read_bytes())!=t['source_sha256']:raise ValueError('Source changed')
    reserved={q['output_path'].lower() for q in tasks if q.get('output_path')}
    n=251
    while (image_path(f"{t['folder']}/Image_{n}.png").exists() or f"{t['folder']}/Image_{n}.png".lower() in reserved):n+=1
    t.update(status='running',output_path=f"{t['folder']}/Image_{n}.png",started_at=now(),attempts=t['attempts']+1)
    atomic_json(WORK/'generation_tasks.json',tasks);event('started',**t);print(json.dumps(t,ensure_ascii=False,indent=2))
def complete(taskid,generated_file):
    tasks,t=get_task(taskid)
    if t['status']=='success':print('Already completed; skipped');return
    if t['status']!='running':raise ValueError('Reserve task first')
    p=Path(generated_file); info=inspect_file(p)
    if info['error']:raise ValueError(info['error'])
    with Image.open(p) as im:
        im=ImageOps.exif_transpose(im);out=io.BytesIO();im.save(out,format='PNG');payload=out.getvalue()
    # Persist checksum BEFORE exclusive copy. Recovery can safely recognize a
    # completed copy after power loss without reissuing a generation request.
    t['output_sha256']=digest(payload);t['tool_output_file']=str(p)
    atomic_json(WORK/'generation_tasks.json',tasks)
    dest=image_path(t['output_path'])
    with dest.open('xb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
    t.update(status='success',finished_at=now(),error='')
    atomic_json(WORK/'generation_tasks.json',tasks);event('success',**t)
    scan()
def recover():
    tasks=read_json(WORK/'generation_tasks.json',[])
    for t in tasks:
        if t['status']=='running' and t.get('output_sha256') and image_path(t['output_path']).exists():
            p=image_path(t['output_path'])
            if digest(p.read_bytes())==t['output_sha256'] and not inspect_file(p)['error']:
                t.update(status='success',finished_at=now());event('recovered_success',**t)
            else:t.update(status='interrupted',error='Partial/mismatching output; preserved for investigation. Never overwritten.');event('interrupted',**t)
    atomic_json(WORK/'generation_tasks.json',tasks);scan()

def serve(port):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def send(self,data,ctype='application/json',status=200):
            self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
        def do_GET(self):
            path=unquote(urlparse(self.path).path)
            if path=='/':self.send((ROOT/'review_ui.html').read_text('utf-8').replace('__TOKEN__',token).encode(),'text/html; charset=utf-8')
            elif path=='/api/rows':self.send(json.dumps(read_labels(),ensure_ascii=False).encode())
            elif path=='/api/duplicates':
                p=WORK/'reports'/'near_duplicates.csv'
                with p.open(encoding='utf-8-sig') as f:ds=list(csv.DictReader(f))
                self.send(json.dumps(ds).encode())
            elif path.startswith('/image/'):
                try:
                    p=image_path(path[7:])
                    with Image.open(p) as im:
                        im=ImageOps.exif_transpose(im);im.thumbnail((1400,1400));buf=io.BytesIO();im.convert('RGB').save(buf,format='JPEG',quality=93)
                    self.send(buf.getvalue(),'image/jpeg')
                except Exception as e:self.send(str(e).encode(),'text/plain',404)
            else:self.send(b'Not found','text/plain',404)
        def do_POST(self):
            if self.headers.get('X-Review-Token')!=token:self.send(b'Forbidden','text/plain',403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size>1000000:raise ValueError('Payload too large')
                body=json.loads(self.rfile.read(size))
                with lock():
                    if self.path=='/api/annotate':annotate([body])
                    elif self.path=='/api/duplicate':decide(body['a'],body['b'],body['decision'])
                    else:raise ValueError('Unknown endpoint')
                self.send(b'{"ok":true}')
            except Exception as e:self.send(json.dumps({'error':str(e)},ensure_ascii=False).encode(),status=400)
    print(f'Local review: http://127.0.0.1:{port} (Ctrl+C to stop)',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    for c in ('scan','contacts','report','split','recover'):sub.add_parser(c)
    q=sub.add_parser('serve');q.add_argument('--port',type=int,default=8765)
    q=sub.add_parser('annotate');q.add_argument('json_file',type=Path)
    q=sub.add_parser('duplicate');q.add_argument('a');q.add_argument('b');q.add_argument('decision',choices=['same','different'])
    q=sub.add_parser('plan');q.add_argument('--mode',choices=['pilot','balance'],default='pilot')
    q=sub.add_parser('plan-revision');q.add_argument('sources_file',type=Path);q.add_argument('--revision',required=True);q.add_argument('--folders',nargs='+',choices=list(TARGETS));q.add_argument('--strength',choices=['visible','coffee-surface'],default='visible')
    q=sub.add_parser('reserve');q.add_argument('task_id')
    q=sub.add_parser('complete');q.add_argument('task_id');q.add_argument('generated_file')
    q=sub.add_parser('fail');q.add_argument('task_id');q.add_argument('reason')
    q=sub.add_parser('retry');q.add_argument('task_id')
    args=p.parse_args()
    if args.cmd=='serve':serve(args.port);return
    with lock():
        if args.cmd=='scan':scan()
        elif args.cmd=='contacts':contacts()
        elif args.cmd=='report':reports()
        elif args.cmd=='annotate':annotate(read_json(args.json_file,[]))
        elif args.cmd=='duplicate':decide(args.a,args.b,args.decision)
        elif args.cmd=='split':
            rows=read_labels();regroup(rows,read_json(WORK/'inventory.json',{}),reset=True);save_labels(rows);reports(rows)
        elif args.cmd=='plan':plan(args.mode)
        elif args.cmd=='plan-revision':plan_revision(args.sources_file,args.revision,args.folders,args.strength)
        elif args.cmd=='reserve':reserve(args.task_id)
        elif args.cmd=='complete':complete(args.task_id,args.generated_file)
        elif args.cmd=='recover':recover()
        elif args.cmd=='fail':
            tasks,t=get_task(args.task_id)
            if t['status']=='success':raise ValueError('Cannot fail completed task')
            t.update(status='failed',error=args.reason,finished_at=now());atomic_json(WORK/'generation_tasks.json',tasks);event('failed',**t);reports()
        elif args.cmd=='retry':
            tasks,t=get_task(args.task_id)
            if t['status'] not in ('failed','interrupted'):raise ValueError('Only explicitly failed/interrupted tasks can retry')
            if t.get('output_path') and image_path(t['output_path']).exists():raise ValueError('Existing output must be investigated, not overwritten')
            t.update(status='queued',output_path='',error='');atomic_json(WORK/'generation_tasks.json',tasks);event('retry_queued',**t)

if __name__=='__main__':main()
