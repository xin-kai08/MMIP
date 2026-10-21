"""One-time visual review notes made by Codex, all pending human review.

Run only once; subsequent changes belong in the local UI or annotate JSON.
This file is evidence of this session, not an automatic image classifier.
"""
import json
from pathlib import Path
updates=[]
def add(folder,n,residual='',app='unknown',candidate='exclude',note=''):
    updates.append(dict(image_path=f'{folder}/Image_{n}.png',residual=residual,
                        residual_applicable=app,review_status='pending',generation_candidate=candidate,
                        visual_review_by='Codex visual preliminary; human review required',notes=note))
for n in (11,16):add('glass_beverage_bottles',n,'none','yes','eligible','已檢視單張：透明單瓶，底部可見且初看無殘留；待人工確認。')
for n in (145,192):add('paper_cups',n,'','yes','eligible','已檢視單張：可見後側內壁，杯底不可見，原圖殘留不確定；試作僅能在可見內壁加少量咖啡液滴，不可改視角；待人工複核。')
add('plastic_water_bottles',50,'none','yes','eligible','已檢視單張：手握單一透明壓扁空瓶，底部可見，初看無殘留；手部不得改動；待人工確認。')
add('plastic_water_bottles',81,'','yes','eligible','已檢視單張：單一透明開口瓶，底部可見；商品照反光使原圖是否有透明液體仍不確定，不標 none；可試作少量有色液體，待人工複核。')
for n in (30,74):add('plastic_food_containers',n,'none','yes','eligible','已檢視單張：透明單一餐盒，內部／底部可見，初看空盒；保留透明蓋及既有背景／文字；待人工確認。')
for n in (6,37):add('styrofoam_food_containers',n,'none','yes','eligible','已檢視單張：開蓋單一白色餐盒，底部清楚，初看無殘留；只加少量食物碎屑且不得有積液；待人工確認。')
for folder,ns,note in [
 ('glass_beverage_bottles',[1,3,5,6,7,8,9,10,12,13,14,17,20,21,22,23,25,29,30,31,33,35,37,38,40,42,44,45,46,47],'聯絡表檢視：多瓶／多物品或滿裝商品陳列，不適合此輪單物品少量殘留編輯；殘留留白。'),
 ('paper_cups',[1,4,5,6,7,10,11,12,14,15,16,17,18,19,20,21,22,24,26,27,28,29,31,32,33,34,35,39,40,41,42,43,45,46,48],'聯絡表檢視：多物品／拼貼／有蓋遮擋，不適合本輪編輯；殘留留白。'),
 ('paper_cups',[3,8,13,23,25,36,37,38,47,54,56,71,73,76,84,90,91,102,112,117,118,119,121,128,136,140,142,143,144,146,148,149,150,152,162,164,169,170,171,174,178,184,193,194,204,205,206,208,210,217,223,227,228,233,243,249],'聯絡表檢視：圖表／拼貼／教學／大型造型或非清楚單杯照片，候選排除；需人工檢查物品細類。'),
 ('plastic_water_bottles',[1,3,4,6,8,9,11,12,14,16,17,19,20,21,23,24,25,26,27,28,29,30,31,32,34,35,36,37,38,39,40,41,42,43,46,47,48,49,51,52,53,54,56,58,60,61,62,63,64,65,66,67,68,69,70,71,72,73,75,76,77,78,79,82,84,85,86,87,88,89,90,91,92,94,95,96],'聯絡表檢視：多瓶／垃圾堆／海洋場景／宣傳圖／非單一清楚容器，候選排除；不以背景推論殘留。'),
 ('plastic_food_containers',[1,2,3,4,5,6,7,8,9,10,11,13,14,15,16,17,19,20,21,22,23,24,25,26,27,28,29,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,56,57,58,59,60,61,62,63,64,65,66,67,68,69,70,71,72,73,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96],'聯絡表檢視：多盒／滿裝食物／不透明或蓋子遮擋內部，候選排除；不把滿裝商品當成適合加少量殘留的來源。'),
 ('styrofoam_food_containers',[1,2,3,4,5,7,8,9,10,11,12,13,14,15,16,18,20,21,22,24,25,26,27,28,29,30,32,33,34,35,36,38,39,40,41,44,45,46,47,48],'聯絡表檢視：多物品／閉蓋遮擋／滿裝食物或疑似非保麗龍材質，候選排除；物品材質需人工複核。')]:
    for n in ns:add(folder,n,note=note)
for folder,n,note in [('glass_beverage_bottles',15,'棕色不透明／深色瓶，底部內部不可確認。'),('plastic_food_containers',75,'已檢視單張：半透明圓盒且商品浮水印覆蓋，內部不清楚，本輪排除。'),('paper_cups',44,'已檢視單張：杯底不可見，只能看到上方內壁，本輪候選排除。')]:add(folder,n,note=note)
for n in (30,61,97,108,157,185,212,231):add('paper_cups',n,'liquid','yes','exclude','看圖初判有明顯飲料（多為滿杯，非少量殘留）；待人工複核，本輪不再加液體。')
add('styrofoam_food_containers',23,'food','yes','exclude','看圖初判開盒有食物及醬料殘留，未看見明顯積液；需人工複核是否有液體並存。')
out=Path(__file__).parent/'dataset_workflow'/'initial_visual_review.json'
out.parent.mkdir(exist_ok=True)
if out.exists():raise SystemExit('Review evidence already exists; use UI to preserve subsequent labels.')
out.write_text(json.dumps(updates,ensure_ascii=False,indent=2),encoding='utf-8')
print(len(updates),'initial pending reviews written')
