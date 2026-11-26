# 검증 근거 파일

원시 좌표·모델 가중치·실사용 인증정보를 포함하지 않는 측정 결과를 보관합니다. 실제 사용자 식별자와 전체 이벤트 payload도 재배포하지 않습니다.

| 파일 | 실행 범위 | 결과 |
|---|---|---|
| [android-engine-reference.json](android-engine-reference.json) | 2026-11-25 제공 엔진·단일 fixture를 Node.js VM에서 재계산 | 전처리·확률 오차 허용 범위 통과, 감사 판정 |
| [mongodb-index-and-exceptions.json](mongodb-index-and-exceptions.json) | 2026-11-23 실제 AWS 인덱스 적용·별도 임시 컬렉션 시험 | 문서 검사 73→10, 원문 일치, 재시도·11000·121 확인 |

Android 결과의 source_files는 ZIP 내부 3개 파일의 SHA-256입니다. 이는 원본 모델·fixture의 공개 권한을 부여하는 항목이 아닙니다. DB 결과는 당시 실행 도구가 저장한 결과 파일을 옮겼습니다. 최신 운영 상태나 새로운 부하 시험으로 해석하지 않습니다.

조건과 한계는 [앱 엔진](../docs/app-engine.md)과 [검증 결과](../docs/verification.md)에 있습니다. 서버 재처리·상시 적재는 담당자 제공 보고로 표시하며, 원시 서버 로그가 있는 것처럼 결과 파일을 생성하지 않았습니다.


## 개발 과정의 추가 근거

| 파일 | 근거 범위 |
|---|---|
| [model-development.json](model-development.json) | 11월 5일 8개 클래스 kNN 두 기준선, 분할·혼동 행렬·원본 해시 |
| [pipeline-regression.json](pipeline-regression.json) | 11월 9일 영상 작업·Spark·단어 회귀·중단 복구 결과 요약 |
| [source-inventory.json](source-inventory.json) | 수록 소스의 원본 위치·SHA-256, 로컬 두 폴더 대조 |
| [integration-baseline.json](integration-baseline.json) | GitHub 기준 커밋·PR #1·#2·서버 보고 출처 |
| [package-validation.json](package-validation.json) | 11월 26일 통합본 구문·링크·소스 해시·합성 함수 검사 |

과거 서비스 결과는 저장된 실행 보고를 감사한 값이며, 통합본 함수 검사는 11월 26일 직접 실행한 값입니다. 실제 앱 r0006 계산과 실험 kNN 평가의 모델·입력 계약을 각각 명시했습니다.
