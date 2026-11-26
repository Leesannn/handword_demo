"""HTTP 검사와 MongoDB 문서의 일치를 확인합니다."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from pymongo import MongoClient
import test_job_api
from serve_mongo_job_api import DATABASE, COLLECTION

def main():
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--database',default=DATABASE)
    parser.add_argument('--inspect-latest',action='store_true',help='새 작업을 만들지 않고 마지막 검사 결과 조회')
    args=parser.parse_args()
    base=f'http://127.0.0.1:{args.port}'
    status,health=test_job_api.call(base,'/health')
    assert status==200 and health['storage']=='mongodb','MongoDB API에 연결했는지 확인하세요.'
    if not args.inspect_latest:
        saved=sys.argv
        try:
            sys.argv=[saved[0],'--port',str(args.port)]
            test_job_api.main()
        finally: sys.argv=saved
    paths=list((root/'results').glob('*/job_api_check.json'))
    if not paths: raise FileNotFoundError('먼저 일반 검사를 실행하세요.')
    latest=max(paths,key=lambda p:p.stat().st_mtime)
    record=json.loads(latest.read_text(encoding='utf-8'))
    job_id=record['completed']['sequence_id']
    status,current=test_job_api.call(base,'/jobs/'+job_id)
    assert status==200 and current['status']=='completed'
    with MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000) as client:
        col=client[args.database][COLLECTION]
        doc=col.find_one({'_id':job_id})
        assert doc is not None and doc['status']=='completed'
        assert doc['result']==current['result']==record['completed']['result']
        assert col.count_documents({'client_request_id':doc['client_request_id']})==1
        assert col.index_information()['unique_client_request']['unique'] is True
    print('[PASS] MongoDB 문서와 API 결과 일치')
    print('[PASS] 요청 키 유일 인덱스·문서 1개 확인')
    evidence={'database':args.database,'collection':COLLECTION,'sequence_id':job_id,
              'status':current['status'],'candidate':current['result']['candidate'],
              'mongodb_matches_api':True,'unique_index_checked':True,
              'mode':'기존 작업 재조회' if args.inspect_latest else '새 HTTP 검사 후 저장 검증',
              'checked_at':datetime.now(timezone.utc).isoformat()}
    name='mongo_recheck.json' if args.inspect_latest else 'mongo_check.json'
    (latest.parent/name).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('MongoDB 검증 기록:',latest.parent/name)

if __name__=='__main__':main()
