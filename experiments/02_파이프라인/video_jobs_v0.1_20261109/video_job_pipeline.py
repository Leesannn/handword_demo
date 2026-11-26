"""로컬 단일 API·단일 워커용 영상 비동기 처리. 기존 특징 API와 별도 DB·토픽 사용."""
import argparse
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from kafka_job_pipeline import KafkaJobService, RecognitionWorker, init_topics, topics
from serve_job_api import APIError, now
from serve_mongo_job_api import storage_errors
from serve_video_upload import VideoStore, UploadError, create_app

VERSION='server-video-job-pipeline-v1'
DATABASE='ksl_demo_video_jobs_v1'
PREFIX='ksl.video.recognition'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

class ProcessingError(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)

class VideoPredictor:
    def __init__(self,pipeline,store,results,load_engine=False):
        self.pipeline=Path(pipeline).resolve();self.store=store;self.results=Path(results)
        if not (self.pipeline/'video_feature_pipeline.py').is_file():raise ValueError('영상 처리 모듈 경로를 확인하세요.')
        # API와 워커가 같은 코드·모델·추출 모델을 사용해야 합니다.
        files=sorted([p for p in self.pipeline.glob('*.py')]+[p for folder in ('model','models')
            for p in (self.pipeline/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts])
        hashes={p.relative_to(self.pipeline).as_posix():digest(p) for p in files}
        self.pipeline_hash=hashlib.sha256(json.dumps({'version':VERSION,'files':hashes},sort_keys=True).encode()).hexdigest()
        sys.path.insert(0,str(self.pipeline))
        from predict_feature_json import SignFeaturePredictor
        predictor=SignFeaturePredictor(self.pipeline/'model')
        self.model_hash=predictor.model_hash
        self.engine=None
        if load_engine:
            from video_feature_pipeline import VideoFeaturePipeline
            self.engine=VideoFeaturePipeline(self.pipeline/'model',self.pipeline/'models')

    def predict(self,value):
        if value.get('pipeline_sha256')!=self.pipeline_hash:raise ProcessingError('PIPELINE_VERSION_MISMATCH')
        try:record,path=self.store.get(value['file_id'])
        except UploadError as exc:raise ProcessingError(exc.code) from exc
        if record['sha256']!=value['video_sha256']:raise ProcessingError('VIDEO_HASH_MISMATCH')
        output=self.results/(now().replace(':','').replace('+','_')+'_'+uuid.uuid4().hex)
        try:
            report=self.engine.process(path,output,value['frame_interval']['start'],value['frame_interval']['end'])
            result=json.loads((output/'response.json').read_text(encoding='utf-8'))
        except Exception as exc:raise ProcessingError('VIDEO_PROCESSING_FAILED') from exc
        # 결과를 앱에 전달할 때 서버 내부 경로를 노출하지 않습니다.
        result['video_processing']={'file_id':value['file_id'],'video_sha256':record['sha256'],
            'frame_interval':value['frame_interval'],'pipeline_version':VERSION,'pipeline_sha256':self.pipeline_hash,
            'selected_source_frames_1based':report['selected_source_frames_1based'],
            'base_shape':report['base_shape'],'model_shape':report['model_shape']}
        return result

class VideoJobService(KafkaJobService):
    @storage_errors
    def submit(self,payload):
        if not isinstance(payload,dict) or set(payload)-{'client_request_id','file_id','frame_interval'}:
            raise APIError(422,'INVALID_REQUEST','허용한 요청 필드를 확인하세요.')
        key=payload.get('client_request_id')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',key):
            raise APIError(422,'INVALID_REQUEST','요청 키는 영문·숫자·밑줄·하이픈 1~80자입니다.')
        file_id=payload.get('file_id')
        if not isinstance(file_id,str):raise APIError(422,'INVALID_FILE_ID','file_id 문자열이 필요합니다.')
        try:record,_=self.predictor.store.get(file_id)
        except UploadError as exc:raise APIError(exc.status,exc.code,exc.message) from exc
        interval=payload.get('frame_interval',{'start':1,'end':record['video_info']['frames']})
        if (not isinstance(interval,dict) or set(interval)!={'start','end'}
            or any(type(interval[k]) is not int for k in ('start','end'))
            or not 1<=interval['start']<=interval['end']<=record['video_info']['frames']):
            raise APIError(422,'INVALID_FRAME_INTERVAL','구간은 1부터 시작하며 끝 번호를 포함해야 합니다.')
        value={'file_id':file_id,'video_sha256':record['sha256'],'frame_interval':interval,
            'pipeline_version':VERSION,'pipeline_sha256':self.predictor.pipeline_hash}
        fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.lock:
            old=self.collection.find_one({'client_request_id':key})
            if old:return self.previous(old,fingerprint)
            if self.closed:raise APIError(503,'SHUTTING_DOWN','서버 종료 중입니다.')
            if self.collection.count_documents({'status':{'$in':['queued','processing']}})>=256:
                raise APIError(503,'QUEUE_FULL','미완료 작업이 많습니다.')
            stamp=now()
            row={'_id':str(uuid.uuid4()),'client_request_id':key,'fingerprint':fingerprint,'input':value,
                'status':'queued','created_at':stamp,'updated_at':stamp,'result':None,'error_code':None,
                'model_sha256':self.predictor.model_hash,'attempts':0,
                'outbox':{'request':{'event_id':str(uuid.uuid4()),'published':False}}}
            try:self.collection.insert_one(row)
            except DuplicateKeyError:
                old=self.collection.find_one({'client_request_id':key})
                if old:return self.previous(old,fingerprint)
                raise
            return self.public(row),False

class VideoWorker(RecognitionWorker):
    def handle(self,message):
        try:
            event=json.loads(message.value)
            if not isinstance(event,dict) or event.get('schema_version')!='sign-recognition-event-v1' or event.get('event_type')!='requested':
                raise ValueError('이벤트 형식 불일치')
            row=self.collection.find_one({'_id':event['sequence_id']})
            if row is None or event.get('event_id')!=row['outbox']['request']['event_id']:raise ValueError('작업·이벤트 ID 불일치')
        except (ValueError,KeyError,TypeError) as exc:
            self.rejected.update_one({'_id':f'{message.topic}:{message.partition}:{message.offset}'},
                {'$setOnInsert':{'reason':str(exc),'created_at':now()}},upsert=True)
            return
        if row['status'] in ('completed','failed'):return
        token=str(uuid.uuid4())
        row=self.collection.find_one_and_update({'_id':row['_id'],'status':{'$in':['queued','processing']}},
            {'$set':{'status':'processing','updated_at':now(),'run_token':token,
                'consumed':{'topic':message.topic,'partition':message.partition,'offset':message.offset}},
                '$inc':{'attempts':1}},return_document=ReturnDocument.AFTER)
        if row is None:return
        result=None;error=None
        try:
            if row['model_sha256']!=self.predictor.model_hash or event.get('model_sha256')!=self.predictor.model_hash:
                raise ProcessingError('MODEL_VERSION_MISMATCH')
            result=self.predictor.predict(row['input'])
        except ProcessingError as exc:error=exc.code
        except Exception:error='VIDEO_PROCESSING_FAILED'
        changed=self.collection.update_one({'_id':row['_id'],'run_token':token,'status':'processing'},
            {'$set':{'status':'failed' if error else 'completed','result':result,'error_code':error,
                'updated_at':now(),'outbox.result':{'event_id':str(uuid.uuid4()),'published':False}}})
        if changed.matched_count!=1:raise RuntimeError('작업 소유권이 변경되어 커밋하지 않습니다.')
        print('영상 작업 완료:',row['_id'],'/',error or 'completed',flush=True)

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('role',choices=['init','api','worker'])
    p.add_argument('--port',type=int,default=8770)
    p.add_argument('--broker',default='127.0.0.1:19092')
    p.add_argument('--database',default=DATABASE)
    p.add_argument('--prefix',default=PREFIX)
    p.add_argument('--storage',type=Path,default=root.parent/'video_upload_v0.1_20261109/storage')
    p.add_argument('--pipeline-dir',type=Path,default=root.parent/'video_pipeline_v0.1_20261109')
    p.add_argument('--results',type=Path,default=root/'processing_results')
    args=p.parse_args()
    if not re.fullmatch(r'ksl_demo_[A-Za-z0-9_]{1,48}',args.database):raise ValueError('실습 DB 이름을 확인하세요.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',args.prefix):raise ValueError('토픽 접두사를 확인하세요.')
    if args.role=='init':init_topics(args.broker,args.prefix);print('영상 토픽 준비:',topics(args.prefix));return
    store=VideoStore(args.storage)
    engine=VideoPredictor(args.pipeline_dir,store,args.results,load_engine=args.role=='worker')
    client=MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000,socketTimeoutMS=10000)
    client.admin.command('ping')
    if args.role=='worker':
        print('영상 워커 실행 / 단일 워커 전용 / 종료 Ctrl+C',flush=True)
        VideoWorker(client,engine,args.database,args.prefix,args.broker).run();return
    service=VideoJobService(client,engine,args.database,args.prefix,args.broker)
    app=create_app(store)
    @asynccontextmanager
    async def lifespan(app):
        service.start_publisher()
        try:yield
        finally:await run_in_threadpool(service.close)
    app.router.lifespan_context=lifespan
    @app.post('/v1/video-jobs',status_code=202)
    async def submit(request:Request):
        try:payload=await request.json()
        except ValueError:raise HTTPException(422,detail={'code':'INVALID_JSON'})
        try:
            row,reused=await run_in_threadpool(service.submit,payload)
            row['reused']=reused
            return JSONResponse(row,status_code=200 if reused else 202)
        except APIError as exc:raise HTTPException(exc.status,detail={'code':exc.code,'message':exc.message}) from exc
    @app.get('/v1/video-jobs/{sequence_id}')
    def get(sequence_id:str):
        try:return service.get(sequence_id)
        except APIError as exc:raise HTTPException(exc.status,detail={'code':exc.code,'message':exc.message}) from exc
    @app.get('/job-health')
    def job_health():
        try:service.check_storage()
        except APIError as exc:raise HTTPException(exc.status,detail={'code':exc.code}) from exc
        return {'status':'ready','stage':'video-jobs','database':args.database,'topics':topics(args.prefix),
            'pipeline_sha256':engine.pipeline_hash,'model_sha256':engine.model_hash,
            'note': 'MongoDB 연결 확인. 워커·Kafka 처리 성공은 통합 검사로 확인합니다.'}
    import uvicorn
    print('영상 작업 API:',f'http://127.0.0.1:{args.port}','/ 저장소:',store.root,flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port,limit_concurrency=8)

if __name__=='__main__':main()
