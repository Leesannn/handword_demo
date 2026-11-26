import Foundation

/// 학습 때와 같은 좌표 규격(model_bundle/먼저읽기.txt). 하나라도 다르면 엉뚱한 판정이 나온다.
enum SignSpec {
    static let numPoints = 59
    static let numValues = numPoints * 3   // 프레임마다 177개 값 (점마다 x, y, z)
    static let numFrames = 30
    static let handPoints = 21
    /// MediaPipe가 "Right"로 표시한 손은 0~20번, "Left"는 21~41번. 라벨을 바꾸지 않고 그대로 넣는다
    static let rightLabelStart = 0
    static let leftLabelStart = 21
    /// Pose 0~16번 점은 42~58번
    static let poseStart = 42
    static let posePoints = 17
    static let leftShoulder = 11
    static let rightShoulder = 12
    static let leftWrist = 15
    static let rightWrist = 16

    static let targetFPS = 15.0
    /// 시작~끝이 이보다 짧으면 버리고, 이만큼 지나면 자동으로 끝내고 판정한다 (record.py MIN/MAX_SECONDS)
    static let minDuration = 0.5
    static let maxDuration = 3.0
    /// 동작 손이 이보다 많이 빠지면 판정이 손이 아니라 몸 자세에 기대므로 믿기 어렵다 (live_test.py MISSING_WARN, 표시만)
    static let missingWarn = 0.5
}

/// MediaPipe 정규화 좌표. x, y는 전체 화면 기준 0~1, z는 MediaPipe 값 그대로
struct Landmark: Equatable {
    var x: Float
    var y: Float
    var z: Float
}

enum SignError: LocalizedError {
    case modelMissing(String)
    case badModelMetadata
    case tooFewFrames

    var errorDescription: String? {
        switch self {
        case .modelMissing(let name): "앱 안에 \(name) 파일이 없습니다"
        case .badModelMetadata: "Core ML 모델에 라벨(classes) 정보가 없습니다"
        case .tooFewFrames: "구간 안 프레임이 2개 미만입니다"
        }
    }
}
