import CoreVideo
import MediaPipeTasksVision
import UIKit

/// MediaPipe Tasks로 손(최대 4개)과 Pose lite(최대 2명)를 찾는다. VIDEO 모드라 시각이 늘어나는 순서로 불러야 한다.
/// 뒤 사람 손까지 잡은 뒤 FrameBuilder에서 앞사람 손만 남긴다.
final class LandmarkDetector {
    private let hands: HandLandmarker
    private let poses: PoseLandmarker
    private var lastMs = -1

    init(bundle: Bundle = .main) throws {
        guard let handPath = bundle.path(forResource: "hand_landmarker", ofType: "task") else {
            throw SignError.modelMissing("hand_landmarker.task")
        }
        guard let posePath = bundle.path(forResource: "pose_landmarker_lite", ofType: "task") else {
            throw SignError.modelMissing("pose_landmarker_lite.task")
        }
        let handOptions = HandLandmarkerOptions()
        handOptions.baseOptions.modelAssetPath = handPath
        handOptions.runningMode = .video
        handOptions.numHands = 4
        handOptions.minHandDetectionConfidence = 0.5
        handOptions.minHandPresenceConfidence = 0.5
        handOptions.minTrackingConfidence = 0.5
        hands = try HandLandmarker(options: handOptions)

        let poseOptions = PoseLandmarkerOptions()
        poseOptions.baseOptions.modelAssetPath = posePath
        poseOptions.runningMode = .video
        poseOptions.numPoses = 2
        poses = try PoseLandmarker(options: poseOptions)
    }

    /// pixelBuffer는 이미 세로로 돌리고 좌우 반전한 BGRA 화면이어야 한다. 시각이 앞으로 가지 않으면 nil
    func detect(_ pixelBuffer: CVPixelBuffer, timestampMs: Int) throws -> (hands: [HandDetection], poses: [PoseDetection])? {
        guard timestampMs > lastMs else { return nil }
        lastMs = timestampMs
        let image = try MPImage(pixelBuffer: pixelBuffer, orientation: .up)
        let h = try hands.detect(videoFrame: image, timestampInMilliseconds: timestampMs)
        let p = try poses.detect(videoFrame: image, timestampInMilliseconds: timestampMs)
        let handList = zip(h.landmarks, h.handedness).compactMap { points, categories -> HandDetection? in
            guard let top = categories.first, let label = top.categoryName else { return nil }
            return HandDetection(label: label, score: top.score, points: points.map(Self.landmark))
        }
        return (handList, p.landmarks.map { PoseDetection(points: $0.map(Self.landmark)) })
    }

    private static func landmark(_ p: NormalizedLandmark) -> Landmark {
        Landmark(x: p.x, y: p.y, z: p.z)
    }
}
