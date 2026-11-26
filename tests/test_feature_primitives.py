"""Synthetic invariants for the packaged historical feature implementations."""
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / '03_실습코드'))

from hand_local_features import transform
from normalize_mediapipe177_pilot import normalize
from resample_xy30_pilot import select_frames
from train_aihub_knn import predict, metrics
from record_webcam_clip import recording_fps


class FeatureInvariants(unittest.TestCase):
    def test_shoulder_normalization_round_trip_and_missing_mask(self):
        points = np.full((2, 59, 3), .5, dtype=np.float32)
        points[:, 53, 0], points[:, 54, 0] = .4, .6
        valid = np.ones((2, 59), dtype=bool)
        valid[1, 0] = False
        points[1, 0] = np.nan
        result, maximum = normalize(points, valid, np.ones((2, 17)), 640, 480)
        self.assertLess(maximum, .02)
        self.assertTrue(np.isnan(result['normalized_xy'][1, 0]).all())
        self.assertFalse(result['joint_mask'][1, 0])
        np.testing.assert_allclose(result['normalized_xy'][:, [53, 54], 0], [[-.5, .5]] * 2)

    def test_resampling_preserves_endpoint_and_source_time(self):
        xy = np.zeros((5, 59, 2), dtype=np.float32)
        data = dict(normalized_xy=xy, joint_mask=np.ones((5, 59), dtype=bool),
                    normalizable_frame=np.ones(5, dtype=bool),
                    word_interval_mask=np.ones(5, dtype=bool),
                    source_frame_indices=np.arange(10, 15),
                    timestamps_seconds=np.arange(5) * .1)
        sampled, rows = select_frames(data)
        self.assertEqual(sampled['normalized_xy'].shape, (30, 59, 2))
        self.assertEqual(sampled['source_frame_indices'][0], 10)
        self.assertEqual(sampled['source_frame_indices'][-1], 14)
        self.assertTrue(np.all(np.diff(sampled['timestamps_seconds']) >= 0))
        np.testing.assert_array_equal(rows, np.arange(5))

    def test_resampling_rejects_disconnected_word_interval(self):
        data = dict(normalized_xy=np.zeros((3, 59, 2)),
                    joint_mask=np.ones((3, 59), dtype=bool),
                    normalizable_frame=np.ones(3, dtype=bool),
                    word_interval_mask=np.array([True, False, True]),
                    source_frame_indices=np.arange(3), timestamps_seconds=np.arange(3) * .1)
        with self.assertRaises(ValueError):
            select_frames(data)

    def test_relative_hand_transform_and_wrist_feature_width(self):
        x = np.zeros((30, 177), dtype=np.float32)
        x[:, 118:] = 1
        xy = x[:, :118].reshape(30, 59, 2)
        xy[:, 0] = [2, 3]
        xy[:, 1] = [3, 5]
        y = transform(x, 'local_hands_keep_pose_add_wrists')
        self.assertEqual(y.shape, (30, 183))
        np.testing.assert_array_equal(y[0, :4], [0, 0, 1, 2])
        np.testing.assert_array_equal(x[0, :2], [2, 3])

    def test_invalid_availability_mask_is_rejected(self):
        x = np.zeros((30, 177), dtype=np.float32)
        x[0, 118] = .5
        with self.assertRaises(ValueError):
            transform(x, 'original')

    def test_knn_tie_and_metrics_have_deterministic_results(self):
        guess, vote = predict(np.array([[-1.], [1.]]), np.array([1, 0]), np.array([[0.]]), 2, 2)
        self.assertEqual(guess.tolist(), [0])
        self.assertEqual(vote.tolist(), [.5])
        result = metrics(np.array([0, 1]), np.array([0, 0]), ['a', 'b'])
        self.assertEqual(result['confusion_matrix_rows_actual_columns_predicted'], [[1, 0], [1, 0]])
        self.assertEqual(result['accuracy'], .5)

    def test_capture_fps_uses_elapsed_timestamps(self):
        self.assertAlmostEqual(recording_fps([0., .1, .2]), 10.)
        with self.assertRaises(ValueError):
            recording_fps([0., 0.])


if __name__ == '__main__':
    unittest.main()
