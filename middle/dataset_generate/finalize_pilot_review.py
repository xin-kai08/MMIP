"""Session-specific visual inspection evidence, not an automated classifier."""
import csv
from PIL import Image,ImageOps,ImageDraw
import waste_workflow as w

if (w.WORK/'pilot_visual_review.json').exists():
    raise SystemExit('Pilot review evidence already exists; use the UI for subsequent edits.')
updates=[];qa=[]
for t in w.read_json(w.WORK/'generation_tasks.json',[]):
    p=t['output_path'];target=t['target_residual']
    note=('已看圖初判底部有少量食物碎屑／米粒／醬痕，未見明顯積液；材質、角度及背景仍需人工驗收。' if target=='food' else
          '已看圖初判有可見少量液體／液滴；材質、角度、背景與殘留量仍需人工驗收。')
    residual=target;candidate='';qa_state='pending_human_review'
    if p=='plastic_water_bottles/Image_252.png':
        residual='';candidate='exclude';qa_state='needs_rework'
        note='已看圖：瓶底液體與反光不易區分，肩部疑似有液面，可能看似滿瓶；原圖亦有透明液體歧義。不確認 residual，待人工判斷或換來源重做。'
    if p=='plastic_food_containers/Image_252.png':
        candidate='exclude';qa_state='needs_rework'
        note='已看圖：可見少量米粒／碎屑且未見積液，但原圖底部黑色文字條與既有文字被移除／改動，違反保留背景細節要求；待修正，不列合格樣本。'
    updates.append(dict(image_path=p,residual=residual,residual_applicable='yes',review_status='pending',generation_candidate=candidate,
                        visual_review_by='Codex visual preliminary; human review required',notes=note))
    qa.append(dict(task_id=t['task_id'],source_path=t['source_path'],output_path=p,target_residual=target,
                   observed_residual=residual,qa_status=qa_state,notes=note))
with w.lock():
    w.atomic_json(w.WORK/'pilot_visual_review.json',updates)
    w.annotate(updates)
    w.write_csv(w.WORK/'reports'/'pilot_qa.csv',qa)
# Only derived preview canvases are resized; dataset images stay untouched.
out=w.WORK/'pilot_preview';out.mkdir(exist_ok=True)
for folder in w.TARGETS:
    ts=[t for t in w.read_json(w.WORK/'generation_tasks.json',[]) if t['folder']==folder]
    sheet=Image.new('RGB',(1000,1080),'#eeeeee');draw=ImageDraw.Draw(sheet)
    for i,t in enumerate(ts):
        for j,rel in enumerate((t['source_path'],t['output_path'])):
            with Image.open(w.image_path(rel)) as im:
                im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((480,480))
                sheet.paste(im,(j*500+(500-im.width)//2,i*540))
            draw.text((j*500+8,i*540+486),('SOURCE: ' if j==0 else 'EDIT: ')+rel,fill='black')
    sheet.save(out/f'{folder}.jpg',quality=92)
print('Pilot comparison sheets:',out)
