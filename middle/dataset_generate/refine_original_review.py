"""Specific follow-up observations after viewing individual ambiguous images."""
import review_originals as v
import waste_workflow as w
if (v.RUN/'verification.json').exists():raise SystemExit('Review already applied; preserving the visual evidence.')
updates={
 'glass_beverage_bottles/Image_2.png':('Q','透明單瓶內可見檸檬片／植物與液體同時存在；mixed 留白，不硬標 liquid 或 food。'),
 'glass_beverage_bottles/Image_4.png':('B','波紋玻璃瓶的折射、紋理與透明液體難以分辨，不能據此確認 none；旁邊橙汁在另一個杯中，不能作為瓶內殘留證據。'),
 'glass_beverage_bottles/Image_63.png':('B','波紋玻璃瓶的折射、紋理與透明液體難以分辨，不能確認 none；旁邊杯中的果汁不是瓶內殘留。'),
 'glass_beverage_bottles/Image_20.png':('W','再次看單張並核對完全重複圖：瓶底有 PET 五瓣結構，主體是塑膠飲料瓶商品組圖，與 glass 細類不符；保留資料夾及 waste_class 對照，不自動搬圖改類。'),
 'glass_beverage_bottles/Image_159.png':('W','與 Image_20 為完全相同像素的圖片；瓶底有 PET 五瓣結構，主體是塑膠瓶，與 glass 細類不符。紅色瓶身不能單靠顏色確認液體。'),
 'glass_beverage_bottles/Image_23.png':('W','畫面主體多為帶 PET 底部與瓶蓋結構的塑膠水瓶，混有不同材質商品，非清楚的玻璃飲料瓶細類樣本。'),
 'plastic_water_bottles/Image_44.png':('B','再次看單張：Aquafina 標籤遮住中段，透明瓶壁、肩部線條與清水難以分辨；不從品牌或商品照推定裝水，也不確認 none。'),
 'plastic_water_bottles/Image_158.png':('B','與 Image_44 完全相同像素，採一致判斷：標籤遮擋中段，清水與透明瓶壁難辨，殘留 unknown，不列無殘留生成來源。'),
 'plastic_water_bottles/Image_209.png':('B','同一 Aquafina 瓶構圖：標籤遮擋中段，肩部折線可能為結構／折射，無法清楚確認液體或 none。'),
 'plastic_water_bottles/Image_50.png':('B','再次看單張：手部遮住瓶身中段，壓扁透明瓶的反光與可能液滴難分；底部雖可見，仍不能確定全瓶無殘留，移出 eligible。'),
 'plastic_water_bottles/Image_205.png':('B','再次看單張：可見金屬底座與瓶蓋，瓶身材質及內底可見性仍需確認；不能直接視為清楚無殘留的 PET 水瓶來源。'),
 'plastic_water_bottles/Image_246.png':('B','再次看單張：低解析度且瓶身壓皺，亮點、刮痕與可能液滴無法區分；不能確認 none，不列 eligible。'),
 'paper_cups/Image_145.png':('B','可見上方內壁，但杯底被前壁遮住；只看到白色內壁不足以確認整杯 none，因此不列無殘留生成來源。'),
 'paper_cups/Image_189.png':('B','與 Image_145 為同構圖紙杯：上方內壁可見但杯底遮擋；不能確認 none，不列 eligible。'),
 'paper_cups/Image_192.png':('B','白色紙杯可見上方內壁，內底不在可判讀視野中；不能因白色乾淨外觀確認 none。'),
 'paper_cups/Image_200.png':('B','再次看單張：有紙製提把且杯口清楚，但深處底面與透印／反光無法確實分清；殘留留白，不以生成咖啡版本倒推原圖乾淨。'),
 'paper_cups/Image_217.png':('N','俯視多個紙杯，內底可見，未見殘留；多容器畫面不適合作為單一容器編輯來源。'),
 'paper_cups/Image_219.png':('N','俯視多個杯口及內底，未見殘留；保留 none，但多容器不列 eligible。'),
 'paper_cups/Image_230.png':('F','可見小紙容器內紅色濃稠醬料；屬醬料／食物內容，不以旁邊空杯推定 none。沒有可確認的薄層自由液體。'),
 'plastic_food_containers/Image_28.png':('Q','與其他水果／堅果內容一起出現的黃色容器有明顯液體內容；畫面食物與液體並存，修正原本 none。'),
 'plastic_food_containers/Image_94.png':('F','多個黑色餐盒內明顯裝有雞肉、蔬菜等完整餐食，修正原本 none；不作無殘留生成來源。'),
 'plastic_food_containers/Image_168.png':('E','再次看單張：透明刻度方盒內壁及底面可見，未見食物或液體；單一主體且底部殘留能從現有角度顯示，列 eligible。'),
 'plastic_food_containers/Image_182.png':('B','再次看單張：透明舊餐盒內底可見細點／痕跡，無法確實區分刮痕與細小食物；不確認 none，留 review。'),
 'styrofoam_food_containers/Image_7.png':('U','餐盒為閉蓋不透明狀態，無法看內底，修正原本 none／eligible；外觀乾淨不代表內部無殘留。'),
 'styrofoam_food_containers/Image_27.png':('Q','可見泡棉碗中湯汁與食物塊並存；mixed 留白，不再單標 food。'),
 'styrofoam_food_containers/Image_38.png':('Q','與 Image_27 同構圖：泡棉碗內可見湯汁及食物，mixed 留白。'),
 'styrofoam_food_containers/Image_76.png':('Q','使用過的分隔餐盒內同時可見食物碎屑／醬料與有反光的黃色積液，mixed 留白。'),
 'styrofoam_food_containers/Image_97.png':('Q','使用過的餐盒內可見食物痕跡、深色醬汁及積液，不能只標 food。'),
 'styrofoam_food_containers/Image_118.png':('Q','可見橘色食物／醬痕與分隔格中的黃色自由積液；mixed 留白，不硬標 food。'),
 'styrofoam_food_containers/Image_190.png':('F','再次看單張：打開的白盒內底有清楚橘色食物／醬料殘留，未見明顯積液；修正原本 none／eligible 為 food／exclude。'),
 'styrofoam_food_containers/Image_200.png':('W','透明薄壁有肋紋的掀蓋餐盒，可直接透視內部，非此細類的泡棉容器；排除並保留原資料夾，不自動搬移。'),
 'styrofoam_food_containers/Image_202.png':('R','再次看單張：可見空盒內底，未見殘留；外殼材質／細類仍有歧義，維持原本 generation_candidate=review，不直接提升 eligible。'),
}
obs=w.read_json(v.RUN/'observations.json',{})
for path,(code,reason) in updates.items():
    obs[path].pop('individual_image_viewed',None)
    obs[path].pop('individual_followup_at',None)
    obs[path].update(code=code,reason=reason,visual_detail_confirmed_at=w.now(),followup_basis='Viewed original pixels in contact sheet and/or individual image')
w.atomic_json(v.RUN/'observations.json',obs)
w.atomic_json(v.RUN/'individual_followups.json',updates)
w.atomic_json(v.RUN/'codes.json',v.CODES)
print('Individual followups:',len(updates),'Total review observations:',len(obs))
