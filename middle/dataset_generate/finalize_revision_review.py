"""One-time evidence of the visible-v2 / coffee-surface-v3 visual inspection."""
import os
from html import escape
from PIL import Image,ImageOps,ImageDraw
import waste_workflow as w

if (w.WORK/'revision_visual_review.json').exists():raise SystemExit('Evidence exists; use the review UI for later edits.')
tasks=w.read_json(w.WORK/'generation_tasks.json',[])
updates=[];qa=[]
for t in tasks:
    if t['mode']=='pilot':continue
    if t['status']!='success':raise RuntimeError('Incomplete revision task '+t['task_id'])
    target=t['target_residual'];note=''
    if target=='food':note='已逐張看圖：米粒、碎屑及醬痕比首輪明顯，盒底大部分可見，未見明顯積液；本體輪廓、材質與視角初看合理。待人工驗收，勿依提示詞直接核准。'
    elif t['mode']=='coffee-surface-v3':note='已逐張看圖：清楚可見深咖啡液面、反光與少量泡沫；液位低於杯口，外側杯身與圖案未被遮擋。液體比例不是實測值；待人工複核。'
    elif t['folder']=='paper_cups':note='已逐張看圖：內壁液滴與短流痕更明顯，杯身未遮擋；使用者後續要求可見咖啡液面，請優先複核 Image_255、Image_256，本版保留作比較。'
    else:note='已逐張看圖：底部清楚可見琥珀色淺層液體及液面，上方大部分瓶身空且外形可辨。保留原視角；待人工驗收。'
    updates.append(dict(image_path=t['output_path'],residual=target,residual_applicable='yes',review_status='pending',
                        generation_candidate='',visual_review_by='Codex visual preliminary; human review required',notes=note))
    qa.append(dict(task_id=t['task_id'],mode=t['mode'],source_path=t['source_path'],output_path=t['output_path'],observed_residual=target,qa_status='pending_human_review',notes=note))
with w.lock():
    w.atomic_json(w.WORK/'revision_visual_review.json',updates);w.annotate(updates)
    w.write_csv(w.WORK/'reports'/'revision_qa.csv',qa)
out=w.WORK/'pilot_preview';out.mkdir(exist_ok=True)
html=['<!doctype html><meta charset="utf-8"><title>生成版本對照</title><style>body{font:16px system-ui;margin:24px}section{margin:30px 0}article{display:inline-block;vertical-align:top;width:650px;margin:12px}img{width:300px;height:300px;object-fit:contain;background:#eee}p{max-width:620px}</style><h1>原圖與生成版本對照</h1><p>所有生成圖均待人工複核。紙杯最新版請看 coffee-surface-v3 的 Image_255 / Image_256。點圖開啟原尺寸。</p>']
for folder in w.TARGETS:
    html.append('<section><h2>'+escape(folder)+'</h2>')
    ts=[t for t in tasks if t['folder']==folder and t['status']=='success']
    for mode in sorted({t['mode'] for t in ts}):
        batch=[t for t in ts if t['mode']==mode]
        sheet=Image.new('RGB',(1000,540*len(batch)),'#eeeeee');draw=ImageDraw.Draw(sheet)
        for i,t in enumerate(batch):
            html.append('<article><h3>'+escape(mode)+'</h3>')
            for j,rel in enumerate((t['source_path'],t['output_path'])):
                with Image.open(w.image_path(rel)) as im:
                    im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((480,480));sheet.paste(im,(j*500+(500-im.width)//2,i*540))
                draw.text((j*500+8,i*540+486),('SOURCE: ' if j==0 else 'EDIT: ')+rel,fill='black')
                url=os.path.relpath(w.image_path(rel),out).replace('\\','/')
                html.append('<a href="'+escape(url)+'"><img src="'+escape(url)+'" alt="'+escape(rel)+'"></a>')
            html.append('<p>'+escape(t['source_path'])+' → '+escape(t['output_path'])+'</p></article>')
        sheet.save(out/f'{folder}_{mode}.jpg',quality=92)
    html.append('</section>')
(out/'index.html').write_text('\n'.join(html),encoding='utf-8')
print('Gallery:',out/'index.html')
