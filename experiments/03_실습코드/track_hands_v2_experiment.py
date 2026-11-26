"""한 손만 보일 때도 보수적으로 배정 후보를 유지하는 별도 실험."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
from project_paths import resolve_saved_path


def assign_v2(frames,aspect,max_gap=5,max_distance=.25,min_margin=.04,label_score_min=.7):
    tracks={};output=[]
    for frame in frames:
        number=frame['frame_number'];detections=frame['detections']
        tracks={s:v for s,v in tracks.items() if number-v[1]<=max_gap}
        row={'frame_number':number,'assignments':[],'status':'no_detections'}
        if not detections:output.append(row);continue
        wrists=[]
        for d in detections:
            points=d['landmarks']
            if len(points)!=21 or any(p[0] is None or p[1] is None or not math.isfinite(p[0]) or not math.isfinite(p[1]) for p in points):break
            wrists.append((points[0][0],points[0][1]*aspect))
        if len(wrists)!=len(detections) or len(detections) not in (1,2):
            row['status']='invalid_detection';output.append(row);continue
        if len(tracks)==2:
            costs=[]
            for sides in itertools.permutations(('Left','Right'),len(wrists)):
                distances=[math.dist(w,tracks[s][0]) for w,s in zip(wrists,sides)]
                costs.append((sum(distances),sides,distances))
            costs.sort(key=lambda item:item[0]);best,second=costs
            if max(best[2])>max_distance:row['status']='distance_too_large'
            elif second[0]-best[0]<min_margin:row['status']='ambiguous_position'
            else:
                row['assignments']=[{'detection_index':d['detection_index'],'side':s} for d,s in zip(detections,best[1])]
                row['status']='position_candidate'
        else:
            # 초기화를 양손 동시 검출로 제한하지 않는다. 중복 라벨은 보류한다.
            cats=[d['categories'][0] if d['categories'] else {} for d in detections]
            names=Counter(c.get('name') for c in cats)
            for index,(d,c) in enumerate(zip(detections,cats)):
                side=c.get('name');score=c.get('score')
                if side not in ('Left','Right') or names[side]!=1 or score is None or score<label_score_min:continue
                # 기존 같은 손에서 급격히 멀어진 후보를 라벨만으로 강제 채택하지 않는다.
                if side in tracks and math.dist(wrists[index],tracks[side][0])>max_distance:continue
                row['assignments'].append({'detection_index':d['detection_index'],'side':side})
            row['status']='partial_label_candidate' if row['assignments'] else 'await_reliable_label'
        for a in row['assignments']:
            i=next(i for i,d in enumerate(detections) if d['detection_index']==a['detection_index'])
            tracks[a['side']]=(wrists[i],number)
        output.append(row)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--raw',type=Path)
    parser.add_argument('--start',type=int,default=51)
    parser.add_argument('--no-preview',action='store_true')
    parser.add_argument('--output',type=Path,default=root.parent / '04_데이터'/'ksl_data/hand_assignment_v2_experiment')
    args=parser.parse_args()
    if args.raw:path=args.raw.resolve()
    else:
        files=list((root.parent / '04_데이터'/'ksl_data/new_video_predictions').glob('*/raw_hands.json'))
        if not files:raise FileNotFoundError('저장된 손 검출 결과가 없습니다.')
        path=max(files,key=lambda p:p.stat().st_mtime).resolve()
    raw=json.loads(path.read_text(encoding='utf-8'))
    from track_hands_pilot import assign,preview
    from review_raw_hands import digest
    if raw.get('schema_version')!='raw-hand-review-v1':raise ValueError('원시 검출 형식을 확인하세요.')
    video=resolve_saved_path(raw['source_video'])
    if digest(video)!=raw['video_sha256']:raise ValueError('원본 영상이 변경됐습니다.')
    capture=json.loads(video.with_suffix('.json').read_text(encoding='utf-8'))
    if capture.get('schema_version')!='webcam-short-clip-v1' or resolve_saved_path(capture['video']).resolve()!=video.resolve():
        raise ValueError('이 실험은 촬영 기록 JSON이 있는 웹캠 영상에 사용하세요.')
    width,height=capture['width'],capture['height']
    if min(width,height)<=0:raise ValueError('영상 크기가 올바르지 않습니다.')
    aspect=height/width
    old=assign(raw['frames'],aspect);new=assign_v2(raw['frames'],aspect)
    selected=None
    comparison_paths=list(path.parent.glob('feature_comparison_*.json'))
    if comparison_paths:
        comparison=json.loads(max(comparison_paths,key=lambda p:p.stat().st_mtime).read_text(encoding='utf-8'))
        if comparison['video_sha256']!=raw['video_sha256']:raise ValueError('비교 결과와 영상이 다릅니다.')
        selected=set(comparison['selected_source_frames_1based'])
    def summarize(rows):
        pairs=[(f,r) for f,r in zip(raw['frames'],rows) if selected is None or f['frame_number'] in selected]
        return {'frames':len(pairs),'raw_detections':sum(len(f['detections']) for f,r in pairs),
                'assigned_detections':sum(len(r['assignments']) for f,r in pairs),
                'frames_with_unassigned_detection':[f['frame_number'] for f,r in pairs if len(r['assignments'])<len(f['detections'])]}
    summary={'scope':'최신 비교의 선택 프레임' if selected is not None else '원본 전체 프레임',
             'before':summarize(old),'experiment':summarize(new)}
    report={'schema_version':'hand-assignment-v2-shadow-experiment-v1','source_raw':str(path),'source_raw_sha256':digest(path),
            'video_sha256':raw['video_sha256'],'settings':{'max_gap_frames':5,'max_distance':.25,'min_margin':.04,'label_score_min':.7},
            'summary':summary,'frames':new,
            'limitations':['좌표를 새로 검출하거나 미검출을 보간하지 않음. 기존 분류 모델과 전처리를 변경하지 않음.',
                           '라벨 점수는 해부학적 좌우의 정확성 보장이 아님. 단일 라벨 초기화로 오배정 위험이 증가할 수 있음.',
                           '배정 수 증가는 좌표 정확도나 분류 성능 향상 입증이 아님.'],'classification_evaluated':False}
    args.output.mkdir(parents=True,exist_ok=True)
    target=args.output/f'{video.stem}_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('비교 범위:',summary['scope'])
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print('저장:',target.resolve())
    print('분류 모델 적용 전 실험입니다. 좌표 정확도와 예측 성능은 별도 검증이 필요합니다.')
    if not args.no_preview:preview(raw,new,args.start)


if __name__=='__main__':main()
