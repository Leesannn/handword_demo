"""Audit and compare raw XY with inverse-normalized saved model input, read-only."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from project_paths import resolve_saved_path

EDGES = [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),
         (10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(0,17),
         (17,18),(18,19),(19,20)]


def audit(dataset, sequence):
    import numpy as np
    spec = json.loads((dataset / 'preprocessing.json').read_text(encoding='utf-8'))
    if spec.get('preprocessing_version') != 'aihub-2d-upper50-nearest30-v1':
        raise ValueError('이 진단이 지원하지 않는 전처리 버전입니다.')
    with (dataset / 'sample_manifest.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = [r for r in csv.DictReader(stream) if r['sequence_id'] == sequence]
    if len(rows) != 1:
        raise ValueError('시퀀스가 목록에 없거나 중복됩니다.')
    row = rows[0]
    raw_path = resolve_saved_path(row['source_npz'])
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != row['source_sha256']:
        raise ValueError('학습 입력 생성 이후 원시 구간 파일이 변경됐습니다.')
    meta_path = raw_path.with_suffix('.json')
    if hashlib.sha256(meta_path.read_bytes()).hexdigest() != row['metadata_sha256']:
        raise ValueError('원시 구간 메타데이터가 변경됐습니다.')
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    with np.load(raw_path, allow_pickle=False) as raw:
        xy = raw['xy'].copy(); valid = raw['valid_2d'].copy()
        source_ids = raw['source_frame_indices'].copy()
        source_times = raw['source_times_seconds'].copy()
    with np.load(dataset / 'dataset.npz', allow_pickle=False) as saved:
        locations = np.flatnonzero(saved['sequence_id'] == sequence)
        if len(locations) != 1:
            raise ValueError('데이터 배열에서 시퀀스를 특정할 수 없습니다.')
        index = int(locations[0])
        x = saved['X'][index].copy(); mask = saved['joint_mask'][index].copy()
        selected_ids = saved['sampled_source_frame_indices'][index].copy()
        selected_times = saved['sampled_source_times_seconds'][index].copy()
        split = str(saved['split'][index])
    positions = np.rint(np.linspace(0, len(xy)-1, 30)).astype(np.int64)
    expected_ids, expected_times = source_ids[positions], source_times[positions]
    if x.shape != (30,150) or mask.shape != (30,50):
        raise ValueError('저장된 모델 입력 배열 크기가 다릅니다.')
    if not np.array_equal(selected_ids, expected_ids) or not np.allclose(selected_times, expected_times, atol=1e-9, rtol=0):
        raise ValueError('선택한 모델 프레임과 원본 프레임 시각 대응이 다릅니다.')
    if not np.array_equal(x[:,100:], mask.astype(x.dtype)):
        raise ValueError('모델의 마스크 특징과 관절 마스크가 다릅니다.')
    shoulders = xy[:,[44,47]]
    center = shoulders.mean(axis=1)
    width = np.linalg.norm(shoulders[:,0] - shoulders[:,1], axis=1)
    usable = valid[:,[44,47]].all(axis=1) & np.isfinite(shoulders).all(axis=(1,2)) & (width > 1.0)
    expected_mask = (valid[:,:50] & np.isfinite(xy[:,:50]).all(axis=2) & usable[:,None])[positions]
    if not np.array_equal(mask, expected_mask):
        raise ValueError('저장된 마스크와 원시 좌표에서 계산한 마스크가 다릅니다.')
    restored = x[:,:100].reshape(30,50,2) * width[positions,None,None] + center[positions,None,:]
    restored[~mask] = np.nan
    original = xy[positions,:50].copy()
    original[~mask] = np.nan
    deltas = np.linalg.norm(restored-original, axis=2)
    comparable = deltas[mask]
    if not comparable.size:
        raise ValueError('비교할 수 있는 유효 관절이 없습니다.')
    maximum = float(comparable.max())
    if maximum > 0.02:
        raise ValueError(f'복원 좌표 차이가 실험 허용값0.02px보다 큽니다: {maximum}')
    report = {
        'sequence_id': sequence, 'split': split, 'source_video': meta['source_video'],
        'model_steps':30, 'source_frames_in_segment':len(xy),
        'source_frame_correspondence_matches':True, 'joint_mask_matches':True,
        'valid_joint_comparisons':int(mask.sum()), 'max_roundtrip_difference_pixels':maximum,
        'mean_roundtrip_difference_pixels':float(comparable.mean()),
        'source_frames_1based':(selected_ids+1).tolist(),
        'source_times_seconds':selected_times.tolist(),
        'scope':'Saved 30-step frame selection, mask and inverse XY normalization checked. Does NOT validate source keypoint/video alignment or recognition correctness.',
        'display_note':'Both panels use the same selected source frame. The right panel inverses stored normalized XY using the corresponding raw shoulders. Frame stepping advances model steps, not every video frame.',
    }
    return report, original, restored, mask, selected_ids, selected_times, meta


def review(report, raw, restored, mask, frame_ids, times, meta):
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(meta['source_video'])
    try:
        if not cap.isOpened():
            raise RuntimeError('원본 영상을 열 수 없습니다.')
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if abs(fps-float(meta['fps_from_preflight'])) > 1e-4:
            raise ValueError('현재 영상 FPS가 사전 검사와 다릅니다.')
        current, cached_step, cached = 0, -1, None
        playing, overlay = False, True
        window = 'Raw keypoints vs saved model input'
        while True:
            if current != cached_step:
                if not cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_ids[current])):
                    raise RuntimeError('선택한 프레임으로 이동할 수 없습니다.')
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError(f'원본 {int(frame_ids[current])+1}프레임 읽기 실패')
                cached, cached_step = frame, current
            source_h, source_w = cached.shape[:2]
            scale = min(600/source_w, 430/source_h, 1.0)
            view = cv2.resize(cached, (round(source_w*scale),round(source_h*scale)))
            panels=[]
            for coords,color in [(raw,(255,220,0)),(restored,(0,180,255))]:
                panel=view.copy()
                if overlay:
                    pixels=[]
                    for i,(x,y) in enumerate(coords[current]):
                        if mask[current,i] and np.isfinite([x,y]).all() and 0<=x<source_w and 0<=y<source_h:
                            pixels.append((round(float(x)*scale),round(float(y)*scale)))
                        else:
                            pixels.append(None)
                    for offset in (0,21):
                        for a,b in EDGES:
                            p,q=pixels[offset+a],pixels[offset+b]
                            if p is not None and q is not None:
                                cv2.line(panel,p,q,color,2)
                    for i,p in enumerate(pixels):
                        if p is not None:
                            cv2.circle(panel,p,3,color if i<42 else (80,220,80),-1)
                panels.append(panel)
            ph,pw=panels[0].shape[:2]
            canvas=np.zeros((ph+175,1240,3),dtype=np.uint8)
            canvas[175:,10:10+pw]=panels[0]
            canvas[175:,630:630+pw]=panels[1]
            lines=[f'{"PLAY" if playing else "PAUSE"} | Model step {current+1}/30 | Source frame {int(frame_ids[current])+1} (1-based) | {times[current]:.3f}s',
                   'LEFT: source XY (cyan) | RIGHT: restored saved model XY (orange)',
                   f'Round-trip max difference: {report["max_roundtrip_difference_pixels"]:.6f} px | Same source frame on both sides',
                   'SPACE: play/pause | A/D: previous/next model step | O: overlay | R: first | Q: quit',
                   'Only selected 30 steps are shown; absent source intervals are not filled by this viewer.']
            for r,line in enumerate(lines):
                cv2.putText(canvas,line,(12,25+29*r),cv2.FONT_HERSHEY_SIMPLEX,0.52,(255,255,255),1)
            cv2.imshow(window,canvas)
            wait=max(1,round((times[current+1]-times[current])*1000)) if playing and current<29 else 30
            key=cv2.waitKey(wait)&0xFF
            if key in (ord('q'),27) or cv2.getWindowProperty(window,cv2.WND_PROP_VISIBLE)<1:
                break
            if key==ord(' '):playing=not playing
            elif key in (ord('a'),ord('d')):
                current=max(0,min(29,current+(1 if key==ord('d') else -1)));playing=False
            elif key==ord('o'):overlay=not overlay
            elif key==ord('r'):current,playing=0,False
            elif playing:
                if current<29:current+=1
                else:playing=False
    finally:
        cap.release();cv2.destroyAllWindows()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--dataset',type=Path,default=root.parent / '04_데이터'/'ksl_data'/'aihub_baseline_v1')
    parser.add_argument('--sequence',default='NIA_SL_WORD0815_REAL12_F')
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--report-dir',type=Path,default=root.parent / '04_데이터'/'ksl_data'/'model_input_review')
    args=parser.parse_args()
    report,*data=audit(args.dataset,args.sequence)
    args.report_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=args.report_dir/f'{args.sequence}_{stamp}.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('시퀀스:',args.sequence)
    print('원본 프레임/시각 대응 검사: 통과')
    print('마스크 일치 검사: 통과')
    print(f'정규화 복원 최대 차이: {report["max_roundtrip_difference_pixels"]:.6f}px')
    print('결과:',target.resolve())
    print('이 검사는 제공 좌표 자체의 영상 지연을 검증하지 않습니다. 모델과 원본 파일은 변경하지 않습니다.')
    if not args.check_only:
        review(report,*data)


if __name__=='__main__':
    main()
