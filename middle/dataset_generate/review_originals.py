"""Auditable, resumable visual review of target ORIGINALS only.

prepare backs up labels and creates full-resolution 25-image sheets.
record accepts 25 explicit per-image observation codes AFTER viewing a sheet.
apply requires complete coverage and unchanged baseline before editing labels.
No classifiers, filename heuristics, image mutations, or generation calls.
"""
import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from PIL import Image,ImageDraw,ImageOps
import waste_workflow as w

RUN=w.WORK/'reviews'/'original_review_20261017'
CODES={
 'R':('yes','none','review','可見內底無殘留，但材質／細類或後續編輯可見性仍需另核實，不直接列為 eligible。'),
 'U':('unknown','','exclude','容器內部／底部不可完整判讀，或多容器的殘留狀態無法一致確認；不以反光、背景或外觀推定 none。'),
 'B':('unknown','','review','單一容器可辨，但內部可見性／材質或透明液體仍有歧義；殘留與編輯來源需另行確認，不列 eligible。'),
 'N':('yes','none','exclude','可見容器內部無殘留，但有多容器／堆疊等編輯限制，不適合作為單一容器生成來源。'),
 'E':('yes','none','eligible','單一主要容器清楚，內底／透明瓶內可判讀且未見殘留；現有視角能合理呈現新增殘留。'),
 'L':('yes','liquid','exclude','可見容器內飲料／液體或液滴；已有液體內容，不作無殘留生成來源。滿裝飲料另視為內容情境，非少量殘留示例。'),
 'F':('yes','food','exclude','可見容器內食物／食物碎屑，未見明顯積液；已有食物內容，不作無殘留生成來源。滿裝餐食非少量殘留示例。'),
 'Q':('yes','','exclude','mixed：可見食物與液體明顯並存；完成圖片複核但單一殘留標籤無法表示，不納入三分類訓練與比例統計。'),
 'X':('no','','exclude','圖表／文字宣傳／教學拼貼／非實際目標容器等不適合保留的樣本，排除；殘留標註不適用。'),
 'W':('unknown','','exclude','物品材質／細類與資料夾明顯不符，排除；不自動改分類。'),
}

