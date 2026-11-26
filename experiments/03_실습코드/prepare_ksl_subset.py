"""Inspect KSL ZIP and safely export selected classes without pickle.load."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import pickletools
import re
import shutil
from zipfile import ZipFile


def read_labels(path):
    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError("라벨 파일이 예상보다 큽니다.")
    operations = list(pickletools.genops(raw))
    allowed = {"MARK", "DICT", "PUT", "INT", "STRING", "SETITEM", "STOP"}
    if not operations or operations[-1][0].name != "STOP":
        raise ValueError("불완전한 라벨 파일입니다.")
    if [op.name for op, _, _ in operations[:2]] != ["MARK", "DICT"]:
        raise ValueError("이 실습에서 지원하지 않는 라벨 형식입니다.")
    labels = {}
    pending = []
    for op, value, position in operations:
        if op.name not in allowed:
            raise ValueError(f"지원하지 않는 pickle 명령입니다: {op.name}")
        if op.name in ("INT", "STRING"):
            pending.append(value)
        elif op.name == "SETITEM":
            if len(pending) != 2 or type(pending[0]) is not int or not isinstance(pending[1], str):
                raise ValueError("정수 번호와 문자열 라벨의 연결 형식이 아닙니다.")
            key, label = pending
            if key in labels:
                raise ValueError("중복된 클래스 번호입니다.")
            labels[key] = label.strip()
            pending = []
    if pending:
        raise ValueError("라벨 쌍이 완성되지 않았습니다.")
    return labels, hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "04_데이터/ksl_data")
    parser.add_argument("--classes", type=int, nargs="+", default=[1, 13])
    parser.add_argument("--max-per-class", type=int, default=0, help="0 exports all selected videos")
    args = parser.parse_args()
    if args.max_per_class < 0:
        parser.error("--max-per-class must be nonnegative")
    root = args.output.resolve()
    labels, label_hash = read_labels(args.labels)
    chosen = list(dict.fromkeys(args.classes))
    for class_id in chosen:
        if not labels.get(class_id):
            parser.error(f"{class_id}: 비어 있거나 없는 라벨입니다.")

    with ZipFile(args.zip) as archive:
        videos = [i for i in archive.infolist() if i.filename.lower().endswith(".mp4")]
        entries = []
        counts = Counter()
        for info in videos:
            member = PurePosixPath(info.filename)
            if len(member.parts) != 2 or not re.fullmatch(r"\d{2}", member.parts[0]):
                raise ValueError(f"예상과 다른 경로: {info.filename}")
            match = re.fullmatch(r"(\d{2})_(\d{2})\.mp4", member.name, re.IGNORECASE)
            if not match or int(match[2]) != int(member.parts[0]):
                raise ValueError(f"폴더와 영상 클래스 번호를 확인하세요: {info.filename}")
            class_id = int(member.parts[0])
            if not labels.get(class_id):
                raise ValueError(f"라벨이 없는 영상 클래스: {class_id}")
            counts[class_id] += 1
            entries.append((info, class_id, match[1]))

        rows = []
        exported = Counter()
        for info, class_id, prefix in sorted(entries, key=lambda item: item[0].filename):
            selected = class_id in chosen and (not args.max_per_class or exported[class_id] < args.max_per_class)
            relative = f"videos/{class_id:02d}/{PurePosixPath(info.filename).name}"
            if selected:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    # Verify the complete existing file, rather than silently overwriting it.
                    from zlib import crc32
                    checksum = 0
                    with target.open("rb") as existing:
                        for block in iter(lambda: existing.read(1024 * 1024), b""):
                            checksum = crc32(block, checksum)
                    if target.stat().st_size != info.file_size or checksum & 0xFFFFFFFF != info.CRC:
                        raise ValueError(f"기존 파일이 원본과 다릅니다. 덮어쓰지 않았습니다: {target}")
                else:
                    # Reading a complete member also checks its ZIP CRC.
                    with archive.open(info) as source, target.open("xb") as dest:
                        shutil.copyfileobj(source, dest)
                exported[class_id] += 1
            rows.append({
                "archive_member": info.filename,
                "class_id": class_id,
                "source_label": labels[class_id],
                "filename_prefix": prefix,
                "group_candidate": f"source_prefix_{prefix}",
                "group_semantics_verified": False,
                "selected": selected,
                "local_relative_path": relative if selected else "",
                "uncompressed_bytes": info.file_size,
                "zip_crc32": f"{info.CRC:08x}",
                "split": "unassigned",
            })
        absent = [c for c in chosen if not counts[c]]
        if absent:
            raise ValueError(f"선택했지만 영상이 없는 클래스: {absent}")
        root.mkdir(parents=True, exist_ok=True)
        with (root / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        (root / "class_labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
        report = {
            "source_zip": str(args.zip.resolve()),
            "source_labels_sha256": label_hash,
            "class_count_with_videos": len(counts),
            "video_count": len(videos),
            "nonempty_label_count": sum(bool(label) for label in labels.values()),
            "label_ids_without_videos": [c for c, label in labels.items() if label and not counts[c]],
            "selected_classes": {str(c): {"label": labels[c], "archive_videos": counts[c], "exported": exported[c]} for c in chosen},
            "group_note": "Filename prefix is a candidate group only; signer identity must be verified before claiming person-independent evaluation.",
            "verification_scope": "ZIP structure and selected member CRC checked; decoding, sign meaning and use permissions are not verified by this script.",
        }
        (root / "dataset_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"원본 영상: {len(videos)}개 / 영상이 있는 클래스: {len(counts)}개")
    for c in chosen:
        print(f"{c:02d}: {labels[c]} / {exported[c]}개 추출")
    print(f"저장 위치: {root}")
    print("manifest.csv: 원본 번호와 라벨 연결 / class_labels.json: 안전하게 변환한 라벨")
    print("파일명 앞 번호가 촬영자 번호인지는 미확인입니다. 실제 영상과 출처 설명으로 확인하세요.")


if __name__ == "__main__":
    main()
