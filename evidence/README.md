# 검증 근거 파일

원시 좌표·모델 가중치·실사용 인증정보를 포함하지 않는 측정 결과를 보관합니다. 실제 사용자 식별자와 전체 이벤트 payload도 재배포하지 않습니다.

| 파일 | 실행 범위 | 결과 |
|---|---|---|
| [android-engine-reference.json](android-engine-reference.json) | 2026-11-25 제공 엔진·단일 fixture를 Node.js VM에서 재계산 | 전처리·확률 오차 허용 범위 통과, 감사 판정 |
| [mongodb-index-and-exceptions.json](mongodb-index-and-exceptions.json) | 2026-11-23 실제 AWS 인덱스 적용·별도 임시 컬렉션 시험 | 문서 검사 73→10, 원문 일치, 재시도·11000·121 확인 |

Android 결과의 source_files는 ZIP 내부 3개 파일의 SHA-256입니다. 이는 원본 모델·fixture의 공개 권한을 부여하는 항목이 아닙니다. DB 결과는 당시 실행 도구가 저장한 결과 파일을 옮겼습니다. 최신 운영 상태나 새로운 부하 시험으로 해석하지 않습니다.

조건과 한계는 [앱 엔진](../docs/app-engine.md)과 [검증 결과](../docs/verification.md)에 있습니다. 서버 재처리·상시 적재는 담당자 제공 보고로 표시하며, 원시 서버 로그가 있는 것처럼 결과 파일을 생성하지 않았습니다.
