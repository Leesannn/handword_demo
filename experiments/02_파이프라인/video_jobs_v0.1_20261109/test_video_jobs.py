"""실제 HTTP·MongoDB·Kafka에서 커피 영상 작업을 검증합니다."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
from test_video_upload import request, upload

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8770)
    p.add_argument('--video',type=Path,default=root.parents[1] / '04_데이터'/'recordings/webcam_20261105_151643_813679.mp4')
    p.add_argument('--database',default='ksl_demo_video_jobs_v1')
    p.add_argument('--prefix',default='ksl.video.recognition')
    p.add_argument('--broker',default='127.0.0.1:19092')
    args=p.parse_args();base=f'http://127.0.0.1:{args.port}'
    checks=[]
    def passed(name):checks.append(name);print('[PASS]',name,flush=True)
    def post(payload):return request(base,'/v1/video-jobs',json.dumps(payload).encode(),'application/json')
    status,health=request(base,'/job-health');assert status==200
    assert health['database']==args.database
    passed('영상 작업 API·MongoDB 준비')
    raw=args.video.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    status,file=upload(base,raw);assert status==201 and file['sha256']==sha
    passed('영상 업로드 HTTP 201·원본 해시 일치')
    payload={'client_request_id':'coffee-'+uuid.uuid4().hex,'file_id':file['file_id']}
    status,job=post(payload);assert status==202
    job_id=job['sequence_id'];passed('영상 인식 작업 접수 HTTP 202·작업 ID')
    status,reused=post(payload);assert status==200 and reused['reused'] and reused['sequence_id']==job_id
    passed('같은 요청 재전송 시 같은 작업 ID HTTP 200')
    status,error=post(dict(payload,frame_interval={'start':2,'end':91}));assert status==409
    passed('같은 요청 키·다른 구간 거부 HTTP 409')
    status,error=post(dict(payload,frame_interval={'start':0,'end':91}));assert status==422
    passed('잘못된 프레임 구간 거부 HTTP 422')
    status,error=post(dict(payload,file_id=str(uuid.uuid4())));assert status==404
    passed('없는 영상 파일 ID 거부 HTTP 404')
    status,error=request(base,'/v1/video-jobs/'+str(uuid.uuid4()));assert status==404
    passed('없는 작업 조회 HTTP 404')
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        status,final=request(base,'/v1/video-jobs/'+job_id);assert status==200
        if final['status'] in ('completed','failed'):break
        time.sleep(.5)
    else:raise RuntimeError('180초 안에 처리되지 않았습니다. 워커·Kafka 로그를 확인하세요.')
    assert final['status']=='completed',final
    assert final['result']['candidate']['class_id']=='coffee',final['result']
    processing=final['result']['video_processing']
    assert processing['video_sha256']==sha and processing['frame_interval']=={'start':1,'end':91}
    assert processing['base_shape']==[30,177] and processing['model_shape']==[30,183]
    passed('워커 영상 처리·커피 후보·구간·특징 크기 확인')
    from pymongo import MongoClient
    from kafka import KafkaConsumer
    import os
    with MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000) as mongo:
        col=mongo[args.database]['jobs'];deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            row=col.find_one({'_id':job_id})
            if all(row.get('outbox',{}).get(kind,{}).get('published') for kind in ('request','result')):break
            time.sleep(.2)
        else:raise RuntimeError('Outbox Kafka 발행 확인 시간 초과')
        assert row['result']==final['result'] and row['consumed']['topic']==args.prefix+'.requested.v1'
        passed('Kafka 요청 소비 위치·MongoDB 결과 일치')
        passed('요청·완료 Outbox 발행 확인')
        consumer=KafkaConsumer(bootstrap_servers=args.broker,enable_auto_commit=False,group_id=None)
        try:
            from kafka import TopicPartition
            out=row['outbox']['result'];tp=TopicPartition(args.prefix+'.completed.v1',out['partition'])
            consumer.assign([tp]);consumer.seek(tp,out['offset']);event=None;deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                for batch in consumer.poll(timeout_ms=500).values():
                    for message in batch:
                        value=json.loads(message.value)
                        if value.get('event_id')==out['event_id']:event=value
                if event:break
            assert event and event['sequence_id']==job_id and event['candidate']==final['result']['candidate']
        finally:consumer.close()
        passed('실제 Kafka 완료 이벤트·API 결과 일치')
    output=root/'results'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');output.mkdir(parents=True)
    report={'passed':len(checks),'checks':checks,'file_id':file['file_id'],'sequence_id':job_id,
        'upload':file,'job_result':final,'completed_event':event,
        'scope':'로컬 단일 워커의 커피 회귀 검사. 모바일·Spark 통계·새 정확도 평가는 아님.'}
    (output/'video_job_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n검사 완료:',len(checks),'개 PASS')
    print('작업 ID:',job_id)
    print('검사 기록:',output/'video_job_check.json')

if __name__=='__main__':main()
