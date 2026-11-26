"""Single-video hand assignment pilot. Not a training-data generator."""
import argparse
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path


def assign(frames, aspect, max_gap=5, max_distance=0.25, min_margin=0.04):
    tracks = {}
    output = []
    for frame in frames:
        number = frame['frame_number']
        detections = frame['detections']
        row = {'frame_number': number, 'assignments': [], 'status': 'no_detections'}
        tracks = {side: value for side, value in tracks.items() if number-value[1] <= max_gap}
        if not detections:
            output.append(row)
            continue
        wrists = []
        for d in detections:
            points = d['landmarks']
            if len(points) != 21 or any(p[0] is None or p[1] is None or not math.isfinite(p[0]) or not math.isfinite(p[1]) for p in points):
                break
            wrists.append((points[0][0], points[0][1]*aspect))
        if len(wrists) != len(detections) or len(detections) not in (1,2):
            row['status'] = 'invalid_detection'; output.append(row); continue
        candidates = []
        if len(tracks) == 2:
            for sides in itertools.permutations(('Left','Right'),len(wrists)):
                distances = [math.dist(w,tracks[s][0]) for w,s in zip(wrists,sides)]
                candidates.append((sum(distances),sides,distances))
            candidates.sort(key=lambda x:x[0])
            best, second = candidates
            if max(best[2]) > max_distance:
                row['status'] = 'distance_too_large'
            elif second[0]-best[0] < min_margin:
                row['status'] = 'ambiguous_position'
            else:
                row['assignments'] = [{'detection_index':d['detection_index'],'side':s} for d,s in zip(detections,best[1])]
                row['status'] = 'position_candidate'
        else:
            # Seed only when both distinct labels are available. These are model
            # labels, not independently verified anatomical ground truth.
            cats = [d['categories'][0] if d['categories'] else {} for d in detections]
            if len(cats)==2 and {c.get('name') for c in cats}=={'Left','Right'} and all((c.get('score') or 0)>=0.7 for c in cats):
                row['assignments'] = [{'detection_index':d['detection_index'],'side':c['name']} for d,c in zip(detections,cats)]
                row['status'] = 'label_seed_candidate'
            else:
                row['status'] = 'await_two_distinct_labels'
        for a in row['assignments']:
            pos = next(i for i,d in enumerate(detections) if d['detection_index']==a['detection_index'])
            tracks[a['side']] = (wrists[pos],number)
        output.append(row)
    return output


def preview(saved, rows, start):
    import cv2
    import numpy as np
    from review_raw_hands import EDGES
    cap = cv2.VideoCapture(saved['source_video'])
    try:
        if not cap.isOpened(): raise RuntimeError('영상을 열 수 없습니다.')
        i = start-1
        if not 0<=i<len(rows): raise ValueError('시작 프레임 범위를 확인하세요.')
        playing=False
        window='Hand assignment PILOT - labels are candidates'
        while True:
            if not cap.set(cv2.CAP_PROP_POS_FRAMES,i): raise RuntimeError('프레임 이동 실패')
            ok,image=cap.read()
            if not ok: raise RuntimeError('영상 읽기 실패')
            scale=min(960/image.shape[1],640/image.shape[0],1)
            image=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale)))
            h,w=image.shape[:2]
            mapping={a['detection_index']:a['side'] for a in rows[i]['assignments']}
            for d in saved['frames'][i]['detections']:
                side=mapping.get(d['detection_index'],'Unassigned')
                color={'Left':(255,220,0),'Right':(0,180,255)}.get(side,(180,180,180))
                points=[None if p[0] is None or p[1] is None or not(0<=p[0]<=1 and 0<=p[1]<=1) else (round(p[0]*(w-1)),round(p[1]*(h-1))) for p in d['landmarks']]
                for a,b in EDGES:
                    if points[a] is not None and points[b] is not None: cv2.line(image,points[a],points[b],color,2)
                for p in points:
                    if p is not None: cv2.circle(image,p,3,color,-1)
                if points[0] is not None: cv2.putText(image,f'{side} / raw D{d["detection_index"]}',points[0],cv2.FONT_HERSHEY_SIMPLEX,.5,color,1)
            canvas=np.zeros((h+100,max(w,960),3),dtype=np.uint8);canvas[100:,:w]=image
            for n,line in enumerate([f'Frame {i+1}/{len(rows)} | {rows[i]["status"]}', 'Candidate Left: cyan | Right: orange | Unassigned: gray', 'SPACE: play/pause | A/D: step | Q: quit. No gap filling.']):
                cv2.putText(canvas,line,(10,25+28*n),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
            cv2.imshow(window,canvas)
            key=cv2.waitKey(max(1,round(1000/saved['fps'])) if playing else 30)&255
            if key in (ord('q'),27) or cv2.getWindowProperty(window,cv2.WND_PROP_VISIBLE)<1: break
            if key==ord(' '): playing=not playing
            elif key in (ord('a'),ord('d')): i=max(0,min(len(rows)-1,i+(1 if key==ord('d') else -1)));playing=False
            elif playing:
                i=min(len(rows)-1,i+1)
                if i==len(rows)-1:playing=False
    finally:
        cap.release();cv2.destroyAllWindows()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--raw',type=Path,default=root.parent / '04_데이터'/'ksl_data/raw_hand_diagnostics/12/NIA_SL_WORD0815_REAL12_F.json')
    parser.add_argument('--start',type=int,default=39)
    parser.add_argument('--no-preview',action='store_true',help='재생 창 없이 배정 결과만 저장')
    args=parser.parse_args()
    saved=json.loads(args.raw.read_text(encoding='utf-8'))
    if saved.get('schema_version')!='raw-hand-review-v1': raise ValueError('진단 파일 형식을 확인하세요.')
    import cv2
    cap=cv2.VideoCapture(saved['source_video'])
    try:
        if not cap.isOpened(): raise RuntimeError('영상 열기 실패')
        w,h=cap.get(cv2.CAP_PROP_FRAME_WIDTH),cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not(w>0 and h>0): raise ValueError('영상 크기 확인 실패')
    finally:cap.release()
    rows=assign(saved['frames'],h/w)
    target=root.parent / '04_데이터'/'ksl_data/hand_tracking_pilot';target.mkdir(parents=True,exist_ok=True)
    path=target/f'{args.raw.stem}_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}.json'
    report={'source_raw':str(args.raw.resolve()),'settings':{'max_gap_frames':5,'max_distance_image_width_units':.25,'min_cost_margin_image_width_units':.04,'label_seed_score_min':.7,'validated':False},'note':'Experimental assignment candidates only. Missing detections are not filled. No training or source overwrite. Anatomical labels depend on model seed correctness.', 'frames':rows}
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('실험 결과:',path)
    print('회색은 배정 보류입니다. 미검출 좌표를 생성하지 않으며 학습 데이터도 변경하지 않습니다.')
    if not args.no_preview:
        preview(saved,rows,args.start)


if __name__=='__main__': main()
