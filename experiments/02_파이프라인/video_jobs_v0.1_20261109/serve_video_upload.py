"""영상 업로드·파일 저장만 검증하는 로컬 API. 인식 작업은 아직 접수하지 않습니다."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.middleware.body_limit import RequestBodyLimitMiddleware

MIB=1024*1024

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(MIB),b''):h.update(block)
    return h.hexdigest()

class UploadError(Exception):
    def __init__(self,status,code,message):
        self.status,self.code,self.message=status,code,message
        super().__init__(message)

class VideoStore:
    def __init__(self,root,max_file_bytes=50*MIB,max_seconds=10,max_side=1920,max_frames=1000):
        self.root=Path(root).resolve();self.files=self.root/'files';self.scratch=self.root/'tmp'
        self.files.mkdir(parents=True,exist_ok=True);self.scratch.mkdir(exist_ok=True)
        self.db=self.root/'registry.sqlite3'
        self.max_file_bytes=max_file_bytes
        self.max_seconds,self.max_side,self.max_frames=max_seconds,max_side,max_frames
        self.slots=threading.BoundedSemaphore(2)
        with self.connect() as con:
            con.execute('CREATE TABLE IF NOT EXISTS videos (file_id TEXT PRIMARY KEY, record_json TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        con=sqlite3.connect(self.db,timeout=10)
        try:
            with con:yield con
        finally:con.close()

    def get(self,file_id):
        if not re.fullmatch(r'[a-f0-9-]{36}',file_id):raise UploadError(404,'VIDEO_NOT_FOUND','해당 파일 ID가 없습니다.')
        with self.connect() as con:
            row=con.execute('SELECT record_json FROM videos WHERE file_id=?',(file_id,)).fetchone()
        if row is None:raise UploadError(404,'VIDEO_NOT_FOUND','해당 파일 ID가 없습니다.')
        record=json.loads(row[0]);path=self.files/(file_id+'.mp4')
        if not path.is_file() or path.stat().st_size!=record['bytes'] or sha256(path)!=record['sha256']:
            raise UploadError(409,'STORED_FILE_CHANGED','저장된 파일이 없거나 변경되었습니다.')
        return record,path

    def store(self,stream,filename):
        if not filename or Path(filename.replace(chr(92),'/')).suffix.lower()!='.mp4':
            raise UploadError(415,'UNSUPPORTED_FILE_EXTENSION','이번 시제품은 MP4 확장자 파일만 받습니다.')
        if not self.slots.acquire(blocking=False):raise UploadError(429,'UPLOAD_BUSY','파일 검사 중입니다. 잠시 후 재시도하세요.')
        file_id=str(uuid.uuid4());temp=self.scratch/(file_id+'.tmp.mp4');target=self.files/(file_id+'.mp4')
        committed=False
        try:
            count=0;h=hashlib.sha256()
            with temp.open('xb') as out:
                while block:=stream.read(MIB):
                    count+=len(block)
                    if count>self.max_file_bytes:raise UploadError(413,'FILE_TOO_LARGE','영상 파일의 용량 제한을 초과했습니다.')
                    out.write(block);h.update(block)
            if not count:raise UploadError(422,'EMPTY_VIDEO','빈 파일은 받을 수 없습니다.')
            with temp.open('rb') as header_file:header=header_file.read(12)
            if len(header)<12 or header[4:8]!=b'ftyp':
                raise UploadError(422,'INVALID_VIDEO','MP4 파일 헤더를 확인할 수 없습니다.')
            command=[sys.executable,str(Path(__file__).with_name('probe_uploaded_video.py')),'--path',str(temp),
                     '--max-seconds',str(self.max_seconds),'--max-side',str(self.max_side),'--max-frames',str(self.max_frames)]
            try:
                probe=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
            except subprocess.TimeoutExpired:
                raise UploadError(422,'VIDEO_PROBE_TIMEOUT','영상 검사 시간이 초과되었습니다.')
            try:checked=json.loads(probe.stdout)
            except ValueError:
                raise UploadError(500,'VIDEO_PROBE_FAILED','영상 검사 프로그램이 실패했습니다. 서버 환경을 확인하세요.')
            if not checked.get('ok'):
                raise UploadError(422,checked.get('code','INVALID_VIDEO'),checked.get('message','영상 검사 실패'))
            if probe.returncode:raise UploadError(500,'VIDEO_PROBE_FAILED','영상 검사 프로그램이 비정상 종료됐습니다.')
            record={'schema_version':'video-upload-experiment-v1','file_id':file_id,'status':'stored',
                    'sha256':h.hexdigest(),'bytes':count,'video_info':checked['video_info'],
                    'created_at':datetime.now(timezone.utc).isoformat()}
            temp.rename(target)
            with self.connect() as con:
                con.execute('INSERT INTO videos VALUES (?,?)',(file_id,json.dumps(record,ensure_ascii=False,allow_nan=False)))
            committed=True
            return record
        finally:
            # 이 호출에서 생성한 UUID 임시 파일·미등록 파일만 정리합니다.
            temp.unlink(missing_ok=True)
            if not committed:target.unlink(missing_ok=True)
            self.slots.release()

def create_app(store):
    app=FastAPI(title='로컬 영상 업로드 검사 API',version='0.1.0',
        description='파일 저장 단계만 제공합니다. HTTP 201은 인식 완료가 아닙니다.')
    app.add_middleware(RequestBodyLimitMiddleware,max_body_size=store.max_file_bytes+64*1024)
    def translate(exc):return HTTPException(exc.status,detail={'code':exc.code,'message':exc.message})

    @app.get('/health')
    def health():
        return {'status':'ready','stage':'upload-only','job_submission_supported':False,
            'limits':{'max_file_bytes':store.max_file_bytes,'max_request_bytes':store.max_file_bytes+64*1024,
                      'max_seconds':store.max_seconds,'max_long_side':store.max_side,'max_frames':store.max_frames}}

    @app.post('/v1/videos',status_code=201,openapi_extra={'requestBody':{'required':True,'content':{
        'multipart/form-data':{'schema':{'type':'object','required':['video'],'properties':{'video':{'type':'string','format':'binary'}}}}}}})
    async def upload(request:Request):
        if request.headers.get('content-type','').split(';',1)[0].lower()!='multipart/form-data':
            raise HTTPException(415,detail={'code':'MULTIPART_REQUIRED','message':'multipart/form-data로 보내세요.'})
        async with request.form(max_files=1,max_fields=0,max_part_size=1024) as form:
            parts=form.multi_items()
            if len(parts)!=1 or parts[0][0]!='video' or not isinstance(parts[0][1],UploadFile):
                raise HTTPException(422,detail={'code':'VIDEO_FIELD_REQUIRED','message':'video 필드에 영상 파일 한 개를 보내세요.'})
            video=parts[0][1]
            try:return await run_in_threadpool(store.store,video.file,video.filename)
            except UploadError as exc:raise translate(exc) from exc

    @app.get('/v1/videos/{file_id}')
    def metadata(file_id:str):
        try:return store.get(file_id)[0]
        except UploadError as exc:raise translate(exc) from exc

    @app.get('/v1/videos/{file_id}/content')
    def content(file_id:str):
        try:
            _,path=store.get(file_id)
            return FileResponse(path,media_type='video/mp4',filename=file_id+'.mp4')
        except UploadError as exc:raise translate(exc) from exc
    return app

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8769)
    p.add_argument('--storage',type=Path,default=Path(__file__).resolve().parent/'storage')
    p.add_argument('--max-file-mib',type=int,default=50)
    p.add_argument('--max-seconds',type=float,default=10)
    p.add_argument('--max-side',type=int,default=1920)
    args=p.parse_args()
    if args.max_file_mib<=0 or args.max_seconds<=0 or args.max_side<=0:raise ValueError('제한 값은 양수여야 합니다.')
    store=VideoStore(args.storage,args.max_file_mib*MIB,args.max_seconds,args.max_side)
    import uvicorn
    print(f'영상 업로드 API: http://127.0.0.1:{args.port}',flush=True)
    print('저장 위치:',store.root,flush=True)
    print('파일 저장 전용입니다. 인식·Kafka 작업 접수 전 / 종료 Ctrl+C',flush=True)
    uvicorn.run(create_app(store),host='127.0.0.1',port=args.port,limit_concurrency=8,timeout_keep_alive=5)

if __name__=='__main__':main()
