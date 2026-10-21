"""ID-only local API. Knowing an ID permits reading/modifying its records."""
from contextlib import asynccontextmanager
import asyncio
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import warnings
from typing import Literal
from PIL import Image
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from .settings import Settings
from .schemas import UserIn, Annotation, UploadMeta, canonical, WASTE, RESIDUAL
from .store import Store, now, uid
from .service import Service

class BodyTooLarge(Exception):pass
class BodyLimit:
    def __init__(self,app,limit):self.app=app;self.limit=limit
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        size=0
        async def limited():
            nonlocal size
            message=await receive();size+=len(message.get('body',b''))
            if size>self.limit:raise BodyTooLarge()
            return message
        try:await self.app(scope,limited,send)
        except BodyTooLarge:await JSONResponse({'detail':'整批上傳超過大小限制'},413)(scope,receive,send)

def validate_user(value):
    try:return canonical(value)
    except ValueError as e:raise HTTPException(422,str(e))

def annotation_insert(c,image,a,source,user,previous=None):
    c.execute('INSERT INTO annotations(image_id,source,waste_label,residual_label,waste_confirmed,residual_confirmed,annotator_id,created_at,previous_id) VALUES(?,?,?,?,?,?,?,?,?)',
              (image,source,a.waste,a.residual,int(a.waste_confirmed),int(a.residual_confirmed),user,now(),previous))

def safe_csv(value):
    if value is None:return ''
    text=str(value)
    # Excel evaluates a leading formula even after whitespace/control prefixes.
    if text.lstrip(' \t\r\n').startswith(('=','+','-','@')) or text.startswith(('\t','\r','\n')):text="'"+text
    return text

def validate_image(data,settings):
    if not data:raise ValueError('檔案為空白')
    if len(data)>settings.max_file_bytes:raise ValueError('檔案超過大小限制')
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as im:
            fmt=im.format;w,h=im.size
            if fmt not in settings.formats:raise ValueError('僅支援 JPEG、PNG、WebP')
            if w*h>settings.max_pixels:raise ValueError('圖片像素超過限制')
            if getattr(im,'n_frames',1)!=1:raise ValueError('不接受動態或多頁圖片')
            im.verify()
        with Image.open(io.BytesIO(data)) as im:im.load()
    return fmt,w,h

