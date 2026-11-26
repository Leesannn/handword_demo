"""기존 로컬 파이프라인을 SSH 터널의 AWS 시안 DB에 연결해 실행한다."""
import argparse
import getpass
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("init", "api", "worker", "spark", "test-jobs", "test-spark", "test-words"))
    parser.add_argument("--project", type=Path, default=Path.home() / "Desktop/sign-language-practice")
    args = parser.parse_args()
    root = args.project.resolve()
    packages = root / "02_파이프라인"
    data = root / "04_데이터"
    jobs = packages / "video_jobs_v0.1_20261109"
    runtime = root / "aws_pipeline_runtime_v1"
    prefix = "ksl.aws.video.recognition"
    job_db = "ksl_demo_video_jobs_aws_v1"
    stats_db = "ksl_demo_video_stream_stats_aws_v1"
    common = ["--broker", "127.0.0.1:19092", "--prefix", prefix]
    if args.role in ("init", "api", "worker"):
        script = jobs / "video_job_pipeline.py"
        command = [str(script), args.role, *common, "--database", job_db,
                   "--port", "8771", "--storage", str(runtime / "storage"),
                   "--results", str(runtime / "processing_results")]
    elif args.role == "spark":
        script = packages / "video_spark_stats_v0.1_20261109/spark_video_stats.py"
        command = [str(script), *common, "--database", stats_db,
                   "--checkpoint", str(runtime / "spark_checkpoint")]
    elif args.role == "test-words":
        script = packages / "video_word_checks_v0.1_20261109/test_video_word_cases.py"
        command = [str(script), *common, "--stats-database", stats_db,
                   "--port", "8771", "--jobs-dir", str(jobs), "--case", "all",
                   "--recordings", str(data / "recordings")]
    elif args.role == "test-spark":
        script = packages / "video_spark_stats_v0.1_20261109/test_video_spark_stats.py"
        command = [str(script), *common, "--stats-database", stats_db,
                   "--port", "8771", "--jobs-dir", str(jobs),
                   "--video", str(data / "recordings/webcam_20261105_151643_813679.mp4")]
    else:
        script = jobs / "test_video_jobs.py"
        command = [str(script), *common, "--database", job_db, "--port", "8771",
                   "--video", str(data / "recordings/webcam_20261105_151643_813679.mp4")]
    if not script.is_file():
        print(f"실행 파일이 없습니다: {script}")
        return 1
    environment = os.environ.copy()
    # 기존 터미널의 로컬 DB 설정은 변경하지 않고 자식 프로세스에만 전달한다.
    environment.pop("KSL_MONGODB_URI", None)
    if args.role != "init":
        password = getpass.getpass("ksl_pipeline 비밀번호 (저장하지 않음): ")
        environment["KSL_MONGODB_URI"] = (
            "mongodb://ksl_pipeline:" + quote(password, safe="")
            + "@127.0.0.1:27018/?authSource=admin&directConnection=true"
        )
        password = None
    print(f"실행 역할: {args.role} / API 포트: 8771", flush=True)
    print(f"작업 DB: {job_db} / 통계 DB: {stats_db}", flush=True)
    print(f"Kafka 접두사: {prefix}", flush=True)
    try:
        return subprocess.call([sys.executable, *command], cwd=root, env=environment)
    except KeyboardInterrupt:
        return 130
    finally:
        environment.pop("KSL_MONGODB_URI", None)


if __name__ == "__main__":
    sys.exit(main())
