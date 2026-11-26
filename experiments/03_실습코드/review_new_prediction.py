"""새 영상 예측 때 저장한 원시 손 좌표를 재추출 없이 확인."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    root=Path(__file__).resolve().parent
    parser.add_argument('--report',type=Path)
    parser.add_argument('--start',type=int,default=1)
    args=parser.parse_args()
    if args.report:path=args.report.resolve()
    else:
        paths=list((root.parent / '04_데이터'/'ksl_data/new_video_predictions').glob('*/prediction.json'))
        if not paths:raise FileNotFoundError('저장된 새 영상 예측 결과가 없습니다.')
        path=max(paths,key=lambda p:p.stat().st_mtime)
    report=json.loads(path.read_text(encoding='utf-8'))
    saved=json.loads((path.parent/'raw_hands.json').read_text(encoding='utf-8'))
    from review_raw_hands import digest,review
    video=Path(report['video'])
    if saved['video_sha256']!=report['video_sha256'] or digest(video)!=report['video_sha256']:
        raise ValueError('예측 시점의 영상과 현재 영상이 다릅니다.')
    if len(saved['frames'])!=saved['summary']['frame_count']:raise ValueError('프레임 수 불일치')
    print('확인할 영상:',video)
    print('FPS:',saved['fps'])
    print('실제 수어 동작의 시작·끝 프레임 번호를 확인하세요. 손 검출 시작과 같다고 가정하지 않습니다.')
    print('색상은 원시 검출 순서입니다. 이번에는 색상보다 실제 동작 구간을 확인하세요.')
    review(video,saved,args.start)


if __name__=='__main__':main()
