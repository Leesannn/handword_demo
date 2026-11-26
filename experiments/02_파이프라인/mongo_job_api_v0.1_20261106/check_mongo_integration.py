"""실제 MongoDB와 HTTP 서버로 검사. 에이전트 검증용 별도 DB 사용."""
import json
from pathlib import Path
import sys
import threading
import time
import uuid
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from predict_feature_json import SignFeaturePredictor
from serve_mongo_job_api import MongoJobService
from serve_job_api import create_server, APIError, now
from check_job_service import ControlledPredictor, expect, wait_terminal
import test_mongo_job_api

def main():
    root=Path(__file__).resolve().parent
    database='ksl_demo_agent_'+uuid.uuid4().hex[:12]
    client=MongoClient('mongodb://127.0.0.1:27017/',serverSelectionTimeoutMS=5000)
    engine=SignFeaturePredictor(root/'model')
    service=MongoJobService(client,engine,database=database)
    server=create_server(service,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    args=sys.argv
    try:
        sys.argv=['test_mongo_job_api.py','--port',str(server.server_port),'--database',database]
        test_mongo_job_api.main()
    finally:
        sys.argv=args; server.shutdown(); server.server_close(); service.close(); thread.join()
    # 서버·클라이언트를 새로 생성해 같은 디스크 저장 결과를 읽습니다.
    client=MongoClient('mongodb://127.0.0.1:27017/',serverSelectionTimeoutMS=5000)
    service=MongoJobService(client,engine,database=database)
    server=create_server(service,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        sys.argv=['test_mongo_job_api.py','--port',str(server.server_port),'--database',database,'--inspect-latest']
        test_mongo_job_api.main()
    finally:
        sys.argv=args; server.shutdown(); server.server_close(); service.close(); thread.join()
    client=MongoClient('mongodb://127.0.0.1:27017/',serverSelectionTimeoutMS=5000)
    controlled=ControlledPredictor()
    service=MongoJobService(client,controlled,database=database,collection='failure_checks',validator=lambda x:None,capacity=1)
    checks=[]
    try:
        accepted,_=service.submit({'client_request_id':'one','input':{}})
        assert controlled.entered.wait(2)
        assert service.get(accepted['sequence_id'])['status']=='processing'
        checks.append('추론 완료 전 접수·상태 조회')
        expect(503,lambda:service.submit({'client_request_id':'two','input':{}}))
        checks.append('대기열 제한')
        try:
            service.collection.insert_one({'_id':'unique-check','client_request_id':'one'})
        except DuplicateKeyError: checks.append('실제 MongoDB 유일 인덱스 중복 거부')
        else: raise AssertionError('중복 입력을 허용했습니다.')
        controlled.release.set()
        assert wait_terminal(service,accepted['sequence_id'])['status']=='completed'
        failed,_=service.submit({'client_request_id':'fail','input':{'fail':True}})
        assert wait_terminal(service,failed['sequence_id'])['error']['code']=='INFERENCE_FAILED'
        checks.append('실패 상태 저장')
        service.collection.insert_one({'_id':'interrupted','client_request_id':'interrupted',
                                      'status':'processing','created_at':now(),'updated_at':now()})
    finally:
        controlled.release.set(); service.close()
    client=MongoClient('mongodb://127.0.0.1:27017/',serverSelectionTimeoutMS=5000)
    recovered=MongoJobService(client,controlled,database=database,collection='failure_checks',validator=lambda x:None)
    try:
        assert recovered.get('interrupted')['error']['code']=='SERVER_RESTARTED'
        checks.append('중단 작업 재시작 실패 처리')
    finally: recovered.close()
    evidence={'database':database,'actual_mongodb':True,'checks':checks,
              'scope':'별도 에이전트 실습 DB에서 검사. 사용자 기본 실습 DB와 기존 데이터는 변경하지 않음.'}
    (root/'results/integration_agent.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    for item in checks: print('[PASS]',item)

if __name__=='__main__':main()
