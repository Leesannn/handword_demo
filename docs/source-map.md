# 소스 구성과 실행 단위

이 패키지는 GitHub main의 563dea74를 기준으로 PR #1·#2를 반영한 문서에, 팀의 실습 소스와 제공 앱 코드 스냅샷을 연결한 통합본입니다. 각 영역의 역할과 검증 근거를 함께 읽도록 구성했습니다.

## 저장소 구조

```text
README.md
mobile/
  ios/ios-board/             SwiftUI 앱·Sync·학습 UI
  ios/ios/KSLSign/           MediaPipe Capture·Core ML·전처리
  android/expo-board/        Expo·WebView·JavaScript GRU
experiments/
  03_실습코드/               녹화·MediaPipe·전처리·학습·평가
  02_파이프라인/             특징·영상 작업 API·Kafka·Spark·검사
  kafka_local_v0.1_20261106/  실제 로컬 Kafka Compose
  team-event-validation/    합성 학습 이벤트·MongoDB 통합 검사 도구
server/
  aws-deployment-report.md  서버 담당자의 배포·검증 보고
  README.md                 모바일 경로의 실행 구성 설명
docs/                       기술 설명·데이터 계약·ERD·운영·발표
evidence/                   집계 결과·원본 해시·소스 출처
tests/                      통합본의 배열·변환·평가 함수 검사
tools/                      패키지 무결성 검사
```

experiments는 실제 개발 과정의 실행 단위를 보존합니다. 현재 앱 서버는 서버 담당자의 배포 보고와 운영 검증으로 설명하고, 실습 HTTP API를 실제 배포 FastAPI 코드와 혼동하지 않습니다.

## MediaPipe·학습 코드 읽기 순서

1. experiments/03_실습코드/record_webcam_clip.py: 녹화·시각·파일 저장
2. review_raw_hands.py → track_hands_pilot.py: 원시 검출·손 배정
3. build_mediapipe177_pilot.py → normalize_mediapipe177_pilot.py: 좌표 조립·정규화
4. resample_xy30_pilot.py → prepare_mediapipe_baseline.py: 길이·특징·분할
5. train_aihub_knn.py → compare_hand_local_features.py: 기준선·특징 비교
6. 02_파이프라인/video_jobs_v0.1_20261109: 입력을 비동기 작업으로 연결
7. 02_파이프라인/video_spark_stats_v0.1_20261109: 이벤트 원장·통계·재처리

## 실행 옵션과 의존성

실습 Python 파일은 개별 CLI 실행 단위입니다. 각 파이프라인 폴더의 requirements.txt는 해당 실습에서 사용한 버전을 보존합니다. 원본 데이터·모델 경로는 코드의 --help와 인자로 확인합니다.

```powershell
python experiments/03_실습코드/train_aihub_knn.py --help
python experiments/03_실습코드/prepare_mediapipe_baseline.py --help
python experiments/02_파이프라인/video_spark_stats_v0.1_20261109/spark_video_stats.py --help
```

로컬 Kafka는 아래 구성으로 실행합니다. 19092 포트는 노트북 loopback에 바인딩됩니다.

```powershell
docker compose -f experiments/kafka_local_v0.1_20261106/compose.yaml up -d
```

이 명령은 Kafka 컨테이너를 실행합니다. 영상·특징 작업은 해당 입력·모델과 MongoDB 설정을 사용하는 별도 실행 단위입니다. 관리자는 환경변수 KSL_MONGODB_URI로 접속 정보를 주입합니다.

## 모바일 소스와 자원

iOS는 XcodeGen project.yml·Podfile·Swift 소스, Android는 package.json·빌드 스크립트·WebView 소스·GRU 코드를 포함합니다. iOS는 macOS·Xcode에서, Android는 Expo 프로젝트에서 다룹니다.

팀이 제공한 ZIP의 코드 스냅샷과 11월 25일 앱 담당자의 GitHub 확인 보고는 시점이 다릅니다. 원본 ZIP 해시와 파일별 출처는 source-inventory.json, 정리된 Android 묶음 해시는 source-materials.json의 revised 항목으로 보존했습니다. 최신 보안 조치·실기기 전송 확인은 app-status.md를 근거로 사용합니다.

모델 가중치·MediaPipe task·AIHub 본보기·원시 영상·좌표·설치 파일·생성 번들·접속 설정은 개별 자원으로 관리합니다. 공개 묶음은 해당 코드와 집계 근거를 담고, 자원 이용 조건은 원본 자료의 조건을 따릅니다.

## 두 로컬 폴더의 통합

sign-language-practice와 sign-language-review에서 가상환경·캐시를 제외한 파일을 조사했습니다. 각각 2,507개·1,650개 파일이며, 검토 폴더에만 있는 소스는 없고 대응 소스의 해시 차이도 없었습니다. 동일 폴더를 두 번 넣는 대신 practice를 기준으로 소스를 수록하고 대조 결과를 기록했습니다.

[소스 목록·해시](../evidence/source-inventory.json) · [통합 기준](../evidence/integration-baseline.json)

## 통합본 검사

```powershell
python -m pip install -r requirements-verification.txt
python -m unittest discover -s tests -v
python tools/verify_package.py
```

tests는 합성 배열로 원시 좌표의 정규화·프레임 선택·특징 변환·kNN 동률·평가 함수를 확인합니다. 카메라나 운영 DB에 접속하지 않는 함수 검사입니다. 기존 서비스 시험은 historical evidence로 별도 보존합니다.
