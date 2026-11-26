# 통합 패키지와 출처 관리

2026-11-26 통합본은 최신 GitHub main 563dea74와 팀원이 병합한 PR #1·#2를 기준으로 작성했습니다. 문서와 코드·저장된 실행 결과를 서로 연결했습니다.

## 포함 범위

| 영역 | 포함한 것 | 근거 |
|---|---|---|
| 기존 팀 문서 | README·ERD·아키텍처·이벤트 계약·운영·실기기 결과 | GitHub main 스냅샷 |
| 팀원 수정 | 최신 폰 전송 확인·앱 묶음 정리·보안 조치 보고, README 정리 | PR #1·#2 |
| MediaPipe·학습 | 녹화·추출·손 배정·정규화·재표본화·kNN·특징 비교 코드 | practice·review 로컬 대조 |
| 파이프라인 실습 | 작업 API·MongoDB Outbox·Kafka·Spark·복구·회귀 검사 코드 | 원본 실습 패키지 |
| 모바일 | Swift·Expo·WebView·GRU 소스·빌드 설정·의존성 명세 | 제공 iOS·Android ZIP |
| 메인 서버 | 배포 구성·실제 적재·재처리 보고 | 제공 서버 MD의 구현·검증 부분 |
| 측정 근거 | 원본 결과 파일의 해시·조건·집계 결과 | 기존 evidence와 추가 실험 보고 |
| 통합본 검사 | 합성 함수 검사·구문·JSON·링크·출처 해시 검사 | tests·tools·검사 결과 JSON |

## 코드와 최신 확인 보고의 시점

첨부된 앱 ZIP은 원래 제공된 코드 스냅샷입니다. 11월 25일 팀원 PR은 이후 실기기·앱 정리·보안 조치를 보고합니다. 두 자료를 하나의 코드 버전이라고 합치지 않고, 원본 ZIP·정리 후 ZIP의 해시와 보고 시점을 각각 보존했습니다.

원본별 파일의 출처·해시는 [source-inventory.json](../evidence/source-inventory.json)에, GitHub 기준 커밋과 PR 정보는 [integration-baseline.json](../evidence/integration-baseline.json)에 있습니다. 원래 자료의 [source-materials.json](../evidence/source-materials.json)도 팀원 수정 상태로 유지했습니다.

## 파일 구성 원칙

원시 영상·좌표·학습 NPZ·모델 가중치·MediaPipe 모델 파일·설치 파일·생성 번들·가상환경·체크포인트·DB 런타임·인증정보를 묶지 않았습니다. 코드와 실험 결과를 원본 자원에 연결하는 해시·계약·설명만 제공합니다.

동일한 두 로컬 폴더를 그대로 중복 수록하지 않고, 실제 대조 결과를 기록한 뒤 소스 한 벌을 사용했습니다. 독립 실행 단위 안의 공통 모듈은 해당 패키지의 구조를 보존합니다. 개인 확장 포트폴리오 경로의 코드는 포함하지 않았습니다.

모델·AIHub 본보기·제3자 자산의 이용 조건은 원본 자료의 조건을 따릅니다. Android 제공 LICENSE는 mobile/android/expo-board에 보존했습니다. 이 파일을 별도 모델·데이터 전체의 이용 허락으로 해석하지 않습니다.

## 코드 탐색과 검증

[소스·실행 안내](source-map.md)에서 실행 단위와 경로를 확인할 수 있습니다. 기존 GitHub를 갱신하는 절차는 [업로드 안내](publishing.md)에 있습니다.