def create_app(settings=None,predictor_factory=None):
    settings=settings or Settings();service=Service(settings,predictor_factory)
    @asynccontextmanager
    async def lifespan(app):
        temp=settings.path('database').parent/'request-temp'
        temp.mkdir(parents=True,exist_ok=True)
        prior_temp=tempfile.tempdir;tempfile.tempdir=str(temp)
        try:
            await run_in_threadpool(service.start)
            yield
        finally:
            await run_in_threadpool(service.close)
            tempfile.tempdir=prior_temp
    app=FastAPI(title='垃圾與殘留辨識（本機 ID-only）',description='ID 是紀錄識別碼，知道相同 ID 即可查看及修改紀錄；沒有身分驗證或私人帳戶保護。',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=settings.api_prefix+'/openapi.json')
    app.state.service=service;app.add_middleware(BodyLimit,limit=settings.max_body)
    prefix=settings.api_prefix

    def user_exists(c,user):
        row=c.execute('SELECT * FROM users WHERE id=?',(user,)).fetchone()
        if not row:raise HTTPException(404,'找不到此 ID')
        return row

    def owned_batch(c,batch,user):
        row=c.execute('SELECT * FROM batches WHERE id=? AND user_id=?',(batch,user)).fetchone()
        if not row:raise HTTPException(404,'找不到此批次')
        return row

    def owned_image(c,image,user):
        row=c.execute('SELECT images.* FROM images JOIN batches ON batches.id=images.batch_id WHERE images.id=? AND batches.user_id=?',(image,user)).fetchone()
        if not row:raise HTTPException(404,'找不到此圖片')
        return row

    @app.get(prefix+'/health')
    def health():
        return dict(status='ok',model_ready=service.ready,model_error=service.error,model_version=service.model_version,
                    model=service.model_metadata,identity_notice='ID 是紀錄識別碼，知道相同 ID 即可查看及修改其資料，並非安全登入。',
                    limits=dict(max_files=settings.max_files,max_file_bytes=settings.max_file_bytes,max_pixels=settings.max_pixels,formats=settings.formats))

    @app.get(prefix+'/users/{user_id}')
    def get_user(user_id:str):
        user=validate_user(user_id)
        with service.store.connect() as c:
            row=c.execute('SELECT * FROM users WHERE id=?',(user,)).fetchone()
            return dict(exists=bool(row),canonical_id=user,user=dict(row) if row else None)

    @app.post(prefix+'/users',status_code=201)
    def new_user(body:UserIn):
        try:
            with service.store.connect(True) as c:
                c.execute('INSERT INTO users VALUES(?,?,?)',(body.id,body.nickname,now()))
                return dict(c.execute('SELECT * FROM users WHERE id=?',(body.id,)).fetchone())
        except sqlite3.IntegrityError:raise HTTPException(409,'此 ID 已存在，請直接使用該 ID 查詢')

    def persist_upload(meta,files):
        # files: display name, bounded bytes. Nothing is written into dataset.
        signature=hashlib.sha256(json.dumps(dict(mode=meta.mode,annotations=[a.model_dump() for a in meta.annotations],files=[(n,hashlib.sha256(b).hexdigest()) for n,b in files]),sort_keys=True).encode()).hexdigest()
        written=[]
        try:
            with service.store.connect(True) as c:
                user_exists(c,meta.user_id)
                prior=c.execute('SELECT * FROM batches WHERE user_id=? AND request_key=?',(meta.user_id,meta.request_key)).fetchone()
                if prior:
                    if prior['request_hash']!=signature:raise HTTPException(409,'此送出識別碼已用於不同的圖片／標註')
                    return dict(batch_id=prior['id'],reused=True)
                batch=uid();stamp=now()
                c.execute('INSERT INTO batches VALUES(?,?,?,?,?,?,?,?)',(batch,meta.user_id,meta.mode,'queued',meta.request_key,signature,stamp,stamp))
                for i,(name,data) in enumerate(files):
                    image=uid();relative=None;fmt=None;width=None;height=None;error=None
                    try:
                        fmt,width,height=validate_image(data,settings)
                    except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning) as e:error=str(e)
                    if not error:
                        relative=image+{'JPEG':'.jpg','PNG':'.png','WEBP':'.webp'}[fmt]
                        path=service.file(relative)
                        with path.open('xb') as f:
                            written.append(path);f.write(data);f.flush();os.fsync(f.fileno())
                    status='failed' if error else 'queued'
                    c.execute('INSERT INTO images(id,batch_id,original_name,storage_path,sha256,format,width,height,status,error,created_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                              (image,batch,name,relative,hashlib.sha256(data).hexdigest() if len(data)<=settings.max_file_bytes else None,fmt,width,height,status,error,now(),now() if error else None))
                    if meta.mode=='evaluation':annotation_insert(c,image,meta.annotations[i],'pre_ground_truth',meta.user_id)
                Store.update_batch(c,batch)
            service.wake.set();return dict(batch_id=batch,reused=False)
        except BaseException:
            for path in written:path.unlink(missing_ok=True)
            raise

    @app.post(prefix+'/batches',status_code=201)
    async def upload(request:Request):
        if not service.ready:raise HTTPException(503,service.error or '模型載入中，請稍候')
        async with request.form(max_files=settings.max_files,max_fields=2,max_part_size=65536) as form:
            try:meta=UploadMeta.model_validate_json(form.get('metadata',''))
            except (ValidationError,TypeError):raise HTTPException(422,'ID、模式或人工標註格式錯誤')
            uploads=form.getlist('files')
            if not 1<=len(uploads)<=settings.max_files or not all(isinstance(f,UploadFile) for f in uploads):raise HTTPException(422,'圖片張數不符合限制')
            if meta.mode=='evaluation' and len(meta.annotations)!=len(uploads):raise HTTPException(422,'評估模式必須逐張提供標註（可各別尚未確認）')
            if meta.mode=='general' and meta.annotations:raise HTTPException(422,'一般模式不能提供預測前 Ground Truth')
            files=[]
            for f in uploads:
                data=await f.read(settings.max_file_bytes+1)
                name=re.sub(r'[\x00-\x1f\x7f]','',f.filename or '未命名圖片')[:200]
                files.append((name,data))
            return await run_in_threadpool(persist_upload,meta,files)

    @app.get(prefix+'/batches')
    def history(user_id:str,page:int=Query(1,ge=1),page_size:int=Query(10,ge=1,le=50)):
        user=validate_user(user_id)
        with service.store.connect() as c:
            user_exists(c,user)
            total=c.execute('SELECT count(*) FROM batches WHERE user_id=?',(user,)).fetchone()[0]
            rs=c.execute('SELECT b.*,count(i.id) AS image_count,sum(i.status=\'completed\') AS completed_count,sum(i.status=\'failed\') AS failed_count FROM batches b LEFT JOIN images i ON b.id=i.batch_id WHERE b.user_id=? GROUP BY b.id ORDER BY b.created_at DESC,b.id LIMIT ? OFFSET ?',(user,page_size,(page-1)*page_size)).fetchall()
            return dict(items=[dict(r) for r in rs],total=total,page=page,page_size=page_size)

    def detail(batch,user):
        with service.store.connect() as c:
            result=dict(owned_batch(c,batch,user));items=[]
            for row in c.execute('SELECT * FROM images WHERE batch_id=? ORDER BY created_at,id',(batch,)):
                item=dict(row);item.pop('storage_path')
                item['has_image']=bool(row['storage_path'])
                p=c.execute('SELECT * FROM predictions WHERE image_id=?',(row['id'],)).fetchone()
                item['prediction']=dict(p) if p else None
                if p:
                    for key in ('waste_probabilities','residual_probabilities'):item['prediction'][key]=json.loads(p[key])
                item['annotations']=[dict(a) for a in c.execute('SELECT * FROM annotations WHERE image_id=? ORDER BY id',(row['id'],))]
                items.append(item)
            result['images']=items;result['finished_count']=sum(r['status'] in ('completed','failed') for r in items)
            return result

    @app.get(prefix+'/batches/{batch_id}')
    def get_batch(batch_id:str,user_id:str):return detail(batch_id,validate_user(user_id))

    @app.post(prefix+'/images/{image_id}/annotations',status_code=201)
    def annotate(image_id:str,user_id:str,body:Annotation,response:Response,
                 source:Literal['post_feedback']='post_feedback'):
        user=validate_user(user_id)
        # BEGIN IMMEDIATE serializes the read/compare/append operation across all
        # SQLite connections. Compare only the latest snapshot, so A -> B -> A
        # remains a revision. Pre-prediction GT is never a writable API source.
        with service.store.connect(True) as c:
            row=owned_image(c,image_id,user)
            if row['status']!='completed':raise HTTPException(409,'只有完成辨識的圖片可提交結果後回饋')
            previous=c.execute('SELECT * FROM annotations WHERE image_id=? AND source=? ORDER BY id DESC LIMIT 1',(image_id,source)).fetchone()
            content=(body.waste,body.residual,int(body.waste_confirmed),int(body.residual_confirmed))
            if previous and content==tuple(previous[k] for k in ('waste_label','residual_label','waste_confirmed','residual_confirmed')):
                response.status_code=200
                return dict(previous,changed=False)
            annotation_insert(c,image_id,body,source,user,previous['id'] if previous else None)
            return dict(c.execute('SELECT * FROM annotations WHERE id=last_insert_rowid()').fetchone(),changed=True)

    @app.post(prefix+'/images/{image_id}/retry')
    def retry(image_id:str,user_id:str):
        if not service.ready:raise HTTPException(503,service.error or '模型未就緒')
        user=validate_user(user_id)
        with service.store.connect(True) as c:
            r=owned_image(c,image_id,user)
            if r['status']!='failed' or not r['storage_path'] or not service.file(r['storage_path']).exists():raise HTTPException(409,'此圖片不能重試，請重新上傳有效圖片')
            c.execute("UPDATE images SET status='queued',error=NULL,started_at=NULL,finished_at=NULL WHERE id=?",(image_id,));Store.update_batch(c,r['batch_id'])
        service.wake.set();return {'status':'queued'}

    @app.get(prefix+'/images/{image_id}/file')
    def image_file(image_id:str,user_id:str):
        with service.store.connect() as c:r=owned_image(c,image_id,validate_user(user_id))
        if not r['storage_path'] or not service.file(r['storage_path']).exists():raise HTTPException(404,'圖片不存在')
        return FileResponse(service.file(r['storage_path']),media_type={'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}[r['format']],headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})

    def remove(batch,image,user,confirmed):
        if not confirmed:raise HTTPException(400,'刪除前需明確確認 confirm=true')
        with service.store.connect(True) as c:
            owned_batch(c,batch,user)
            rows=c.execute('SELECT * FROM images WHERE batch_id=?'+(' AND id=?' if image else ''),(batch,image) if image else (batch,)).fetchall()
            if not rows:raise HTTPException(404,'找不到圖片')
            if any(r['status'] in ('queued','processing') for r in rows):raise HTTPException(409,'排隊或處理中不可刪除，請等待完成')
            for r in rows:
                if r['storage_path']:c.execute('INSERT OR IGNORE INTO file_gc VALUES(?,?)',(r['storage_path'],now()))
            if image:
                c.execute('DELETE FROM images WHERE id=?',(image,))
                if c.execute('SELECT count(*) FROM images WHERE batch_id=?',(batch,)).fetchone()[0]==0:c.execute('DELETE FROM batches WHERE id=?',(batch,))
                else:Store.update_batch(c,batch)
            else:c.execute('DELETE FROM batches WHERE id=?',(batch,))
        service.cleanup();return {'deleted':True}

    @app.delete(prefix+'/images/{image_id}')
    def delete_image(image_id:str,user_id:str,confirm:bool=False):
        user=validate_user(user_id)
        with service.store.connect() as c:r=owned_image(c,image_id,user)
        return remove(r['batch_id'],image_id,user,confirm)

    @app.delete(prefix+'/batches/{batch_id}')
    def delete_batch(batch_id:str,user_id:str,confirm:bool=False):return remove(batch_id,None,validate_user(user_id),confirm)

    def evaluation_data(user,batch=None):
        with service.store.connect() as c:
            user_exists(c,user)
            if batch:owned_batch(c,batch,user)
            images=[dict(r) for r in c.execute('SELECT i.*,b.mode,b.user_id,u.nickname,p.waste_label AS predicted_waste,p.residual_label AS predicted_residual,p.waste_confidence,p.residual_confidence,p.waste_low,p.residual_low,p.threshold,p.model_version,p.elapsed_ms FROM images i JOIN batches b ON b.id=i.batch_id JOIN users u ON u.id=b.user_id LEFT JOIN predictions p ON p.image_id=i.id WHERE b.user_id=?'+(' AND b.id=?' if batch else ''),(user,batch) if batch else (user,))]
            annotations={}
            for a in c.execute('SELECT a.* FROM annotations a JOIN images i ON a.image_id=i.id JOIN batches b ON b.id=i.batch_id WHERE b.user_id=? ORDER BY a.id',(user,)):
                annotations[(a['image_id'],a['source'])]=dict(a)
        return images,annotations

    @app.get(prefix+'/stats')
    def stats(user_id:str,source:str='pre_ground_truth',batch_id:str|None=None):
        if source not in ('pre_ground_truth','post_feedback'):raise HTTPException(422,'標註來源不正確')
        from training.metrics import classification_metrics
        images,annotations=evaluation_data(validate_user(user_id),batch_id);groups={}
        for r in images:
            if r['status']=='completed' and r['model_version']:groups.setdefault(r['model_version'],[]).append(r)
        results=[]
        for version,items in groups.items():
            tasks={}
            for task,classes in [('waste',list(WASTE)),('residual',list(RESIDUAL))]:
                true=[];pred=[]
                for item in items:
                    a=annotations.get((item['id'],source))
                    if a and a[task+'_confirmed'] and a[task+'_label'] in classes:
                        true.append(classes.index(a[task+'_label']));pred.append(classes.index(item['predicted_'+task]))
                tasks[task]=classification_metrics(true,pred,classes);tasks[task].pop('loss',None);tasks[task]['unannotated']=len(items)-len(true)
            results.append(dict(model_version=version,completed_images=len(items),tasks=tasks))
        return dict(source=source,versions=results,total_images=len(images),not_completed=sum(r['status']!='completed' for r in images),notice='信心不是正確率；預測後回饋不是獨立 Ground Truth。')

    @app.get(prefix+'/export.csv')
    def export(user_id:str,batch_id:str|None=None):
        images,annotations=evaluation_data(validate_user(user_id),batch_id)
        fields=['user_id','nickname','batch_id','mode','image_id','filename','image_sha256','status','error','created_at','finished_at','predicted_waste','predicted_residual','waste_confidence','residual_confidence','waste_low','residual_low','threshold','model_version','elapsed_ms','annotation_source','annotation_id','annotator_id','annotation_time','human_waste','human_residual','waste_confirmed','residual_confirmed','previous_annotation_id']
        output=io.StringIO(newline='');w=csv.DictWriter(output,fieldnames=fields);w.writeheader()
        with service.store.connect() as c:
            for image in images:
                # All revisions are exported. Pre GT is never overwritten by feedback.
                aa=c.execute('SELECT * FROM annotations WHERE image_id=? ORDER BY id',(image['id'],)).fetchall() or [None]
                for a in aa:
                    out={k:image.get(k) for k in fields}
                    out.update(image_id=image['id'],filename=image['original_name'],image_sha256=image['sha256'])
                    if a:out.update(annotation_source=a['source'],annotation_id=a['id'],annotator_id=a['annotator_id'],annotation_time=a['created_at'],human_waste=a['waste_label'],human_residual=a['residual_label'],waste_confirmed=a['waste_confirmed'],residual_confirmed=a['residual_confirmed'],previous_annotation_id=a['previous_id'])
                    w.writerow({k:safe_csv(v) for k,v in out.items()})
        return Response(output.getvalue().encode('utf-8-sig'),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="recognition-records.csv"','Cache-Control':'no-store'})

    @app.get('/{path:path}')
    def frontend(path:str):
        if '/'+path==prefix or ('/'+path).startswith(prefix+'/'):raise HTTPException(404,'API 不存在')
        target=(settings.dist/path).resolve()
        if not target.is_relative_to(settings.dist.resolve()):raise HTTPException(404)
        if target.is_file():return FileResponse(target)
        if (settings.dist/'index.html').exists():return FileResponse(settings.dist/'index.html',headers={'Cache-Control':'no-cache'})
        return JSONResponse({'detail':'前端尚未建置，請依 website/README.md 執行 npm run build'},503)
    return app

app=create_app()
