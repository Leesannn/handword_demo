"""로컬 단일 API·단일 워커용 MongoDB Outbox + Kafka 처리 경로."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import uuid
from kafka import KafkaProducer, KafkaConsumer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from serve_job_api import APIError, validate_input, now, create_server
from serve_mongo_job_api import MongoJobService, storage_errors, create_server_handler

DATABASE='ksl_demo_kafka_jobs_v1'
PREFIX='ksl.recognition'
BROKER='127.0.0.1:19092'

def encode(value): return json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')

def topics(prefix):
    return {kind:f'{prefix}.{kind}.v1' for kind in ('requested','completed','failed')}

def init_topics(broker,prefix):
    admin=KafkaAdminClient(bootstrap_servers=broker,request_timeout_ms=10000)
    try:
        for topic in topics(prefix).values():
            try:
                admin.create_topics([NewTopic(topic,1,1,topic_configs={'retention.ms':'86400000'})])
            except TopicAlreadyExistsError: pass
    finally: admin.close()

class KafkaJobService(MongoJobService):
    """API는 추론하지 않고 작업·입력·발행 대기 기록을 한 문서로 저장합니다."""
    def __init__(self,client,predictor,database=DATABASE,prefix=PREFIX,broker=BROKER):
        self.client,self.predictor=client,predictor
        self.collection=client[database]['jobs']
        self.collection.create_index('client_request_id',unique=True,name='unique_client_request')
        self.collection.create_index('outbox.request.published')
        self.lock=threading.Lock(); self.closed=False
        self.prefix,self.broker=prefix,broker
        self.stop_event=threading.Event(); self.thread=None

    @storage_errors
    def submit(self,payload):
        if not isinstance(payload,dict): raise APIError(422,'INVALID_REQUEST','JSON 객체가 필요합니다.')
        key,value=payload.get('client_request_id'),payload.get('input')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',key):
            raise APIError(422,'INVALID_REQUEST','client_request_id 형식을 확인하세요.')
        try:
            validate_input(value)
            fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        except (ValueError,TypeError,OverflowError) as exc:
            raise APIError(422,'INVALID_FEATURE_INPUT',str(exc)) from exc
        with self.lock:
            old=self.collection.find_one({'client_request_id':key})
            if old: return self.previous(old,fingerprint)
            if self.closed: raise APIError(503,'SHUTTING_DOWN','서버 종료 중입니다.')
            if self.collection.count_documents({'status':{'$in':['queued','processing']}})>=256:
                raise APIError(503,'QUEUE_FULL','미완료 작업이 많습니다. 잠시 후 재시도하세요.')
            stamp=now()
            row={'_id':str(uuid.uuid4()),'client_request_id':key,'fingerprint':fingerprint,
                 'status':'queued','created_at':stamp,'updated_at':stamp,'result':None,'error_code':None,
                 'input':value,'model_sha256':self.predictor.model_hash,'attempts':0,
                 'outbox':{'request':{'event_id':str(uuid.uuid4()),'published':False}}}
            try: self.collection.insert_one(row)
            except DuplicateKeyError:
                old=self.collection.find_one({'client_request_id':key})
                if old: return self.previous(old,fingerprint)
                raise
            return self.public(row),False

    def start_publisher(self):
        self.thread=threading.Thread(target=self.publish_loop,name='outbox',daemon=True)
        self.thread.start()

    def publish_loop(self):
        producer=None
        try:
            while not self.stop_event.is_set():
                try:
                    if producer is None:
                        producer=KafkaProducer(bootstrap_servers=self.broker,acks='all',retries=3,
                            max_block_ms=5000,request_timeout_ms=10000,value_serializer=encode)
                    self.publish_once(producer)
                except Exception:
                    logging.warning('Outbox 발행 대기: MongoDB·Kafka 연결을 확인하세요. 기록은 삭제하지 않습니다.')
                    if producer is not None:
                        try: producer.close(timeout=1)
                        except Exception: pass
                        producer=None
                self.stop_event.wait(.5)
        finally:
            if producer is not None: producer.close(timeout=2)

    def publish_once(self,producer):
        for kind in ('request','result'):
            if self.stop_event.is_set(): return
            row=self.collection.find_one({f'outbox.{kind}.published':False})
            if row is None: continue
            outbox=row['outbox'][kind]
            event_type='requested' if kind=='request' else ('completed' if row['status']=='completed' else 'failed')
            event={'schema_version':'sign-recognition-event-v1','event_id':outbox['event_id'],
                   'event_type':event_type,'sequence_id':row['_id'],'model_sha256':row['model_sha256']}
            if kind=='result':
                event.update(status=row['status'],candidate=(row.get('result') or {}).get('candidate'),
                             error_code=row.get('error_code'))
            metadata=producer.send(topics(self.prefix)[event_type],key=row['_id'].encode(),value=event).get(timeout=15)
            # Kafka 확인 이후 표시합니다. 이 사이 종료되면 같은 event_id가 재발행될 수 있습니다.
            self.collection.update_one({'_id':row['_id'],f'outbox.{kind}.event_id':outbox['event_id']},
                {'$set':{f'outbox.{kind}.published':True,f'outbox.{kind}.published_at':now(),
                         f'outbox.{kind}.partition':metadata.partition,f'outbox.{kind}.offset':metadata.offset}})

    def close(self):
        with self.lock:self.closed=True
        self.stop_event.set()
        if self.thread:self.thread.join()
        self.client.close()

class RecognitionWorker:
    """단일 파티션·단일 워커 기준. 저장 성공 후 수동 커밋합니다."""
    def __init__(self,client,predictor,database=DATABASE,prefix=PREFIX,broker=BROKER):
        self.client,self.predictor=client,predictor
        self.collection=client[database]['jobs']
        self.rejected=client[database]['rejected_events']
        self.consumer=KafkaConsumer(topics(prefix)['requested'],bootstrap_servers=broker,
            group_id=prefix+'.worker.v1',enable_auto_commit=False,auto_offset_reset='earliest',
            max_poll_records=1,max_poll_interval_ms=300000,request_timeout_ms=30000)
        self.stop_event=threading.Event()

    def handle(self,message):
        try:
            event=json.loads(message.value)
            if not isinstance(event,dict) or event.get('schema_version')!='sign-recognition-event-v1' or event.get('event_type')!='requested':
                raise ValueError('이벤트 형식 불일치')
            job_id=event['sequence_id']
            row=self.collection.find_one({'_id':job_id})
            if row is None: raise ValueError('작업 문서 없음')
            if event.get('event_id')!=row['outbox']['request']['event_id']:
                raise ValueError('이벤트 ID 불일치')
        except (ValueError,KeyError,TypeError) as exc:
            # 잘못된 이벤트를 조용히 버리지 않고 해당 Kafka 위치를 유일 키로 기록합니다.
            key=f'{message.topic}:{message.partition}:{message.offset}'
            self.rejected.update_one({'_id':key},{'$setOnInsert':{'reason':str(exc),'created_at':now()}},upsert=True)
            return
        if row['status'] in ('completed','failed'):return
        token=str(uuid.uuid4())
        row=self.collection.find_one_and_update({'_id':job_id,'status':{'$in':['queued','processing']}},
            {'$set':{'status':'processing','updated_at':now(),'run_token':token,
                     'consumed':{'topic':message.topic,'partition':message.partition,'offset':message.offset}},
             '$inc':{'attempts':1}},return_document=ReturnDocument.AFTER)
        if row is None:return
        result=None; error=None
        try:
            if row['model_sha256']!=self.predictor.model_hash or event.get('model_sha256')!=self.predictor.model_hash:
                error='MODEL_VERSION_MISMATCH'
            else:result=self.predictor.predict(row['input'])
        except Exception:error='INFERENCE_FAILED'
        status='failed' if error else 'completed'
        changed=self.collection.update_one({'_id':job_id,'run_token':token,'status':'processing'},
            {'$set':{'status':status,'result':result,'error_code':error,'updated_at':now(),
                     'outbox.result':{'event_id':str(uuid.uuid4()),'published':False}}})
        if changed.matched_count!=1:raise RuntimeError('작업 소유권이 변경되어 커밋하지 않습니다.')
        print(f'처리 완료: {job_id} / {status}',flush=True)

    def run(self):
        try:
            while not self.stop_event.is_set():
                records=self.consumer.poll(timeout_ms=500,max_records=1)
                for batch in records.values():
                    for message in batch:
                        self.handle(message)
                        self.consumer.commit()
        except KeyboardInterrupt:pass
        finally:
            # DB·커밋 실패 시 프로세스를 종료해 재시작 시 미커밋 레코드를 재소비합니다.
            self.consumer.close(autocommit=False)
            self.client.close()

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('role',choices=['init','api','worker'])
    p.add_argument('--broker',default=BROKER)
    p.add_argument('--database',default=DATABASE)
    p.add_argument('--prefix',default=PREFIX)
    p.add_argument('--port',type=int,default=8768)
    args=p.parse_args()
    if not re.fullmatch(r'ksl_demo_[A-Za-z0-9_]{1,48}',args.database):raise ValueError('실습 DB 이름을 확인하세요.')
    if args.role=='init':
        init_topics(args.broker,args.prefix)
        print('토픽 3개 생성·확인 완료:',topics(args.prefix)); return
    from predict_feature_json import SignFeaturePredictor
    engine=SignFeaturePredictor(root/'model')
    client=MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),
                       serverSelectionTimeoutMS=5000,socketTimeoutMS=10000)
    if args.role=='worker':
        print('인식 워커 시작: 종료 Ctrl+C',flush=True)
        RecognitionWorker(client,engine,args.database,args.prefix,args.broker).run(); return
    server=create_server(None,args.port)
    service=KafkaJobService(client,engine,args.database,args.prefix,args.broker)
    server.RequestHandlerClass=create_server_handler(service)
    service.start_publisher()
    print(f'Kafka 작업 API: http://127.0.0.1:{args.port} / DB: {args.database}',flush=True)
    print('추론은 별도 워커에서 실행합니다. 종료 Ctrl+C',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();service.close()

if __name__=='__main__':main()
