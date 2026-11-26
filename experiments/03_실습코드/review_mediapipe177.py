"""Display saved MediaPipe177 coordinates on the original video; no inference."""
import argparse
import hashlib
import json
from pathlib import Path
from project_paths import resolve_saved_path

HAND_EDGES=[(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(0,17),(17,18),(18,19),(19,20)]
POSE_EDGES=[(11,12),(11,13),(13,15),(12,14),(14,16)]


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def load_arrays(path):
    import numpy as np
    meta=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if meta.get('schema_version')!='mediapipe177-assigned-pilot-v1':raise ValueError('지원하지 않는 좌표 형식입니다.')
    if digest(path)!=meta['array_sha256']:raise ValueError('저장 후 좌표 파일이 변경됐습니다.')
    with np.load(path,allow_pickle=False) as data:
        arrays={k:data[k].copy() for k in data.files}
    n=len(arrays['coordinates'])
    if arrays['coordinates'].shape!=(n,177) or arrays['landmark_valid'].shape!=(n,59):raise ValueError('좌표 또는 마스크 크기가 다릅니다.')
    points=arrays['coordinates'].reshape(n,59,3)
    if not np.array_equal(arrays['landmark_valid'],np.isfinite(points).all(axis=2)):raise ValueError('좌표와 마스크가 다릅니다.')
    if not np.array_equal(arrays['source_frame_indices'],np.arange(n)):raise ValueError('전체 원본 프레임 순서가 아닙니다.')
    return meta,arrays


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coordinates',type=Path)
    parser.add_argument('--start',type=int,help='원본 영상 프레임 번호, 1부터 시작')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    if args.coordinates:path=args.coordinates.resolve()
    else:
        files=list((root.parent / '04_데이터'/'ksl_data/mediapipe177_pilot').rglob('NIA_SL_WORD0815_REAL12_F.npz'))
        if not files:raise FileNotFoundError('먼저 우유 영상의 177개 좌표를 생성하세요.')
        path=max(files,key=lambda p:p.stat().st_mtime)
    meta,data=load_arrays(path)
    video=resolve_saved_path(meta['source_video'])
    if digest(video)!=meta['video_sha256']:raise ValueError('원본 영상이 변경됐습니다.')
    import numpy as np
    import cv2
    points=data['coordinates'].reshape(-1,59,3)
    word_ids=np.flatnonzero(data['word_interval_mask'])
    if not len(word_ids):raise ValueError('단어 구간이 비어 있습니다.')
    i=args.start-1 if args.start is not None else int(word_ids[0])
    if not 0<=i<len(points):raise ValueError('시작 프레임 번호 범위를 확인하세요.')
    print('좌표:',path)
    print(f'라벨 기준 동작 구간: {word_ids[0]+1}~{word_ids[-1]+1}번')
    print('상체 초록색 / 왼손 청록색 / 오른손 주황색. 좌우 이름은 모델 기반 후보입니다.')
    cap=cv2.VideoCapture(str(video));playing=False;overlay=True;cached=None;cached_i=-1
    window='Saved MediaPipe177 - hands and upper body'
    try:
        if not cap.isOpened():raise RuntimeError('원본 영상 열기 실패')
        if abs(cap.get(cv2.CAP_PROP_FPS)-meta['fps'])>1e-5:raise ValueError('영상 FPS가 다릅니다.')
        while True:
            if i!=cached_i:
                if not cap.set(cv2.CAP_PROP_POS_FRAMES,int(data['source_frame_indices'][i])):raise RuntimeError('프레임 이동 실패')
                ok,frame=cap.read()
                if not ok:raise RuntimeError('프레임 읽기 실패')
                scale=min(960/frame.shape[1],640/frame.shape[0],1)
                cached=cv2.resize(frame,(round(frame.shape[1]*scale),round(frame.shape[0]*scale)));cached_i=i
            image=cached.copy();h,w=image.shape[:2]
            if overlay:
                pixels=[(round(float(x)*(w-1)),round(float(y)*(h-1))) if valid and 0<=x<=1 and 0<=y<=1 else None for (x,y,z),valid in zip(points[i],data['landmark_valid'][i])]
                for offset,edges,color in [(42,POSE_EDGES,(60,220,60)),(0,HAND_EDGES,(255,220,0)),(21,HAND_EDGES,(0,180,255))]:
                    for a,b in edges:
                        p,q=pixels[offset+a],pixels[offset+b]
                        if p is not None and q is not None:cv2.line(image,p,q,color,2)
                for j,p in enumerate(pixels):
                    if p is not None:cv2.circle(image,p,3,(255,220,0) if j<21 else (0,180,255) if j<42 else (60,220,60),-1)
                for joint,name in [(11,'L shoulder'),(12,'R shoulder'),(13,'L elbow'),(14,'R elbow'),(15,'L wrist'),(16,'R wrist')]:
                    p=pixels[42+joint]
                    if p is not None:cv2.putText(image,name,p,cv2.FONT_HERSHEY_SIMPLEX,.42,(60,220,60),1)
            canvas=np.zeros((h+115,max(w,960),3),dtype=np.uint8);canvas[115:,:w]=image
            vis=data['pose_visibility'][i,[11,12]]
            lines=[f'Frame {i+1}/{len(points)} | {"WORD" if data["word_interval_mask"][i] else "OUTSIDE WORD"} | {"PLAY" if playing else "PAUSE"}',
                   f'Shoulder visibility L/R: {vis[0]:.3f} / {vis[1]:.3f} (not localization accuracy)',
                   'SPACE: play/pause | A/D: step | O: overlay | R: word start | Q: quit',
                   'Saved coordinates only. No gap filling or new inference.']
            for r,line in enumerate(lines):cv2.putText(canvas,line,(10,23+27*r),cv2.FONT_HERSHEY_SIMPLEX,.53,(255,255,255),1)
            cv2.imshow(window,canvas)
            key=cv2.waitKey(max(1,round(1000/meta['fps'])) if playing else 30)&255
            if key in (ord('q'),27) or cv2.getWindowProperty(window,cv2.WND_PROP_VISIBLE)<1:break
            if key==ord(' '):playing=not playing
            elif key in (ord('a'),ord('d')):i=max(0,min(len(points)-1,i+(1 if key==ord('d') else -1)));playing=False
            elif key==ord('o'):overlay=not overlay
            elif key==ord('r'):i=int(word_ids[0]);playing=False
            elif playing:
                i=min(len(points)-1,i+1)
                if i==len(points)-1:playing=False
    finally:cap.release();cv2.destroyAllWindows()


if __name__=='__main__':main()
