"""워커 중단·복구와 Spark 체크포인트 재시작을 단계별로 검증합니다."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid
from pymongo import MongoClient
from kafka import KafkaProducer

def require(condition,message):
    if not condition:raise RuntimeError(message)

def until(check,seconds=180):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=check()
        if value:return value
        time.sleep(.5)
    raise RuntimeError('확인 시간 초과. API·워커·Spark의 마지막 로그를 확인하세요.')

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def snapshot(db):
    # 배치 ID는 재처리로 바뀔 수 있으므로 값·고유 기록을 비교합니다.
    records={r['_id']:{'fingerprint':r['fingerprint'],'event_time':r['event_time'].isoformat()}
        for r in db.event_ledger.find()}
    require(len(records)<=10000,'소규모 실습의 원장 건수 제한을 넘었습니다.')
    return {'ledger':records,
        'words':{r['_id']:r['count'] for r in db.word_totals.find()},
        'windows':{r['_id']:r['count'] for r in db.word_windows_1m.find()},
        'states':{r['_id']:r['count'] for r in db.status_totals.find()}}

def statistics_match(db):
    words={};windows={};states={}
    for row in db.event_ledger.find():
        status=row['status'];states[status]=states.get(status,0)+1
        if status=='completed':
            case=row['class_id'];words[case]=words.get(case,0)+1
            start=row['event_time'].replace(second=0,microsecond=0,tzinfo=timezone.utc)
            key=start.isoformat()+'|'+case;windows[key]=windows.get(key,0)+1
    current=snapshot(db)
    return current if (current['words'],current['windows'],current['states'])==(words,windows,states) else None

def checkpoint_state(path):
    binding=path/'ksl_binding.json'
    require(binding.is_file(),'기존 영상용 Spark 체크포인트를 찾을 수 없습니다: '+str(path))
    commits=[p for p in (path/'commits').glob('*') if p.is_file() and p.name.isdigit()]
    require(bool(commits),'완료된 Spark 배치 커밋이 없습니다. 이전 통계 검사를 먼저 확인하세요.')
    latest=max(commits,key=lambda p:int(p.name))
    return {'path':str(path.resolve()),'binding_sha256':digest(binding),'commit':int(latest.name),'commit_sha256':digest(latest)}

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['queue-worker','finish-worker','queue-spark','finish-spark'])
    p.add_argument('--port',type=int,default=8770)
    p.add_argument('--broker',default='127.0.0.1:19092')
    p.add_argument('--prefix',default='ksl.video.recognition')
    p.add_argument('--jobs-database',default='ksl_demo_video_jobs_v1')
    p.add_argument('--stats-database',default='ksl_demo_video_stream_stats_v1')
    p.add_argument('--jobs-dir',type=Path,default=root.parent/'video_jobs_v0.1_20261109')
    p.add_argument('--recordings',type=Path,default=root.parents[1] / '04_데이터'/'recordings')
    p.add_argument('--checkpoint',type=Path,default=root.parent/'video_spark_stats_v0.1_20261109/runtime/video_stats_checkpoint')
    p.add_argument('--session',type=Path,default=root/'session.json')
    args=p.parse_args()
    sys.path.insert(0,str(args.jobs_dir.resolve()))
    from test_video_upload import request, upload
    config={'port':args.port,'broker':args.broker,'prefix':args.prefix,'jobs_database':args.jobs_database,
        'stats_database':args.stats_database,'checkpoint':str(args.checkpoint.resolve())}
    if args.stage=='queue-worker':
        require(not args.session.exists(),'기존 session.json을 덮어쓰지 않습니다. 재검사는 --session .\\새이름.json을 사용하세요.')
        state={'config':config,'phase':'started','checks':{},'status':'running',
            'scope':'대기 작업 복구·Spark 재시작 검사. 처리 도중 강제 종료·운영 고가용성 검증은 아님.'}
    else:
        require(args.session.is_file(),'먼저 queue-worker 단계를 실행하세요.')
        state=json.loads(args.session.read_text(encoding='utf-8'))
        require(state['config']==config,'이전 단계와 API·DB·토픽·체크포인트 설정이 다릅니다.')
    def save():
        args.session.parent.mkdir(parents=True,exist_ok=True)
        temp=args.session.with_suffix('.writing')
        temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(args.session)
    def passed(text):
        checks=state['checks'].setdefault(args.stage,[])
        if text not in checks:checks.append(text)
        save();print('[PASS]',text,flush=True)
    base=f'http://127.0.0.1:{args.port}'
    status,health=request(base,'/job-health')
    require(status==200 and health['database']==args.jobs_database and health['topics']['completed']==args.prefix+'.completed.v1',
        '영상 API·DB·토픽 설정을 확인하세요.')
    reference=json.loads((root/'reference/coffee.json').read_text(encoding='utf-8'))
    def post(payload):return request(base,'/v1/video-jobs',json.dumps(payload).encode(),'application/json')
    with MongoClient(os.environ.get('KSL_MONGODB_URI','mongodb://127.0.0.1:27017/'),serverSelectionTimeoutMS=5000) as client:
        jobs=client[args.jobs_database]['jobs'];db=client[args.stats_database]
        def submit(label):
            path=args.recordings/reference['video_filename']
            require(digest(path)==reference['video_sha256'],'기준 커피 영상의 해시가 다릅니다.')
            status,file=upload(base,path.read_bytes(),filename=path.name)
            require(status==201 and file['sha256']==reference['video_sha256'],'영상 업로드 실패·해시 불일치')
            payload={'client_request_id':'recover-'+label+'-'+uuid.uuid4().hex,'file_id':file['file_id']}
            status,job=post(payload);require(status==202,'작업 접수 실패: '+str(job))
            return {'payload':payload,'sequence_id':job['sequence_id'],'file_id':file['file_id']}
        def completed(info):
            status,value=request(base,'/v1/video-jobs/'+info['sequence_id'])
            require(status==200,'작업 조회 실패')
            if value['status']=='failed':raise RuntimeError('인식 작업 실패: '+str(value['error']))
            return value if value['status']=='completed' else None
        def published(info,kind):
            row=jobs.find_one({'_id':info['sequence_id']})
            return row if row and row.get('outbox',{}).get(kind,{}).get('published') else None
        try:
            if args.stage=='queue-worker':
                info=submit('worker');state['worker_job']=info;save()
                passed('영상 업로드·복구 검사 작업 접수 HTTP 202')
                until(lambda:published(info,'request'));passed('요청 Outbox의 Kafka 발행 확인')
                started=time.monotonic()
                while time.monotonic()-started<5:
                    row=jobs.find_one({'_id':info['sequence_id']})
                    require(row['status']=='queued' and row['attempts']==0,
                        '작업이 처리됐습니다. 영상 워커가 모두 종료됐는지 확인하고 검사 기록을 공유하세요.')
                    time.sleep(.5)
                state['queued_observation_seconds']=time.monotonic()-started;state['phase']='worker_wait'
                passed('워커 중단 중 5초간 queued·추론 0회 유지')
                print('다음: 터미널 B에서 워커를 다시 실행한 뒤 finish-worker를 실행하세요.')
            elif args.stage=='finish-worker':
                require(state['phase']=='worker_wait','queue-worker 성공 후 실행하세요.')
                info=state['worker_job'];final=until(lambda:completed(info));result=final['result']
                require(result['candidate']['class_id']=='coffee' and result['video_processing']['frame_interval']=={'start':1,'end':91},
                    '복구 후 후보·구간 불일치')
                state['worker_result']=result;passed('워커 재실행 후 같은 작업 ID로 커피 처리 완료')
                until(lambda:published(info,'result'))
                row=until(lambda:db.event_ledger.find_one({'sequence_id':info['sequence_id']}))
                require(row['event']['candidate']==result['candidate'],'API·원장 후보 불일치')
                until(lambda:statistics_match(db));passed('복구 결과의 Kafka 완료 발행·Spark 통계 반영')
                status,reused=post(info['payload']);require(status==200 and reused['sequence_id']==info['sequence_id'],'중복 요청의 작업 ID 불일치')
                time.sleep(2);row=jobs.find_one({'_id':info['sequence_id']})
                require(row['attempts']==1 and row['result']==result,'재요청으로 추론 횟수·결과가 달라졌습니다.')
                state['phase']='worker_done';passed('동일 요청 재전송 후 작업 ID·결과·추론 1회 유지')
                print('다음: 터미널 D의 Spark만 Ctrl+C로 종료한 뒤 queue-spark를 실행하세요.')
            elif args.stage=='queue-spark':
                require(state['phase']=='worker_done','finish-worker 성공 후 실행하세요.')
                baseline=until(lambda:statistics_match(db));cp=checkpoint_state(args.checkpoint)
                binding=json.loads((args.checkpoint/'ksl_binding.json').read_text(encoding='utf-8'))
                require(all(binding[k]==config[v] for k,v in [('broker','broker'),('prefix','prefix'),('database','stats_database')]),
                    '영상용 Spark 체크포인트 설정이 다릅니다.')
                state['baseline']=baseline;state['checkpoint_before']=cp;save()
                passed('기존 원장·통계·영상용 체크포인트 기준 저장')
                info=submit('spark');state['spark_job']=info;save()
                final=until(lambda:completed(info));require(final['result']['candidate']['class_id']=='coffee','커피 후보 불일치')
                until(lambda:published(info,'result'));state['spark_result']=final['result']
                passed('Spark 중단 중에도 API·영상 워커·Kafka 완료 처리 성공')
                started=time.monotonic()
                while time.monotonic()-started<5:
                    require(db.event_ledger.find_one({'sequence_id':info['sequence_id']}) is None and snapshot(db)==baseline,
                        '통계가 갱신됐습니다. 영상용 Spark가 종료됐는지 또는 다른 요청이 있었는지 확인하세요.')
                    time.sleep(.5)
                state['phase']='spark_wait';passed('Spark 중단 중 5초간 기존 통계 유지·새 결과 미집계 확인')
                print('다음: 터미널 D에서 같은 Spark 명령으로 재실행한 뒤 finish-spark를 실행하세요.')
            else:
                require(state['phase']=='spark_wait','queue-spark 성공 후 실행하세요.')
                info=state['spark_job'];row=until(lambda:db.event_ledger.find_one({'sequence_id':info['sequence_id']}))
                require(row['event']['candidate']==state['spark_result']['candidate'],'API·Spark 후보 불일치')
                current=until(lambda:statistics_match(db));baseline=state['baseline']
                require(all(current['ledger'].get(key)==value for key,value in baseline['ledger'].items()),'기존 원장이 변경·손실됐습니다.')
                passed('Spark 재시작 후 기존 고유 원장·시각 유지')
                require(len(current['ledger'])==len(baseline['ledger'])+1
                    and current['words'].get('coffee',0)==baseline['words'].get('coffee',0)+1
                    and current['states'].get('completed',0)==baseline['states'].get('completed',0)+1,
                    '새 작업 외에 다른 작업이 반영됐는지 또는 통계 불일치를 확인하세요.')
                passed('중단 중 쌓인 작업 1건만 누적·1분·완료 통계에 반영')
                before=state['checkpoint_before']
                def advanced():
                    cp=checkpoint_state(args.checkpoint)
                    require(cp['path']==before['path'] and cp['binding_sha256']==before['binding_sha256'],'체크포인트 설정 변경')
                    previous=args.checkpoint/'commits'/str(before['commit'])
                    require(previous.is_file() and digest(previous)==before['commit_sha256'],'이전 체크포인트 커밋이 없거나 바뀌었습니다.')
                    return cp if cp['commit']>before['commit'] else None
                state['checkpoint_after']=until(advanced)
                producer=KafkaProducer(bootstrap_servers=args.broker,acks='all',value_serializer=lambda v:json.dumps(v,ensure_ascii=False).encode())
                try:
                    for _ in range(3):meta=producer.send(args.prefix+'.completed.v1',key=info['sequence_id'].encode(),value=row['event']).get(timeout=15)
                finally:producer.close(timeout=5)
                key=args.prefix+'.completed.v1:'+str(meta.partition)
                until(lambda:(d if (d:=db.source_offsets.find_one({'_id':key})) and d['offset']>=meta.offset else None))
                require(until(lambda:statistics_match(db))==current,'재시작 후 중복 재전달로 원장·통계가 달라졌습니다.')
                state.update(phase='done',status='passed',final_snapshot=current,duplicate_events_sent=3)
                passed('같은 체크포인트 진행·중복 3회 재전달 후 통계 유지')
                print('전체 복구 검사 완료:',sum(len(items) for items in state['checks'].values()),'개 PASS')
            state.pop('last_error',None);save()
        except Exception as exc:
            state['last_error']={'stage':args.stage,'type':type(exc).__name__,'message':str(exc)};save()
            raise
    reports=root/'results';reports.mkdir(exist_ok=True)
    report=reports/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'_'+args.stage+'.json')
    report.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    print('이번 단계:',len(state['checks'].get(args.stage,[])),'개 PASS')
    print('세션:',args.session.resolve());print('검사 기록:',report)

if __name__=='__main__':main()
