"""SSH 터널을 통해 AWS 시안 DB의 인증 및 제한된 CRUD를 확인한다."""

import getpass
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4


DATABASES = ("ksl_demo_video_jobs_aws_v1", "ksl_demo_video_stream_stats_aws_v1")


def main():
    try:
        from pymongo import MongoClient
        from pymongo.errors import OperationFailure, PyMongoError
    except ImportError:
        print("pymongo가 없습니다. 프로젝트 가상환경의 Python으로 실행하세요.")
        return 1

    report = {
        "run_id": str(uuid4()),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": "127.0.0.1:27018 (SSH 터널)",
        "username": "ksl_pipeline",
        "checks": [],
        "scope": "인증·일회성 검사 문서 저장/조회/삭제. 파이프라인 통합 및 장기 안정성 검증 아님.",
    }

    def record(name, passed):
        report["checks"].append({"name": name, "passed": bool(passed)})
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")

    options = dict(host="127.0.0.1", port=27018, directConnection=True,
                   serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                   socketTimeoutMS=10000, appname="ksl-aws-db-check")
    password = getpass.getpass("ksl_pipeline 비밀번호 (화면에 표시되지 않음): ")
    client = None
    try:
        with MongoClient(**options) as anonymous:
            try:
                anonymous[DATABASES[0]]["_connection_checks"].find_one({"_id": report["run_id"]})
            except OperationFailure as exc:
                if exc.code != 13:
                    raise
                record("비인증 데이터 조회 거부", True)
            else:
                record("비인증 데이터 조회 거부", False)
                raise RuntimeError("AUTHORIZATION_NOT_ENFORCED")

        client = MongoClient(**options, username="ksl_pipeline", password=password, authSource="admin")
        password = None
        authenticated = client.admin.command("connectionStatus")["authInfo"]["authenticatedUsers"]
        ok = any(item.get("user") == "ksl_pipeline" and item.get("db") == "admin"
                 for item in authenticated)
        record("파이프라인 전용 계정 인증", ok)
        if not ok:
            raise RuntimeError("AUTHENTICATED_USER_MISMATCH")

        for database in DATABASES:
            collection = client[database]["_connection_checks"]
            document = {"_id": report["run_id"], "purpose": "AWS 연결 검사", "value": 1}
            try:
                inserted = collection.insert_one(document)
                record(f"{database}: 검사 문서 저장", inserted.acknowledged)
                record(f"{database}: 저장 내용 조회 일치", collection.find_one({"_id": document["_id"]}) == document)
                updated = collection.update_one({"_id": document["_id"]}, {"$set": {"value": 2}})
                loaded = collection.find_one({"_id": document["_id"]})
                record(f"{database}: 검사 문서 수정", updated.modified_count == 1 and loaded is not None and loaded.get("value") == 2)
            finally:
                deleted = collection.delete_one({"_id": document["_id"]})
                record(f"{database}: 검사 문서 삭제", deleted.deleted_count == 1)
    except (PyMongoError, RuntimeError, OSError) as exc:
        # 예외 전문에는 접속 정보가 들어갈 수 있어 유형과 코드만 기록한다.
        report["error"] = {"type": type(exc).__name__, "code": getattr(exc, "code", None)}
        record("전체 연결 검사 완료", False)
        print("연결·인증·권한을 확인하세요. 비밀번호는 공유하지 마세요.")
        print(f"오류 유형: {report['error']['type']} / 코드: {report['error']['code']}")
        print("중간 실패 시 이번 run_id의 검사 문서가 남았는지 확인이 필요할 수 있습니다.")
    finally:
        password = None
        if client is not None:
            client.close()

    report["passed"] = bool(report["checks"]) and all(item["passed"] for item in report["checks"])
    output = Path(__file__).resolve().parent / "aws_db_checks"
    output.mkdir(parents=True, exist_ok=True)
    filename = output / f"aws_mongo_check_{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    filename.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n검사 결과: {'PASS' if report['passed'] else 'FAIL'}")
    print(f"검사 기록: {filename}")
    print("비밀번호 저장 없음 / 기존 업무 문서 수정·삭제 없음")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
