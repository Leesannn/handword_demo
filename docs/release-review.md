# 게시 범위와 자료 출처

이 패키지는 GitHub 게시용 문서 초안입니다. 앱·서버 원본 소스의 병합, GitHub 업로드, 새 공개 라이선스 부여는 별도 단계입니다. 팀 개인 확장 프로젝트의 자료는 포함하지 않았습니다.

## 공개 전 파일 점검

앱 ZIP은 원본 상태에서 아래 항목을 포함합니다. 파일 내용의 비밀값은 이 문서에 복사하지 않았습니다.

| 발견 위치 | 확인·정리할 내용 |
|---|---|
| iOS `ios-board/KSLBoard/Resources/Server.plist` | 실제 접속 키가 들어갈 수 있는 설정. 공개본은 예시 설정과 로컬 주입 절차로 구성 |
| Android `expo-board/web/dist/local-key.pem` | 로컬 HTTPS 개인키. 배포 파일에 들어가는 경로를 확인하고 공개 묶음에서 제거 |
| Android `expo-board/web/dist/local-cert.pem` | 로컬 시험 인증서. 생성 절차와 공개 필요성 확인 |
| Android `engine/model.json`, iOS Core ML 패키지 | 모델 담당자와 데이터 이용 조건을 확인해 공개 범위 결정 |
| iOS `demo_*.json`, Android `engine/demo_frames/` | AIHub 좌표 기반 본보기 포함. 원문 README는 내부용이라고 명시 |
| iOS `Signer.usdz` 및 앱별 자산 | 출처·제작 도구·개별 자산 라이선스 표시 검토 |
| 생성된 `page.js`, `web/dist/index.html`, APK | 설정·모델·본보기 자산이 번들에 포함될 수 있어 생성 결과까지 검사 |
| 프로젝트 서명·개인 경로 | 팀별 서명 설정과 로컬 경로를 공개 빌드 안내에 맞게 정리 |

앱 소스 README의 내부 시험·배포 제한 문구와 외부 데이터 이용 조건을 보존해 판단해야 합니다. Android의 LICENSE는 Expo 저작권 문구를 포함합니다. 이를 팀 자체 코드·모델·데이터 전체의 공개 허용으로 해석하지 않습니다.

공개 초안에는 실사용 API 키, DB 비밀번호, SSH 키, 인증서 개인키, 전체 MongoDB 접속 문자열을 포함하지 않았습니다. 과거 채팅에 전달된 인증 키는 원본 앱·생성 번들과 공개 이력을 검사한 뒤 노출 범위에 맞춰 갱신을 검토합니다. 실제 키 교체는 팀 배포 설정과 함께 수행해야 합니다.

## 저장소 구조 제안

현재 ZIP의 iOS 경로 의존성을 보존하는 합본 구조 제안입니다. 실제 병합 전에 팀과 확정합니다.

```text
README.md
docs/
  architecture.md
  app-engine.md
  data-contract.md
  data-model.md
  data-flow.md
  reliability-and-optimization.md
  design-decisions.md
  operations.md
  verification.md
  presentation.md
  release-review.md
evidence/
  README.md
  android-engine-reference.json
  mongodb-index-and-exceptions.json
  source-materials.json
mobile/
  ios-board/             SwiftUI 화면·Sync
  ios/KSLSign/           ios-board가 참조하는 공통 엔진
  expo-board/            Android Expo·WebView
server/                 서버 담당자의 실제 API·Kafka·Spark 소스
database/               검토한 DB 인덱스·점검 스크립트
```

현재 게시 묶음은 README, docs, 비밀값·사용자 원문을 제외한 evidence 결과 파일로 구성됩니다. 서버는 설명 MD만 제공됐으므로 실행 코드와 Docker Compose는 이 문서 묶음에 포함하지 않습니다. 빌드 산출물·모델·AIHub 자산의 공개 범위는 위 조건을 따릅니다.

## 자료가 뒷받침하는 범위

| 항목 | 현재 근거 | 자료로 확정하지 않은 사항 |
|---|---|---|
| 팀 소개 | 역할 단위 기여 정리 | 이름·프로필·기간·모델 학습 담당 |
| 앱 실제 구현 | 제공 Swift·JS와 문서 확인 | 마지막 커밋, 현재 빌드, 최신 BaseURL 반영 |
| 신뢰도 기준 | 제공 코드 0.6 | 평가로 확정할 기준·목적 |
| 동의·수집 범위 | 초기 안내와 최신 앱 README 차이 | 실제 화면·학습/번역 범위·삭제 경로 |
| 서버 환경 | 제공 MD에 Ubuntu24.04·t3.medium | 이미지 버전·실제 Compose·지속 볼륨 |
| 집계 저장 | 서버가 MongoDB 스냅샷 보고 | 컬렉션명·키·지연 이벤트·분모·원자성 |
| 샘플 저장 | 서버 로컬 테스트 보고 | S3 버킷·권한·실제 업로드·동일 ID 수정 |
| 플랫폼 구분 | 기존 device 값으로 관측 | 제조사·모델·OS 필드 규격 합의 |
| 공개 라이선스 | 자료별 확인 필요 | 모델·데이터·자산과 자체 코드의 적용 범위 |

## 초안 작성에 사용한 근거

| 근거 | 사용 내용 | 검증 수준 |
|---|---|---|
| `aws-deployment-and-data-pipeline.md` | 메인 EC2·HTTPS·API·Kafka·Spark·재처리·샘플 계획 | 서버 담당자 제공 보고 |
| `수어칠판_아이폰앱.zip` | README·규격서·Swift 엔진·Sync·Xcode 구성 | 압축 내부 파일 직접 검토 |
| `수어칠판_안드로이드앱.zip` | README·package.json·App.js·core.js·리소스 | 압축 내부 파일 직접 검토 |
| 기존 팀 `handoff` 문서 | PrivateLink·TLS·인증·Kafka 저장 검사 절차 | 기존 팀 운영 자료 |
| 11월23일 DB 진단·인덱스 적용 결과 | 73→10 문서 검사, 원문 비교, 임시 예외 시험 | 실제 AWS에서 에이전트 실행 |
| 11월23~25일 MongoDB 조회 결과 | 이벤트 ID·오프셋·수신 시각·device | 실제 AWS에서 에이전트 실행 |
| 앱 담당자 전송 목록 | 개별 이벤트 대조 | 제공 목록과 DB 직접 대조 |
| 제공 Android 엔진·단일 fixture | 전처리·확률·감사 판정 | 11월25일 Node.js에서 직접 재검증 |

기존 DB 진단 도구가 저장한 결과 파일에서 인증정보·사용자 원문이 없는 인덱스·예외 시험 결과를 evidence에 보관했습니다. Android는 제공 파일 해시와 계산 오차를 보관했습니다. 원본 ZIP·서버 문서의 해시는 source-materials.json에 기록합니다. 이 값은 자료 식별용이며 현재 배포 버전과 같다는 보장은 아닙니다.

## 참고 저장소 반영

- [kream-ready-data](https://github.com/Shinkyeongho/kream-ready-data)에서 배경→구조→규칙→검증→한계로 이어지는 근거 중심 구성을 참고했습니다.
- [WooSimWunKka](https://github.com/Shinkyeongho/WooSimWunKka)에서 팀·기능·기술·구조·수행 결과·용어를 연결하는 문서 구성을 참고했습니다. README는 GitHub API로 읽어 목차를 확인했습니다.

두 저장소의 코드·데이터·성과 수치를 수어 프로젝트 실적으로 가져오지 않았습니다. 새 문서는 제공 자료와 실제 팀 검증에 맞춰 작성했습니다.
