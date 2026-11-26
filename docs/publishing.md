# 기존 GitHub 저장소 갱신

이 패키지는 main 563dea74를 기준으로 팀원 PR을 포함한 기술 문서에 소스를 추가한 통합본입니다. 업로드 대상은 압축 파일 자체가 아니라 압축을 푼 내용입니다.

## Git으로 반영하는 순서

1. 현재 저장소를 복제하거나 기존 작업 폴더에서 git pull을 실행합니다.
2. 압축을 풀어 README·docs·evidence·mobile·experiments·server·tests·tools와 루트 설정 파일을 복사합니다.
3. git status와 git diff --stat으로 수정·추가 파일을 확인합니다.
4. python tools/verify_package.py로 소스 해시·링크·구문을 검사합니다.
5. 변경을 커밋하고 GitHub로 push합니다.

```powershell
git clone https://github.com/Shinkyeongho/handword_demo.git
cd handword_demo
# 이 위치에 통합 ZIP의 내용을 복사합니다.
git status --short
git diff --stat
python tools/verify_package.py
git add README.md docs evidence mobile experiments server tests tools .gitignore .gitattributes requirements-verification.txt
git commit -m "docs: integrate MediaPipe experiments, source snapshots and team pipeline evidence"
git push origin main
```

압축 안에는 Git 내부 폴더가 없습니다. 저장소의 .git은 유지합니다. 최신 main에 추가 커밋이 있다면 해당 변경과 비교해 병합합니다. 이 통합본의 기준 커밋은 evidence/integration-baseline.json에 기록했습니다.

## 반영 후 확인

- README에서 MediaPipe·모델 실험·비동기 작업·모바일·AWS 경로가 연결되는지 확인합니다.
- 모바일·실습 소스 링크와 evidence의 결과 링크를 엽니다.
- 앱 담당자 확인 문서·정리 후 ZIP 해시·57건 적재 결과가 유지되는지 확인합니다.
- 게시 범위는 코드·문서·집계 근거이며 원시 데이터나 실행 자원은 별도 관리합니다.
