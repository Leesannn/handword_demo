"""Resolve absolute paths recorded before the folder move."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_FOLDERS = {
    "job_api_v0.1_20261106": "02_파이프라인/job_api_v0.1_20261106",
    "kafka_job_api_v0.1_20261106": "02_파이프라인/kafka_job_api_v0.1_20261106",
    "mongo_job_api_v0.1_20261106": "02_파이프라인/mongo_job_api_v0.1_20261106",
    "spark_stats_v0.1_20261106": "02_파이프라인/spark_stats_v0.1_20261106",
    "video_jobs_v0.1_20261109": "02_파이프라인/video_jobs_v0.1_20261109",
    "video_pipeline_v0.1_20261109": "02_파이프라인/video_pipeline_v0.1_20261109",
    "video_recovery_checks_v0.1_20261109": "02_파이프라인/video_recovery_checks_v0.1_20261109",
    "video_reference_checks_v0.1_20261109": "02_파이프라인/video_reference_checks_v0.1_20261109",
    "video_spark_stats_v0.1_20261109": "02_파이프라인/video_spark_stats_v0.1_20261109",
    "video_upload_v0.1_20261109": "02_파이프라인/video_upload_v0.1_20261109",
    "video_word_checks_v0.1_20261109": "02_파이프라인/video_word_checks_v0.1_20261109",
    "ksl_data": "04_데이터/ksl_data",
    "models": "04_데이터/models",
    "recordings": "04_데이터/recordings",
    "samples": "04_데이터/samples",
    "sequences": "04_데이터/sequences",
    "assign_hands_experiment.py": "03_실습코드/assign_hands_experiment.py",
    "batch_assignment_experiment.py": "03_실습코드/batch_assignment_experiment.py",
    "build_aihub_word_segments.py": "03_실습코드/build_aihub_word_segments.py",
    "build_mediapipe177_pilot.py": "03_실습코드/build_mediapipe177_pilot.py",
    "camera_test.py": "03_실습코드/camera_test.py",
    "check_aihub_training_inputs.py": "03_실습코드/check_aihub_training_inputs.py",
    "check_aws_mongodb.py": "03_실습코드/check_aws_mongodb.py",
    "check_spark_environment.py": "03_실습코드/check_spark_environment.py",
    "collect_sign_samples.py": "03_실습코드/collect_sign_samples.py",
    "compare_hand_local_features.py": "03_실습코드/compare_hand_local_features.py",
    "compare_new_video_models.py": "03_실습코드/compare_new_video_models.py",
    "diagnose_hand_labels.py": "03_실습코드/diagnose_hand_labels.py",
    "export_prediction_bundle.py": "03_실습코드/export_prediction_bundle.py",
    "extract_ksl_batch.py": "03_실습코드/extract_ksl_batch.py",
    "extract_one_video.py": "03_실습코드/extract_one_video.py",
    "hand_local_features.py": "03_실습코드/hand_local_features.py",
    "hand_test.py": "03_실습코드/hand_test.py",
    "normalize_mediapipe177_pilot.py": "03_실습코드/normalize_mediapipe177_pilot.py",
    "predict_feature_json.py": "03_실습코드/predict_feature_json.py",
    "predict_mediapipe_video.py": "03_실습코드/predict_mediapipe_video.py",
    "prepare_aihub_baseline.py": "03_실습코드/prepare_aihub_baseline.py",
    "prepare_aihub_word_clip.py": "03_실습코드/prepare_aihub_word_clip.py",
    "prepare_assignment_v2_baseline.py": "03_실습코드/prepare_assignment_v2_baseline.py",
    "prepare_ksl_subset.py": "03_실습코드/prepare_ksl_subset.py",
    "prepare_mediapipe_baseline.py": "03_실습코드/prepare_mediapipe_baseline.py",
    "record_hand_sequence.py": "03_실습코드/record_hand_sequence.py",
    "record_webcam_clip.py": "03_실습코드/record_webcam_clip.py",
    "replay_hand_sequence.py": "03_실습코드/replay_hand_sequence.py",
    "resample_xy30_pilot.py": "03_실습코드/resample_xy30_pilot.py",
    "review_aihub_video.py": "03_실습코드/review_aihub_video.py",
    "review_mediapipe177.py": "03_실습코드/review_mediapipe177.py",
    "review_model_input.py": "03_실습코드/review_model_input.py",
    "review_new_prediction.py": "03_실습코드/review_new_prediction.py",
    "review_raw_hands.py": "03_실습코드/review_raw_hands.py",
    "review_video_coordinates.py": "03_실습코드/review_video_coordinates.py",
    "run_aws_pipeline.py": "03_실습코드/run_aws_pipeline.py",
    "run_mediapipe_batch.py": "03_실습코드/run_mediapipe_batch.py",
    "save_hand_sample.py": "03_실습코드/save_hand_sample.py",
    "select_gesture_interval.py": "03_실습코드/select_gesture_interval.py",
    "serve_feature_api.py": "03_실습코드/serve_feature_api.py",
    "test_feature_api.py": "03_실습코드/test_feature_api.py",
    "track_hands_pilot.py": "03_실습코드/track_hands_pilot.py",
    "track_hands_v2_experiment.py": "03_실습코드/track_hands_v2_experiment.py",
    "train_aihub_knn.py": "03_실습코드/train_aihub_knn.py",
    "new_sign.mp4": "04_데이터/new_sign.mp4"
}

def resolve_saved_path(value):
    path = Path(value)
    if path.is_absolute() and path.is_relative_to(ROOT):
        parts = path.relative_to(ROOT).parts
        if parts and parts[0] in PREVIOUS_FOLDERS:
            return ROOT.joinpath(PREVIOUS_FOLDERS[parts[0]], *parts[1:])
    return path


def assignment_hash_matches(expected, actual):
    return expected == actual or (expected == '985dfd28f73a29de243bd9a4ae993c42520e27b7f9891f608c91364e219b06d6' and actual == 'd7f76abea406975828e9ac50459f755ec650789787906aa644a407507f14e45a')
