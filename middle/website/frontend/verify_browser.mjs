// Isolated headless integration test. Existing user browser profiles are never used.
import {chromium} from 'playwright-core'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'
const root=path.resolve(import.meta.dirname,'..')
const project=path.dirname(root)
const out=path.join(root,'verification','screenshots')
const scratch=path.join(root,'.cache','browser')
await fs.mkdir(out,{recursive:true});await fs.mkdir(scratch,{recursive:true})
process.env.TEMP=scratch;process.env.TMP=scratch
const profile=await fs.mkdtemp(path.join(scratch,'profile-'))
const context=await chromium.launchPersistentContext(profile,{
 executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true,
 viewport:{width:1440,height:1000},locale:'zh-TW',downloadsPath:path.join(scratch,'downloads'),acceptDownloads:true
})
const page=await context.newPage();const errors=[]
page.on('pageerror',e=>errors.push(String(e)))
const base=process.env.WASTE_UI_TEST_URL||'http://127.0.0.1:8001'
const screenshots=[]
async function shot(name){await page.screenshot({path:path.join(out,name),fullPage:true});screenshots.push(name)}
try{
 await page.goto(base,{waitUntil:'networkidle'})
 await page.getByRole('heading',{name:'開始你的辨識紀錄'}).waitFor()
 await shot('01-entry.png')
 const id='uitest'+Date.now().toString().slice(-10)
 await page.getByLabel('使用者 ID',{exact:true}).fill(id)
 await page.getByRole('button',{name:'使用這個 ID →'}).click()
 await page.getByLabel('這是新的 ID，請填暱稱').fill('網站自動化測試（隔離）')
 await page.getByRole('button',{name:'建立 ID 並開始'}).click()
 await page.getByText('模型已就緒',{exact:true}).waitFor()
 await page.getByRole('heading',{name:'讓每件物品，找到下一站。'}).waitFor()
 await shot('02-upload.png')
 await page.getByRole('button',{name:/實驗評估/}).click()
 await page.locator('input[type=file]').setInputFiles([path.join(project,'dataset/paper_cups/Image_30.png'),path.join(project,'dataset/styrofoam_food_containers/Image_255.png')])
 const selects=page.locator('.upload-item select')
 assert.equal(await selects.count(),4)
 await selects.nth(0).selectOption('other_recycling');await selects.nth(1).selectOption('liquid')
 await selects.nth(2).selectOption('other_recycling');await selects.nth(3).selectOption('food')
 assert.equal(await page.locator('.score').count(),0)
 await shot('03-before-prediction.png')
 await page.getByRole('button',{name:/開始辨識/}).click()
 await page.locator('.result-card .predictions').nth(1).waitFor({timeout:60000})
 assert.equal(await page.locator('.result-card .predictions').count(),2)
 await shot('04-results.png')
 const first=page.locator('.result-card').first()
 await first.locator('.feedback select').nth(0).selectOption('other_recycling')
 await first.locator('.feedback select').nth(1).selectOption('food')
 await first.getByRole('button',{name:'儲存人工回饋'}).click()
 await first.getByText(/最近儲存/).waitFor()
 assert.match(await first.locator('.pre-truth').textContent(),/液體殘留/)
 await page.reload({waitUntil:'networkidle'})
 await page.locator('.result-card .predictions').nth(1).waitFor()
 assert.match(await page.locator('.result-card').first().locator('.pre-truth').textContent(),/液體殘留/)
 await page.getByRole('button',{name:/評估統計/}).click()
 await page.getByText('混淆矩陣',{exact:true}).first().waitFor()
 await shot('05-statistics.png')
 const response=await page.request.get(`${base}/api/stats?user_id=${id}`)
 const stats=await response.json()
 assert.equal(stats.versions.length,1);assert.equal(stats.versions[0].tasks.waste.n,2);assert.equal(stats.versions[0].tasks.residual.n,2)
 await page.getByLabel('人工答案來源').selectOption('post_feedback')
 const post=await (await page.request.get(`${base}/api/stats?user_id=${id}&source=post_feedback`)).json()
 assert.equal(post.versions[0].tasks.residual.n,1)
 const downloadEvent=page.waitForEvent('download')
 await page.getByRole('link',{name:'匯出含修改紀錄 CSV'}).click()
 const download=await downloadEvent;const csvPath=path.join(scratch,'browser-export.csv');await download.saveAs(csvPath)
 assert.equal((await fs.readFile(csvPath)).subarray(0,3).toString('hex'),'efbbbf')
 await page.getByRole('button',{name:/新增辨識/}).click()
 await page.locator('input[type=file]').setInputFiles([{name:'cup.png',mimeType:'image/png',buffer:await fs.readFile(path.join(project,'dataset/paper_cups/Image_30.png'))},{name:'broken.png',mimeType:'image/png',buffer:Buffer.from('not an image')}])
 await page.getByRole('button',{name:/開始辨識/}).click()
 await page.locator('.result-card .predictions').waitFor({timeout:60000})
 assert.equal(await page.locator('.result-card .tag.failed').count(),1)
 await shot('06-mixed-results.png')
 page.once('dialog',dialog=>dialog.accept())
 await page.locator('.result-card').filter({has:page.locator('.tag.failed')}).getByRole('button',{name:'刪除圖片'}).click()
 await page.locator('.result-card').nth(1).waitFor({state:'detached'})
 page.once('dialog',dialog=>dialog.accept())
 await page.getByRole('button',{name:'刪除整批',exact:true}).click()
 await page.getByRole('heading',{name:'歷史批次',exact:true}).waitFor()
 await page.reload({waitUntil:'networkidle'})
 await page.getByRole('button',{name:'查看明細 →'}).waitFor()
 await page.setViewportSize({width:390,height:844})
 await shot('07-mobile-history.png')
 assert.equal(errors.length,0,errors.join('\n'))
 const result={passed:true,url:base,test_id:id,real_checkpoint:true,screenshots,console_errors:errors,
 tested:['ID creation','multi-upload','pre-GT before prediction','real two-head prediction','feedback separation','refresh persistence','history','statistics sources','CSV download','mixed success/failure','single/batch deletion','mobile layout']}
 await fs.writeFile(path.join(root,'verification/browser.json'),JSON.stringify(result,null,2))
 console.log(JSON.stringify(result,null,2))
}finally{await context.close()}
