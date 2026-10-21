// Real-checkpoint browser integration. Requires the disposable server runner;
// never points this test at an existing user's database/browser profile.
import {chromium} from 'playwright-core'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

const website=path.resolve(import.meta.dirname,'..'),project=path.dirname(website)
const base=process.env.WASTE_UI_TEST_URL,scratch=process.env.WASTE_FEEDBACK_TEST_DIR
assert.ok(base&&scratch,'Run python -m website.verify_feedback instead')
const out=path.join(website,'verification','screenshots','feedback')
await fs.mkdir(out,{recursive:true})
process.env.TEMP=scratch;process.env.TMP=scratch
const context=await chromium.launchPersistentContext(path.join(scratch,'browser-profile'),{
 executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true,
 viewport:{width:1440,height:1050},locale:'zh-TW',downloadsPath:path.join(scratch,'downloads')
})
const page=await context.newPage(),errors=[],screenshots=[]
page.on('pageerror',e=>errors.push(String(e)))
let posts=0
page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/annotations?'))posts++})
const api=async route=>{
 const response=await page.request.get(base+'/api'+route)
 assert.equal(response.status(),200)
 return response.json()
}
const shot=async name=>{await page.screenshot({path:path.join(out,name),fullPage:true});screenshots.push(name)}
const saved=async card=>{
 const button=card.getByRole('button',{name:'已儲存',exact:true})
 await button.waitFor();assert.equal(await button.isDisabled(),true)
}
try{
 await page.goto(base,{waitUntil:'networkidle'})
 const id='fbtest'+Date.now().toString().slice(-10)
 await page.getByLabel('使用者 ID',{exact:true}).fill(id)
 await page.getByRole('button',{name:'使用這個 ID →'}).click()
 await page.getByLabel('這是新的 ID，請填暱稱').fill('人工回饋驗證（隔離）')
 await page.getByRole('button',{name:'建立 ID 並開始'}).click()
 await page.getByText('模型已就緒',{exact:true}).waitFor()
 await page.getByRole('button',{name:/實驗評估/}).click()
 await page.locator('input[type=file]').setInputFiles([
  path.join(project,'dataset/paper_cups/Image_30.png'),
  path.join(project,'dataset/styrofoam_food_containers/Image_255.png')])
 await page.locator('.upload-item').nth(0).locator('select').nth(0).selectOption('other_recycling')
 await page.locator('.upload-item').nth(0).locator('select').nth(1).selectOption('liquid')
 for(const checkbox of await page.locator('.upload-item').nth(0).locator('input[type=checkbox]').all())await checkbox.check()
 await page.getByRole('button',{name:/開始辨識/}).click()
 await page.locator('.result-card .predictions').nth(1).waitFor({timeout:90000})
 const batch=page.url().split('/batch/')[1],read=()=>api(`/batches/${batch}?user_id=${id}`)
 const initial=await read(),firstID=initial.images[0].id
 const first=page.locator('.result-card').nth(0),second=page.locator('.result-card').nth(1)
 assert.equal(await page.getByText('預測前答案（已鎖定）',{exact:true}).count(),2)
 assert.equal(await page.locator('.feedback').count(),0)
 assert.match(await second.locator('.pre-truth').textContent(),/未提供／未確認/)
 assert.equal(await first.locator('.pre-truth select').count(),0)
 await shot('01-locked-GT.png')
 await first.getByRole('button',{name:'新增修正回饋',exact:true}).click()
 assert.equal(await first.locator('.feedback select').nth(0).inputValue(),'')
 assert.equal(await first.locator('.feedback input:checked').count(),0)
 assert.equal((await read()).images[0].annotations.length,1) // opening is not saving
 await first.locator('.feedback select').nth(0).selectOption('other_recycling')
 await first.locator('.feedback select').nth(1).selectOption('food')
 for(const checkbox of await first.locator('.feedback input[type=checkbox]').all())await checkbox.check()
 const pattern='**/api/images/*/annotations?*'
 let release
 const gate=new Promise(resolve=>{release=resolve})
 let releaseRefresh
 const refreshGate=new Promise(resolve=>{releaseRefresh=resolve})
 const batchPattern=`**/api/batches/${batch}?*`
 await page.route(batchPattern,async route=>{
  const response=await route.fetch();await refreshGate;await route.fulfill({response})
 })
 await page.route(pattern,async route=>{await gate;await route.continue()})
 const countBefore=posts
 await first.getByRole('button',{name:'儲存人工回饋',exact:true}).evaluate(button=>{button.click();button.click()})
 await first.getByRole('button',{name:'儲存中…',exact:true}).waitFor()
 assert.equal(await first.locator('.feedback select').nth(0).isDisabled(),true)
 release();await saved(first);await page.unroute(pattern)
 assert.equal(posts-countBefore,1)
 let data=await read(),a=data.images[0].annotations.at(-1)
 const feedbackURL=base+`/api/images/${firstID}/annotations?user_id=${id}`
 const answer={waste:a.waste_label,residual:a.residual_label,waste_confirmed:!!a.waste_confirmed,residual_confirmed:!!a.residual_confirmed}
 for(let i=0;i<2;i++){
  const response=await page.request.post(feedbackURL,{data:answer}),noop=await response.json()
  assert.equal(response.status(),200);assert.equal(noop.changed,false)
  assert.equal(noop.id,a.id);assert.equal(noop.created_at,a.created_at)
 }
 await first.getByRole('button',{name:'已儲存',exact:true}).evaluate(button=>button.click())
 assert.equal(posts-countBefore,1)
 // Unsaved B -> A returns to disabled; a real A -> B -> A creates revisions.
 await first.locator('.feedback select').nth(1).selectOption('liquid')
 const refreshed=page.waitForResponse(r=>r.url().includes(`/batches/${batch}?`)&&r.request().method()==='GET')
 releaseRefresh();await refreshed;await page.unroute(batchPattern)
 await first.getByText('人工標註紀錄（2）',{exact:true}).waitFor()
 assert.equal(await first.locator('.feedback select').nth(1).inputValue(),'liquid')
 assert.equal(await first.getByRole('button',{name:'更新人工回饋',exact:true}).isEnabled(),true)
 await first.locator('.feedback select').nth(1).selectOption('food')
 await first.locator('.feedback input[type=checkbox]').nth(1).check();await saved(first)
 for(const label of ['liquid','food']){
  await first.locator('.feedback select').nth(1).selectOption(label)
  await first.locator('.feedback input[type=checkbox]').nth(1).check()
  await first.getByRole('button',{name:'更新人工回饋',exact:true}).click();await saved(first)
 }
 for(const confirmed of [false,true]){
  await first.locator('.feedback input[type=checkbox]').nth(0).setChecked(confirmed)
  await first.getByRole('button',{name:'更新人工回饋',exact:true}).click();await saved(first)
 }
 data=await read();assert.equal(data.images[0].annotations.length,6)
 assert.deepEqual(data.images[0].annotations[0],initial.images[0].annotations[0])
 assert.deepEqual(data.images[0].prediction,initial.images[0].prediction)
 await shot('02-saved-and-versions.png')
 await page.reload({waitUntil:'networkidle'})
 await first.getByRole('button',{name:'查看／修改回饋',exact:true}).waitFor()
 assert.equal(await page.locator('.feedback').count(),0)
 assert.match(await first.locator('.feedback-summary').textContent(),/食物殘留/)
 await first.getByRole('button',{name:'查看／修改回饋',exact:true}).click();await saved(first)
 assert.equal(await first.locator('.feedback select').nth(1).inputValue(),'food')
 await second.getByRole('button',{name:'新增修正回饋',exact:true}).click()
 await second.locator('.feedback select').nth(0).selectOption('glass')
 await second.locator('.feedback select').nth(1).selectOption('none')
 for(const checkbox of await second.locator('.feedback input[type=checkbox]').all())await checkbox.check()
 await second.getByRole('button',{name:'儲存人工回饋',exact:true}).click();await saved(second)
 data=await read()
 assert.deepEqual(data.images[1].annotations[0],initial.images[1].annotations[0])
 assert.equal(data.images[1].annotations[0].waste_label,null)
 // General mode remains directly editable; one simulated HTTP failure is retryable.
 await page.getByRole('button',{name:/新增辨識/}).click()
 await page.locator('input[type=file]').setInputFiles(path.join(project,'dataset/paper_cups/Image_30.png'))
 await page.getByRole('button',{name:/開始辨識/}).click()
 const general=page.locator('.result-card')
 await general.locator('.predictions').waitFor({timeout:90000})
 assert.equal(await general.locator('.pre-truth').count(),0)
 assert.equal(await general.locator('.feedback').count(),1)
 await general.locator('.feedback select').nth(0).selectOption('glass')
 await general.locator('.feedback select').nth(1).selectOption('liquid')
 for(const checkbox of await general.locator('.feedback input[type=checkbox]').all())await checkbox.check()
 await page.route(pattern,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'隔離測試：暫時無法儲存，請重試'})}))
 await general.getByRole('button',{name:'儲存人工回饋',exact:true}).click()
 await page.getByText('Error: 隔離測試：暫時無法儲存，請重試',{exact:true}).waitFor()
 assert.equal(await general.getByRole('button',{name:'儲存人工回饋',exact:true}).isEnabled(),true)
 assert.equal(await general.locator('.feedback select').nth(0).inputValue(),'glass')
 await shot('03-failure-retains-draft.png');await page.unroute(pattern)
 await general.getByRole('button',{name:'儲存人工回饋',exact:true}).click();await saved(general)
 await page.reload({waitUntil:'networkidle'});await saved(general)
 assert.equal(await general.locator('.feedback select').nth(1).inputValue(),'liquid')
 const gt=await api(`/stats?user_id=${id}&source=pre_ground_truth`)
 const post=await api(`/stats?user_id=${id}&source=post_feedback`)
 for(const task of ['waste','residual']){
  assert.equal(gt.versions[0].tasks[task].n,1)
  assert.equal(post.versions[0].tasks[task].n,3)
 }
 const csv=await page.request.get(base+`/api/export.csv?user_id=${id}`)
 const bytes=await csv.body();assert.equal(bytes.subarray(0,3).toString('hex'),'efbbbf')
 assert.match(bytes.toString('utf8'),/previous_annotation_id/)
 assert.match(bytes.toString('utf8'),/pre_ground_truth/);assert.match(bytes.toString('utf8'),/post_feedback/)
 await page.setViewportSize({width:390,height:844});await shot('04-mobile-general-saved.png')
 assert.deepEqual(errors,[])
 const result={passed:true,real_checkpoint:true,console_errors:errors,screenshots,test_id:id,
  evaluation_images:2,general_images:1,pre_GT_valid_per_task:1,feedback_valid_per_task:3,
  first_image_feedback_versions:5,ui_double_click_requests:1,
  tested:['evaluation GT read-only and unprovided states','feedback collapsed and opt-in','opening does not confirm or save',
   'saved button disabled','late refresh preserves new draft','unsaved edit then revert','A-B-A revisions','confirmation changes','double-click guard',
   'API duplicate changed=false with original timestamp','refresh restores values and collapsed state',
   'post-feedback never fills missing pre-GT','general direct feedback','HTTP failure retains draft and retries',
   'per-source per-image statistics','CSV source and history columns','mobile rendering']}
 await fs.writeFile(path.join(website,'verification/feedback_browser.json'),JSON.stringify(result,null,2))
 console.log(JSON.stringify(result,null,2))
}finally{await context.close()}
