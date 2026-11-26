"""MongoDB에 작업과 결과를 저장하는 로컬 단일 인스턴스 시제품."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import uuid
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError
from serve_job_api import JobService, APIError, validate_input, now, create_server

DATABASE='ksl_demo_jobs_v1'
COLLECTION='jobs'

def storage_errors(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PyMongoError as exc:
            # URI나 인증 정보를 HTTP 응답·로그에 노출하지 않습니다.
            raise APIError(503, 'STORAGE_UNAVAILABLE', 'MongoDB 연결 또는 저장 권한을 확인하세요.') from exc
    return wrapped

class MongoJobService(JobService):
    storage_name='mongodb'

    def __init__(self, client, predictor, database=DATABASE, collection=COLLECTION,
                 validator=validate_input, capacity=8):
        self.client=client
        self.collection=client[database][collection]
        self.predictor, self.validator=predictor, validator
        self.lock=threading.Lock()
        self.slots=threading.BoundedSemaphore(capacity)
        self.closed=False
        client.admin.command('ping')
        # _id에 작업 ID를 사용하고 재전송 키도 DB에서 유일하게 강제합니다.
        self.collection.create_index('client_request_id', unique=True, name='unique_client_request')
        self.collection.update_many({'status':{'$in':['queued','processing']}},
            {'$set':{'status':'failed','error_code':'SERVER_RESTARTED','updated_at':now()}})
        self.executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix='mongo-inference')

    @storage_errors
    def check_storage(self):
        self.client.admin.command('ping')

    @staticmethod
    def public(row):
        return {'schema_version':'sign-job-v1','sequence_id':row['_id'],
                'client_request_id':row['client_request_id'],'status':row['status'],
                'created_at':row['created_at'],'updated_at':row['updated_at'],
                'result':row.get('result'),
                'error':{'code':row['error_code']} if row.get('error_code') else None}

    @storage_errors
    def get(self, sequence_id):
        row=self.collection.find_one({'_id':sequence_id})
        if row is None: raise APIError(404,'JOB_NOT_FOUND','해당 작업이 없습니다.')
        return self.public(row)

    def previous(self, row, fingerprint):
        if row['fingerprint']!=fingerprint:
            raise APIError(409,'IDEMPOTENCY_CONFLICT','같은 요청 키에 다른 입력을 사용할 수 없습니다.')
        return self.public(row),True

    @storage_errors
    def submit(self, payload):
        if not isinstance(payload,dict): raise APIError(422,'INVALID_REQUEST','JSON 객체가 필요합니다.')
        key,value=payload.get('client_request_id'),payload.get('input')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',key):
            raise APIError(422,'INVALID_REQUEST','client_request_id는 영문·숫자·밑줄·하이픈 1~80자입니다.')
        try:
            self.validator(value)
            fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        except (ValueError,TypeError,OverflowError) as exc:
            raise APIError(422,'INVALID_FEATURE_INPUT',str(exc)) from exc
        with self.lock:
            old=self.collection.find_one({'client_request_id':key})
            if old: return self.previous(old,fingerprint)
            if self.closed or not self.slots.acquire(blocking=False):
                raise APIError(503,'QUEUE_FULL','대기열이 가득 찼습니다. 같은 요청으로 잠시 후 재시도하세요.')
            stamp=now()
            row={'_id':str(uuid.uuid4()),'client_request_id':key,'fingerprint':fingerprint,
                 'status':'queued','created_at':stamp,'updated_at':stamp,
                 'result':None,'error_code':None}
            try:
                self.collection.insert_one(row)
            except DuplicateKeyError:
                self.slots.release()
                old=self.collection.find_one({'client_request_id':key})
                if old: return self.previous(old,fingerprint)
                raise
            except Exception:
                self.slots.release()
                raise
            accepted=self.public(row)
            try:
                self.executor.submit(self.run,row['_id'],value)
            except Exception:
                try: self.update(row['_id'],'failed',error='SCHEDULING_FAILED')
                finally: self.slots.release()
                raise APIError(503,'SCHEDULING_FAILED','작업 실행 예약에 실패했습니다.')
            return accepted,False

    @storage_errors
    def update(self, job_id, status, result=None, error=None):
        # 기존 추론 결과는 JSON으로 직렬화 가능한지 먼저 검사합니다.
        if result is not None: json.dumps(result,allow_nan=False)
        changed=self.collection.update_one({'_id':job_id},
            {'$set':{'status':status,'updated_at':now(),'result':result,'error_code':error}})
        if changed.matched_count!=1: raise RuntimeError('작업 문서를 찾을 수 없습니다.')

    def run(self, job_id, value):
        try:
            self.update(job_id,'processing')
            result=self.predictor.predict(value)
            self.update(job_id,'completed',result=result)
        except Exception as exc:
            code='STORAGE_UNAVAILABLE' if isinstance(exc,APIError) else 'INFERENCE_FAILED'
            try: self.update(job_id,'failed',error=code)
            except Exception:
                logging.error('결과 저장 실패: sequence_id=%s. DB 복구 후 서버 재시작·작업 상태 확인 필요.',job_id)
        finally:
            self.slots.release()

    def close(self):
        super().close()
        self.client.close()

def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--model-dir',type=Path,default=root/'model')
    parser.add_argument('--database',default=DATABASE)
    args=parser.parse_args()
    if not re.fullmatch(r'ksl_demo_[A-Za-z0-9_]{1,48}',args.database):
        raise ValueError('별도 실습 DB 이름은 ksl_demo_로 시작해야 합니다.')
    from predict_feature_json import SignFeaturePredictor
    engine=SignFeaturePredictor(args.model_dir)
    client=MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),
                       serverSelectionTimeoutMS=5000,connectTimeoutMS=5000,socketTimeoutMS=10000)
    # 포트를 먼저 확보해 같은 포트로 중복 실행 시 기존 작업을 변경하지 않습니다.
    server=create_server(None,args.port)
    try:
        service=MongoJobService(client,engine,database=args.database)
    except PyMongoError:
        server.server_close(); client.close()
        raise SystemExit('MongoDB 접속·읽기·쓰기·인덱스 생성 권한을 확인하세요. 인증 URI는 화면에 출력하지 않습니다.')
    # 실제 서비스가 캡처된 핸들러를 사용합니다.
    server.RequestHandlerClass=create_server_handler(service)
    print(f'MongoDB 비동기 API: http://127.0.0.1:{args.port}',flush=True)
    print(f'저장 위치: {args.database}.{COLLECTION}',flush=True)
    print('단일 인스턴스 전용. 이 창 유지 / 종료 Ctrl+C / Kafka·AWS 연결 전',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close(); service.close()

def create_server_handler(service):
    probe=create_server(service,0)
    try: return probe.RequestHandlerClass
    finally: probe.server_close()

if __name__=='__main__':main()