def prepare():
    if (RUN/'baseline.csv').exists():print('Existing review baseline; resume without replacing backup:',RUN);return
    RUN.mkdir(parents=True,exist_ok=True)
    with w.lock():
        stamp=w.now().replace(':','').replace('+','_')
        backup=w.WORK/'backups'/f'labels_before_original_review_{stamp}.csv'
        backup.parent.mkdir(exist_ok=True);shutil.copy2(w.LABELS,backup);shutil.copy2(w.LABELS,RUN/'baseline.csv')
        rows=w.read_labels()
        hashes={r['image_path']:w.digest(w.image_path(r['image_path']).read_bytes()) for r in rows}
        w.atomic_json(RUN/'baseline_hashes.json',hashes)
        w.atomic_json(RUN/'run.json',{'backup':str(backup),'started_at':w.now(),'labels_sha256':w.digest(w.LABELS.read_bytes()),'scope':'five target folders, original only'})
    sheets=[]
    for folder in w.TARGETS:
        selected=sorted((r for r in rows if r['folder']==folder and r['origin']=='original'),key=lambda r:w.natural(r['filename']))
        for off in range(0,len(selected),25):
            part=selected[off:off+25];canvas=Image.new('RGB',(1280,5*294),'#eeeeee');draw=ImageDraw.Draw(canvas)
            key=f'{folder}_{off//25+1:02d}'
            for i,r in enumerate(part):
                x=i%5*256;y=i//5*294
                with Image.open(w.image_path(r['image_path'])) as im:
                    im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((256,256));canvas.paste(im,(x+(256-im.width)//2,y))
                label=f"{r['filename']} {r['review_status'][0]} {r['residual_applicable']} {r['residual'] or '-'} {r['generation_candidate'] or '-'}"
                draw.text((x+3,y+258),label[:48],fill='black')
                draw.text((x+3,y+273),f'index {i+1:02d}',fill='black')
            p=RUN/'sheets'/f'{key}.png';p.parent.mkdir(exist_ok=True);canvas.save(p)
            sheets.append({'sheet':key,'paths':[r['image_path'] for r in part]})
    w.atomic_json(RUN/'sheets.json',sheets)
    w.atomic_json(RUN/'codes.json',CODES)
    print('Backup:',backup);print('Sheets:',len(sheets),'Images:',sum(len(s['paths']) for s in sheets))
    print({f:dict(Counter(r['review_status'] for r in rows if r['folder']==f and r['origin']=='original')) for f in w.TARGETS})

def record(sheet,codes,overrides=None):
    if (RUN/'verification.json').exists():raise ValueError('Review already applied; preserve its evidence and create a new run for later reviews')
    item=next(s for s in w.read_json(RUN/'sheets.json',[]) if s['sheet']==sheet)
    codes=codes.replace(' ','').replace(',','')
    if len(codes)!=len(item['paths']) or set(codes)-set(CODES):raise ValueError('Need one valid explicit observation code per image')
    records=w.read_json(RUN/'observations.json',{})
    overrides=overrides or {}
    for i,(path,code) in enumerate(zip(item['paths'],codes),1):
        records[path]={'code':code,'sheet':sheet,'index':i,'at':w.now(),**overrides.get(str(i),{})}
    w.atomic_json(RUN/'observations.json',records);print(sheet,'recorded',len(codes),'total',len(records))

def apply():
    if (RUN/'verification.json').exists():print('Review already applied; skipped without changing labels.');return
    with (RUN/'baseline.csv').open(encoding='utf-8-sig',newline='') as f:before=list(csv.DictReader(f))
    obs=w.read_json(RUN/'observations.json',{})
    target={r['image_path'] for r in before if r['folder'] in w.TARGETS and r['origin']=='original'}
    if set(obs)!=target:raise ValueError(f'Incomplete review: {len(obs)}/{len(target)}')
    with w.lock():
        rows=w.read_labels()
        if rows!=before:raise ValueError('labels changed during review; reconcile against baseline before applying')
        hashes=w.read_json(RUN/'baseline_hashes.json',{})
        for path,sha in hashes.items():
            if w.digest(w.image_path(path).read_bytes())!=sha:raise ValueError('Image changed during review: '+path)
        details=[];fields=[]
        for r in rows:
            path=r['image_path']
            if path not in target:continue
            old=r.copy();o=obs[path];app,res,candidate,reason=CODES[o['code']]
            reason=o.get('reason',reason)
            if o['code']=='Q':reason='mixed：食物與液體並存。'+reason
            status='excluded' if old['review_status']=='excluded' or o['code'] in ('X','W') else 'approved'
            if old['review_status']=='excluded':candidate='exclude';reason='原先 excluded 維持排除，保留既有理由。'+reason
            changed=[k for k,v in {'residual_applicable':app,'residual':res,'generation_candidate':candidate,'review_status':status}.items() if old[k]!=v]
            note='[2026-10-17 全原圖看圖複核] '+reason
            if changed:note+=' 修正欄位：'+','.join(changed)+'；依實際畫面與保守可判讀原則修正，非依檔名推論。'
            r.update(residual_applicable=app,residual=res,generation_candidate=candidate,review_status=status,
                     notes=(old['notes']+'\n' if old['notes'] else '')+note)
            w.validate_annotation(r)
            # Keep user's reviewer identity; store this second review separately.
            r['original_recheck_by']='Codex visual review requested by user'
            r['original_recheck_at']=o['at'];r['original_recheck_sheet']=o['sheet'];r['original_recheck_code']=o['code']
            for k in ('residual_applicable','residual','generation_candidate','review_status','notes'):
                if old[k]!=r[k]:fields.append({'image_path':path,'field':k,'before':old[k],'after':r[k],'reason':reason,'sheet':o['sheet']})
            details.append({'image_path':path,'before_status':old['review_status'],'after_status':status,'before_applicable':old['residual_applicable'],'after_applicable':app,
                            'before_residual':old['residual'],'after_residual':res,'before_candidate':old['generation_candidate'],'after_candidate':candidate,
                            'decision':o['code'],'reason':reason,'changed_fields':','.join(changed),'before_notes':old['notes'],'after_notes':r['notes'],'sheet':o['sheet']})
        assert all(r==old for r,old in zip(rows,before) if r['image_path'] not in target)
        assert all(r['review_status']=='excluded' for r,old in zip(rows,before) if old['review_status']=='excluded' and r['image_path'] in target)
        assert not any(r['review_status']=='pending' for r in rows if r['image_path'] in target)
        w.save_labels(rows);w.reports(rows)
        saved={r['image_path']:r for r in w.read_labels()}
        for old in before:
            if old['image_path'] not in target:
                assert all(saved[old['image_path']][k]==v for k,v in old.items())
        assert all(w.digest(w.image_path(path).read_bytes())==sha for path,sha in hashes.items())
        w.write_csv(RUN/'review_details.csv',details)
        w.write_csv(RUN/'field_changes.csv',fields)
        summary=[]
        for folder in w.TARGETS:
            rs=[r for r in rows if r['folder']==folder and r['origin']=='original']
            eligible=[r for r in rs if w.generation_eligible(r)]
            used={t['source_path'] for t in w.read_json(w.WORK/'generation_tasks.json',[]) if t['status'] in ('queued','running','success')}
            summary.append({'folder':folder,'total':len(rs),'approved':sum(r['review_status']=='approved' for r in rs),'excluded':sum(r['review_status']=='excluded' for r in rs),'pending':sum(r['review_status']=='pending' for r in rs),
                            'approved_none':sum(w.residual_usable(r) and r['residual']=='none' for r in rs),'approved_food':sum(w.residual_usable(r) and r['residual']=='food' for r in rs),'approved_liquid':sum(w.residual_usable(r) and r['residual']=='liquid' for r in rs),
                            'approved_unknown':sum(r['review_status']=='approved' and r['residual_applicable']=='unknown' for r in rs),
                            'approved_no':sum(r['review_status']=='approved' and r['residual_applicable']=='no' for r in rs),
                            'approved_mixed_blank':sum(r['review_status']=='approved' and r['residual_applicable']=='yes' and not r['residual'] for r in rs),
                            'generation_eligible':len(eligible),
                            'generation_eligible_groups':len({r['group_id'] for r in eligible}),
                            'generation_unused_sources':sum(r['image_path'] not in used for r in eligible)})
        w.write_csv(RUN/'summary.csv',summary)
        w.atomic_json(RUN/'verification.json',{'finished_at':w.now(),'reviewed':len(target),'no_pending_in_scope':True,'generated_rows_unchanged':True,
                                               'out_of_scope_rows_unchanged':True,'image_hashes_unchanged':True,'existing_excluded_never_restored':True,
                                               'existing_notes_preserved_as_prefix':True,'backup':w.read_json(RUN/'run.json',{})['backup']})
        print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd',required=True);sp.add_parser('prepare');sp.add_parser('apply')
    q=sp.add_parser('record');q.add_argument('sheet');q.add_argument('codes');q.add_argument('--overrides',type=Path)
    a=p.parse_args()
    if a.cmd=='prepare':prepare()
    elif a.cmd=='record':record(a.sheet,a.codes,w.read_json(a.overrides,{}) if a.overrides else {})
    else:apply()
