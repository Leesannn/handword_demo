# 메인 AWS 서버 구성

서버 담당자가 제공한 배포 보고와 팀의 실제 적재 대조를 연결합니다. 현재 모바일 경로는 다음과 같습니다.

```text
iOS·Android 학습 이벤트
→ Caddy HTTPS
→ FastAPI /v1/events
→ Kafka
→ Spark Structured Streaming
→ PrivateLink·Internal NLB·TLS
→ MongoDB 원장·학습 통계
```

| 실행 요소 | 적용 내용 |
|---|---|
| EC2 | Ubuntu 24.04·t3.medium, Docker·Compose |
| Caddy | Elastic IP 기반 HTTPS·인증서 |
| FastAPI | X-API-Key, 종류별 필드, 배치 100건·본문 1MB |
| Kafka | user_id 키, 이벤트별 JSON 발행, 발행 확인 뒤 202 |
| Spark | 상시 소비·학습 통계·체크포인트·누락 범위 배치 재처리 |
| MongoDB 연결 | 계정 간 PrivateLink·TLS·CA·사용자 인증 |
| 운영 | 자동 재시작 정책, ID·오프셋·원문 대조 |

[서버 담당자 배포 보고](aws-deployment-report.md) · [아키텍처](../docs/architecture.md) · [운영 절차](../docs/operations.md)
