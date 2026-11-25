# 게시 패키지와 자료 근거

이 패키지는 팀이 구현·수행한 프로젝트의 기술 설명과 측정 근거를 정리한 GitHub 게시용 문서입니다. 앱 원본 ZIP·모델·본보기 자산·인증정보·사용자 이벤트 원문은 재배포 묶음에서 제외했습니다.

## 패키지 구성

| 위치 | 내용 |
|---|---|
| README.md | 프로젝트 소개·수행 내용·아키텍처·ERD·결과 |
| docs/instructor-requirements.md | 강사 과제와 연결되는 실제 팀 수행 내용 |
| docs/streaming-semantics.md | Kafka 수집·키·Spark 소비·집계·재처리 |
| docs/architecture.md | 앱·서버·DB·AWS 네트워크 |
| docs/app-engine.md | 좌표 전처리·GRU 계산·기준 데이터 재검증 |
| docs/data-contract.md | 이벤트·식별자·시각·원장 구조 |
| docs/data-model.md | 실제 원장 ERD·이벤트 논리 관계 |
| docs/data-flow.md | 사용자 행동부터 적재·오류 조사까지 시각화 |
| docs/reliability-and-optimization.md | 예외 처리·재전송·재처리·조회 인덱스 |
| docs/design-decisions.md | 적용한 구성의 이유와 기술적 특성 |
| docs/operations.md | 단건 조회·응답별 조사·운영 수행 기록 |
| docs/verification.md | 직접 수행한 결과와 서버 보고 |
| docs/presentation.md | 수행 내용 중심 발표 흐름·질문 답변 |
| evidence/ | DB·엔진 결과 JSON과 원본 자료 해시 |

## 작성 근거

| 자료 | 반영한 내용 | 근거 유형 |
|---|---|---|
| aws-deployment-and-data-pipeline.md | EC2·HTTPS·API·Kafka·Spark·집계·재처리 | 서버 담당자 제공 보고 |
| 수어칠판_아이폰앱.zip | Swift 화면·엔진·Sync·이벤트 규격 | 압축 내부 코드·문서 검토 |
| 수어칠판_안드로이드앱.zip | Expo·WebView·GRU·이벤트 전송 | 압축 내부 코드·문서 검토 |
| 기존 팀 handoff 문서 | PrivateLink·TLS·인증·운영 점검 | 팀 운영 자료 |
| 11월 23일 DB 진단·인덱스 결과 | 문서 검사 73→10·원문 비교·임시 예외 시험 | 실제 AWS 실행 |
| 11월 23~25일 MongoDB 조회 | 이벤트 ID·오프셋·시각·device 대조 | 실제 AWS 조회 |
| 앱 담당자 전송 목록 | 단말 이벤트와 원장 연결 | 제공 목록·DB 대조 |
| Android 단일 기준 데이터 | 전처리·확률·감사 판정 | 11월 25일 Node.js 직접 계산 |
| 11월 25일 강사 지침 | 주제와 팀이 진행한 과제 영역 연결 | 사용자 전달 요구사항 |

원본 자료의 SHA-256은 [source-materials.json](../evidence/source-materials.json)에 보존했습니다. 원본 앱·서버 자료의 식별값과 현재 실행 환경의 관측 결과를 각각의 근거로 기록합니다.

## 공개 파일 처리

패키지는 설명 문서와 비밀값·사용자 원문이 없는 결과 파일로 구성했습니다. 실사용 API 키·DB 비밀번호·SSH 키·인증서 개인키·전체 DB 접속 문자열은 포함하지 않았습니다. 원본 앱의 모델·AIHub 본보기·기타 자산에 포함된 이용 조건은 원본 자료의 조건을 따릅니다.
