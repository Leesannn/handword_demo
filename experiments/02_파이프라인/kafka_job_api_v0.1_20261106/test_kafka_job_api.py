"""실제 Kafka 요청 소비·완료 이벤트·MongoDB 저장을 검증합니다."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid
from kafka import KafkaConsumer, TopicPartition
from pymongo import MongoClient
from kafka_job_pipeline import DATABASE, PREFIX, BROKER, topics
import test_job_api

def wait_job(base,job_id,timeout=60):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        status,row=test_job_api.call(base,'/jobs/'+job_id)
        assert status==200
        if row['status'] in ('completed','failed'):return row
        time.sleep(.25)
    raise AssertionError('처리 시간 초과: Kafka·API·워커 로그를 확인하세요.')

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8768)
    p.add_argument('--database',default=DATABASE)
    p.add_argument('--prefix',default=PREFIX)
    p.add_argument('--broker',default=BROKER)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--queue-only',action='store_true')
    mode.add_argument('--finish-pending',action='store_true')
    args=p.parse_args()
    base=f'http://127.0.0.1:{args.port}'
    pending=root/'results/pending_probe.json'
    if args.queue_only:
        source=json.loads((root/'examples/request.json').read_text(encoding='utf-8'))
        status,row=test_job_api.call(base,'/jobs',{'client_request_id':'offline-'+uuid.uuid4().hex,'input':source})
        assert status==202
        for _ in range(6):
            time.sleep(.5)
            status,current=test_job_api.call(base,'/jobs/'+row['sequence_id'])
            assert status==200 and current['status']=='queued','워커를 먼저 종료했는지 확인하세요.'
        pending.parent.mkdir(exist_ok=True)
        pending.write_text(json.dumps({'sequence_id':row['sequence_id'],'database':args.database,'prefix':args.prefix}),encoding='utf-8')
        print('[PASS] 워커 없이 접수 성공·queued 유지')
        print('이제 워커를 켠 뒤 --finish-pending 검사를 실행하세요.');return
    if args.finish_pending:
        saved=json.loads(pending.read_text(encoding='utf-8'))
        assert saved['database']==args.database and saved['prefix']==args.prefix
        row=wait_job(base,saved['sequence_id'])
        assert row['status']=='completed',row
        output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output.mkdir(parents=True)
    else:
        saved=sys.argv
        try:
            sys.argv=[saved[0],'--port',str(args.port)]
            test_job_api.main()
        finally:sys.argv=saved
        latest=max((root/'results').glob('*/job_api_check.json'),key=lambda p:p.stat().st_mtime)
        output=latest.parent
        row=json.loads(latest.read_text(encoding='utf-8'))['completed']
    job_id=row['sequence_id']
    with MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000) as client:
        col=client[args.database]['jobs']
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            doc=col.find_one({'_id':job_id})
            if doc and doc.get('outbox',{}).get('result',{}).get('published'):break
            time.sleep(.25)
        assert doc and doc['status']=='completed' and doc['result']==row['result']
        assert doc['consumed']['topic']==topics(args.prefix)['requested'] and doc['attempts']>=1
        print('[PASS] Kafka 요청 소비 위치·MongoDB 결과 확인')
        assert doc['outbox']['request']['published'] and doc['outbox']['result']['published']
        print('[PASS] 요청·완료 Outbox 발행 확인')
        target=doc['outbox']['result']
    consumer=KafkaConsumer(bootstrap_servers=args.broker,group_id=None,enable_auto_commit=False)
    try:
        tp=TopicPartition(topics(args.prefix)['completed'],target['partition'])
        consumer.assign([tp]);consumer.seek(tp,target['offset'])
        deadline=time.monotonic()+15; event=None
        while time.monotonic()<deadline and event is None:
            for batch in consumer.poll(timeout_ms=1000,max_records=1).values():
                for message in batch:event=json.loads(message.value)
        assert event and event['event_id']==target['event_id'] and event['sequence_id']==job_id
        assert event['candidate']==row['result']['candidate']
    finally:consumer.close()
    print('[PASS] Kafka 완료 이벤트와 예측 단어 일치')
    evidence={'sequence_id':job_id,'candidate':row['result']['candidate'],'database':args.database,
              'prefix':args.prefix,'request_consumed':doc['consumed'],'attempts':doc['attempts'],
              'outbox':doc['outbox'],'completed_event':event,
              'mode':'워커 중지 후 재개' if args.finish_pending else '정상 전체 경로',
              'scope':'고정 특징 요청의 통합 검사. 정확도 평가·Spark·알림·AWS 검증이 아님.'}
    (output/'kafka_pipeline_check.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('통합 검사 기록:',output/'kafka_pipeline_check.json')

if __name__=='__main__':main()
