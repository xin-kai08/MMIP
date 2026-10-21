// Uses the disposable server runner only; all model outputs are real.
import {chromium} from 'playwright-core'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
const website=path.resolve(import.meta.dirname,'..'),project=path.dirname(website)
const base=process.env.WASTE_UI_TEST_URL,scratch=process.env.WASTE_FEEDBACK_TEST_DIR
assert.ok(base&&scratch&&process.env.WASTE_TEST_TOKEN,'Use python -m website.verify_feedback --scenario linkage')
const out=path.join(website,'verification/screenshots/linkage');await fs.mkdir(out,{recursive:true})
process.env.TEMP=scratch;process.env.TMP=scratch
const context=await chromium.launchPersistentContext(path.join(scratch,'browser-profile'),{
 executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true,locale:'zh-TW',viewport:{width:1440,height:1000}
})
const page=await context.newPage(),errors=[],screenshots=[];page.on('pageerror',e=>errors.push(String(e)))
const shot=async name=>{await page.screenshot({path:path.join(out,name),fullPage:true});screenshots.push(name)}
const api=async route=>{const r=await page.request.get(base+'/api'+route);assert.equal(r.status(),200);return r.json()}
const confirm=async area=>{for(const c of await area.locator('input[type=checkbox]').all())await c.check()}
const saved=async area=>{const b=area.getByRole('button',{name:'已儲存',exact:true});await b.waitFor();assert.equal(await b.isDisabled(),true)}
async function switches(area){
 const waste=area.getByLabel('垃圾類別',{exact:true}),residual=area.getByLabel('殘留狀態',{exact:true})
 const rc=area.locator('input[type=checkbox]').nth(1)
 assert.equal(await residual.isDisabled(),true)
 assert.match(await area.textContent(),/請先選垃圾類別/)
 await waste.selectOption('general');assert.equal(await area.locator('select').count(),1)
 assert.equal(await area.getByRole('status').textContent(),'不適用');assert.equal(await rc.isChecked(),false)
 await rc.check();await waste.selectOption('glass')
 assert.equal(await residual.inputValue(),'');assert.equal(await rc.isChecked(),false)
 assert.equal(await residual.locator('option').count(),5)
 for(const value of ['none','food','liquid','not_assessable']){
  await residual.selectOption(value);assert.equal(await rc.isChecked(),false);await rc.check()
 }
 await waste.selectOption('food_waste');assert.equal(await area.locator('select').count(),1)
 assert.equal(await rc.isChecked(),false)
 await rc.check();await waste.selectOption('other_recycling')
 assert.equal(await residual.inputValue(),'');assert.equal(await rc.isChecked(),false)
 await residual.selectOption('food');await rc.check();await waste.selectOption('')
 assert.equal(await residual.isDisabled(),true);assert.equal(await residual.inputValue(),'');assert.equal(await rc.isChecked(),false)
}
try{
 await page.goto(base,{waitUntil:'networkidle'})
 const id='linktest'+Date.now().toString().slice(-9)
 await page.getByLabel('使用者 ID',{exact:true}).fill(id)
 await page.getByRole('button',{name:'使用這個 ID →'}).click()
 await page.getByLabel('這是新的 ID，請填暱稱').fill('殘留連動驗證（隔離）')
 await page.getByRole('button',{name:'建立 ID 並開始'}).click();await page.getByText('模型已就緒',{exact:true}).waitFor()
 await page.getByRole('button',{name:/實驗評估/}).click()
 await page.locator('input[type=file]').setInputFiles(path.join(project,'dataset/paper_cups/Image_30.png'))
 const upload=page.locator('.upload-item');await switches(upload)
 await upload.getByLabel('垃圾類別',{exact:true}).selectOption('general')
 await upload.locator('input[type=checkbox]').nth(0).check() // residue remains unconfirmed
 await shot('01-pre-GT-fixed-unconfirmed.png')
 await page.getByRole('button',{name:/開始辨識/}).click()
 let card=page.locator('.result-card');await card.locator('.predictions').waitFor({timeout:90000})
 const batch=page.url().split('/batch/')[1],read=()=>api(`/batches/${batch}?user_id=${id}`)
 let data=await read();const original=data.images[0],pre=original.annotations[0]
 assert.equal(pre.waste_label,'general');assert.equal(pre.residual_label,'not_assessable');assert.equal(pre.residual_confirmed,0)
 assert.equal(await card.locator('.pre-truth input,.pre-truth select').count(),0)
 await card.getByRole('button',{name:'新增修正回饋',exact:true}).click()
 const form=card.locator('.feedback');await switches(form)
 assert.deepEqual((await read()).images[0].annotations,original.annotations) // drafts never write
 await form.getByLabel('垃圾類別',{exact:true}).selectOption('food_waste')
 await confirm(form)
 await form.getByRole('button',{name:'儲存人工回饋',exact:true}).click();await saved(form)
 data=await read();const first=data.images[0].annotations.at(-1)
 assert.equal(first.residual_label,'not_assessable');assert.equal(first.residual_confirmed,1)
 assert.deepEqual(data.images[0].annotations[0],pre);assert.deepEqual(data.images[0].prediction,original.prediction)
 // Latest saved automatic value is not overwritten just by opening/reloading.
 await page.reload({waitUntil:'networkidle'});await card.getByRole('button',{name:'查看／修改回饋',exact:true}).click();await saved(form)
 const response=await page.request.post(base+`/api/images/${original.id}/annotations?user_id=${id}`,{
  data:{waste:'food_waste',residual:'not_assessable',waste_confirmed:true,residual_confirmed:true}})
 assert.equal((await response.json()).changed,false)
 // Seed one genuinely incompatible historical row in the disposable DB only.
 const seed=await page.request.post(base+'/__test__/legacy_feedback',{
  headers:{'X-Test-Token':process.env.WASTE_TEST_TOKEN},data:{image_id:original.id}})
 assert.equal(seed.status(),200)
 await page.reload({waitUntil:'networkidle'})
 await card.getByRole('button',{name:'查看／修改回饋',exact:true}).click()
 await form.locator('.legacy-warning').waitFor()
 const beforeCorrection=(await read()).images[0].annotations
 assert.equal(beforeCorrection.at(-1).residual_label,'food')
 assert.equal(await form.getByRole('button',{name:'已儲存',exact:true}).isDisabled(),true)
 await shot('02-legacy-read-only.png')
 await form.getByRole('button',{name:'套用不適用並重新確認',exact:true}).click()
 assert.equal(await form.locator('input[type=checkbox]').nth(1).isChecked(),false)
 assert.deepEqual((await read()).images[0].annotations,beforeCorrection)
 await form.getByRole('button',{name:'更新人工回饋',exact:true}).click();await saved(form)
 data=await read();assert.deepEqual(data.images[0].annotations.slice(0,-1),beforeCorrection)
 assert.equal(data.images[0].annotations.at(-1).residual_confirmed,0)
 assert.deepEqual(data.images[0].annotations[0],pre)
 // General recognition uses the exact same linked editor, independently of predictions.
 await page.getByRole('button',{name:/新增辨識/}).click()
 await page.locator('input[type=file]').setInputFiles(path.join(project,'dataset/paper_cups/Image_30.png'))
 await page.getByRole('button',{name:/開始辨識/}).click()
 card=page.locator('.result-card');await card.locator('.predictions').waitFor({timeout:90000})
 const general=card.locator('.feedback');await switches(general)
 await general.getByLabel('垃圾類別',{exact:true}).selectOption('glass')
 await general.getByLabel('殘留狀態',{exact:true}).selectOption('liquid')
 await confirm(general)
 await general.getByRole('button',{name:'儲存人工回饋',exact:true}).click();await saved(general)
 await page.setViewportSize({width:390,height:844});await shot('03-mobile-manual-options.png')
 assert.deepEqual(errors,[])
 const result={passed:true,real_checkpoint:true,console_errors:errors,screenshots,
  tested:['pre-GT editor linkage','general feedback linkage','post-prediction correction linkage',
   'no-waste disables residual','general and food_waste fixed NA','all four recycling residual options and blank',
   'category switches clear incompatible/automatic values','changed values reset confirmation','automatic NA never auto-confirms',
   'independent confirmation in pre-GT','drafts do not mutate DB','GT and model prediction unchanged',
   'no-op submission remains idempotent','reload restores saved answers','incompatible legacy shown read-only',
   'explicit legacy correction appends without altering history','mobile rendering'],
  fixture_note:'Legacy row is injected only by the disposable test server, never by production APIs.'}
 await fs.writeFile(path.join(website,'verification/linkage_browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))
}finally{await context.close()}
