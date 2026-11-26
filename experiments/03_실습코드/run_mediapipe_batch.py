"""검증한 개별 도구를 순서대로 실행하는 재시작 가능한 배치 실행기."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from project_paths import resolve_saved_path
import subprocess
import sys

TOOLS=('review_raw_hands.py','track_hands_pilot.py','build_mediapipe177_pilot.py',
       'normalize_mediapipe177_pilot.py','resample_xy30_pilot.py')
PILOTS=('NIA_SL_WORD0115_REAL11_F','NIA_SL_WORD0815_REAL12_F',
        'NIA_SL_WORD1248_REAL11_F','NIA_SL_WORD1290_REAL11_F',
        'NIA_SL_WORD1377_REAL11_F','NIA_SL_WORD1378_REAL11_F',
        'NIA_SL_WORD1544_REAL11_F','NIA_SL_WORD1245_REAL11_F')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def plan(data_root,scope):
    by_id={}
    for p in (data_root/'aihub_word_segments').rglob('*.json'):
        meta=json.loads(p.read_text(encoding='utf-8'))
        if meta.get('schema_version')!='aihub-word-segment-v1' or meta.get('angle')!='F':continue
        sequence=meta['sequence_id']
        if sequence in by_id:raise ValueError(f'중복 구간: {sequence}')
        video=resolve_saved_path(meta['source_video']).resolve()
        if not video.is_file():raise FileNotFoundError(video)
        by_id[sequence]=(p.resolve(),meta,video)
    ids=list(PILOTS) if scope=='pilot8' else sorted(by_id)
    if not ids:raise ValueError('실행 대상이 없습니다.')
    missing=[s for s in ids if s not in by_id]
    if missing:raise ValueError(f'구간 메타데이터 누락: {missing}')
    return [(s,*by_id[s]) for s in ids]


def run_stage(script,args,prefix,log):
    env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
    command=[sys.executable,'-X','utf8',str(script),*map(str,args)]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          encoding='utf-8',errors='replace',env=env)
    log.write('\n실행 인수: '+json.dumps(command,ensure_ascii=False)+'\n'+result.stdout+'\n');log.flush()
    if result.returncode:raise RuntimeError(f'{script.name} 실행 실패. 로그를 확인하세요.')
    if prefix is None:return None
    lines=[line[len(prefix):].strip() for line in result.stdout.splitlines() if line.startswith(prefix)]
    if len(lines)!=1:raise ValueError(f'{script.name}의 저장 경로를 특정할 수 없습니다.')
    path=Path(lines[0]).resolve()
    if not path.is_file():raise FileNotFoundError(path)
    return path


def cache_valid(receipt,fingerprint):
    if not receipt.is_file():return False
    saved=json.loads(receipt.read_text(encoding='utf-8'))
    return saved.get('fingerprint')==fingerprint and bool(saved.get('outputs_sha256')) and all(
        resolve_saved_path(p).is_file() and digest(resolve_saved_path(p))==h for p,h in saved['outputs_sha256'].items())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--scope',choices=('pilot8','all'),default='pilot8',help='기본은 확인한 8개 표본만 실행')
    parser.add_argument('--data-root',type=Path,default=root.parent / '04_데이터'/'ksl_data')
    parser.add_argument('--dry-run',action='store_true',help='파일 변경이나 추론 없이 대상·도구 확인')
    args=parser.parse_args()
    # 개별 도구들은 자신의 폴더 아래 ksl_data를 사용한다.
    # 실제 실행에서 데이터 경로가 다르면 다른 폴더에 잘못 저장하지 않도록 중단한다.
    if not args.dry_run and args.data_root.resolve()!=(root.parent / '04_데이터'/'ksl_data').resolve():
        raise ValueError('실제 실행은 04_데이터/ksl_data를 사용해야 합니다.')
    for name in TOOLS:
        if not (root/name).is_file():raise FileNotFoundError(root/name)
    model_root=args.data_root.resolve().parent/'models'
    for name in ('hand_landmarker.task','pose_landmarker_lite.task'):
        if not (model_root/name).is_file():raise FileNotFoundError(model_root/name)
    # 배치 실행에는 재생 창을 열지 않는 옵션이 필요하다.
    if '--no-preview' not in (root/'track_hands_pilot.py').read_text(encoding='utf-8'):
        raise ValueError('track_hands_pilot.py를 최신 파일로 복사하세요.')
    jobs=plan(args.data_root,args.scope)
    print(f'대상: {len(jobs)}개 / 범위: {args.scope}',flush=True)
    if args.dry_run:
        for sequence,_,meta,_ in jobs:print(sequence,meta['class_id'])
        print('사전 확인 통과. 모델 실행·파일 생성·학습 없음.')
        return
    versions={'python':sys.version}
    for module,package in [('mediapipe','mediapipe'),('numpy','numpy')]:
        versions[module]=importlib.metadata.version(package)
    import cv2
    versions['opencv']=cv2.__version__
    base={'tools':{name:digest(root/name) for name in (*TOOLS,Path(__file__).name)},
          'models':{name:digest(model_root/name) for name in ('hand_landmarker.task','pose_landmarker_lite.task')},'versions':versions}
    output=args.data_root/'mediapipe_batch_v1'
    output.mkdir(parents=True,exist_ok=True)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    results=[]
    for index,(sequence,segment_path,meta,video) in enumerate(jobs,1):
        print(f'[{index}/{len(jobs)}] {sequence}',flush=True)
        raw_path=args.data_root/'raw_hand_diagnostics'/video.parent.name/f'{sequence}.json'
        receipt_dir=output/sequence;receipt_dir.mkdir(parents=True,exist_ok=True)
        fingerprint_input={**base,'video':digest(video),'segment':digest(segment_path),
                           'raw_sha256':digest(raw_path) if raw_path.exists() else None}
        fingerprint=hashlib.sha256(json.dumps(fingerprint_input,sort_keys=True).encode()).hexdigest()
        receipt=receipt_dir/'complete.json'
        row={'sequence_id':sequence,'class_id':meta['class_id'],'signer_group':meta['signer_group']}
        try:
            if cache_valid(receipt,fingerprint):
                cached=json.loads(receipt.read_text(encoding='utf-8'))
                row.update(status='reused',final_npz=cached['final_npz'])
                print('  이전 완료 결과의 해시 확인 후 재사용',flush=True)
            else:
                log_path=receipt_dir/f'{run_id}.log'
                with log_path.open('x',encoding='utf-8') as log:
                    print('  1/5 손 검출 또는 기존 원시 결과 확인',flush=True)
                    run_stage(root/TOOLS[0],['--video',video,'--no-preview'],None,log)
                    raw=json.loads(raw_path.read_text(encoding='utf-8'))
                    if raw['mediapipe_version']!=versions['mediapipe'] or raw['opencv_version']!=versions['opencv']:
                        raise ValueError('기존 원시 검출의 라이브러리 버전이 현재와 다릅니다. 자동 덮어쓰기는 하지 않습니다.')
                    print('  2/5 좌우 손 배정',flush=True)
                    pilot=run_stage(root/TOOLS[1],['--raw',raw_path,'--no-preview'],'실험 결과:',log)
                    print('  3/5 상체 추출 및 177개 좌표 저장',flush=True)
                    combined=run_stage(root/TOOLS[2],['--raw',raw_path,'--pilot',pilot,'--segment',segment_path],'NPZ:',log)
                    print('  4/5 XY 정규화',flush=True)
                    normalized=run_stage(root/TOOLS[3],['--coordinates',combined],'저장:',log)
                    print('  5/5 단어 구간 30프레임 선택',flush=True)
                    final=run_stage(root/TOOLS[4],['--normalized',normalized],'저장:',log)
                artifacts=[raw_path,pilot,combined,combined.with_suffix('.json'),normalized,normalized.with_suffix('.json'),final,final.with_suffix('.json')]
                # 첫 실행에서 새로 생긴 원시 검출 해시를 완료 지문에 반영한다.
                fingerprint_input['raw_sha256']=digest(raw_path)
                fingerprint=hashlib.sha256(json.dumps(fingerprint_input,sort_keys=True).encode()).hexdigest()
                record={'fingerprint':fingerprint,'input_identity':fingerprint_input,'final_npz':str(final),
                        'outputs_sha256':{str(p.resolve()):digest(p) for p in artifacts},'training':False,
                        'limitations':'배정 성공은 관절 위치 정확도를 보장하지 않음. 클래스·촬영 코드 분리를 유지하며 학습하지 않음.'}
                temporary=receipt_dir/f'complete_{run_id}.tmp'
                temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(receipt)
                row.update(status='created',final_npz=str(final))
                print('  완료',flush=True)
        except Exception as error:
            row.update(status='failed',error=str(error),log=str(receipt_dir/f'{run_id}.log'))
            print(f'  실패: {error}',flush=True)
        results.append(row)
        # 중간까지 진행한 결과도 남겨 중단 시 추적할 수 있게 한다.
        report=output/f'batch_{run_id}.json'
        report.write_text(json.dumps({'scope':args.scope,'planned':len(jobs),'processed':len(results),
                         'results':results,'training':False},ensure_ascii=False,indent=2),encoding='utf-8')
    created=sum(r['status']=='created' for r in results)
    reused=sum(r['status']=='reused' for r in results)
    failed=sum(r['status']=='failed' for r in results)
    print(f'\n=== 배치 결과: 신규 {created} / 재사용 {reused} / 실패 {failed} ===')
    print('결과표:',report.resolve())
    print('모델 학습은 실행하지 않았습니다.')
    if failed:raise SystemExit(1)


if __name__=='__main__':main()
