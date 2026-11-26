import Foundation

struct HandDetection {
    var label: String     // MediaPipe handedness "Right" / "Left" (그대로 쓴다)
    var score: Float
    var points: [Landmark]  // 21점
}

struct PoseDetection {
    var points: [Landmark]  // 33점
}

struct FrameResult {
    var values: [Float]               // 177개, 안 잡힌 점은 NaN
    var person: PoseDetection?        // 쓰기로 고른 사람 (없으면 nil)
    var shoulderWidth: Double?        // 그 사람 어깨 폭, 화면 너비 대비
    var hands: [Int: HandDetection]   // 슬롯 시작 번호(0 또는 21) → 넣은 손
}

/// MediaPipe 결과를 학습 규격의 177개 값으로 만든다.
/// 뒤 사람 거르기는 Windows pipeline/live_test.py의 select, 177값 조립은 recording/record.py의 to_frame과 같다.
/// - 사람은 2명, 손은 4개까지 잡은 결과를 받는다
/// - 어깨 폭이 화면 너비의 0.10보다 작은 사람은 버리고, 남은 사람 중 어깨 폭이 가장 큰 한 명만 쓴다. 사람이 없으면 손도 버린다
/// - 손은 그 사람의 Pose 손목(15, 16번)에서 어깨 폭 × 1.0 안에 있는 것만 쓴다
enum FrameBuilder {
    static let minShoulderWidth = 0.10
    static let handReach = 1.0

    /// 두 점 사이 픽셀 거리 (live_test.py와 같이 float64로 계산)
    static func pixelDistance(_ a: Landmark, _ b: Landmark, width: Int, height: Int) -> Double {
        hypot((Double(a.x) - Double(b.x)) * Double(width), (Double(a.y) - Double(b.y)) * Double(height))
    }

    /// 어깨 폭(화면 너비 대비). 가까운 사람일수록 크다
    static func shoulderWidth(_ pose: PoseDetection, width: Int, height: Int) -> Double {
        pixelDistance(pose.points[SignSpec.leftShoulder], pose.points[SignSpec.rightShoulder], width: width, height: height) / Double(width)
    }

    static func build(hands: [HandDetection], poses: [PoseDetection], width: Int, height: Int) -> FrameResult {
        var values = [Float](repeating: .nan, count: SignSpec.numValues)
        let front = poses
            .map { ($0, shoulderWidth($0, width: width, height: height)) }
            .filter { $0.1 >= minShoulderWidth }
            .max { $0.1 < $1.1 }
        guard let (person, size) = front else {
            return FrameResult(values: values, person: nil, shoulderWidth: nil, hands: [:])
        }
        for (i, p) in person.points.prefix(SignSpec.posePoints).enumerated() {
            put(p, at: SignSpec.poseStart + i, into: &values)
        }

        let reach = handReach * size * Double(width)
        let wrists = [person.points[SignSpec.leftWrist], person.points[SignSpec.rightWrist]]
        var slots: [Int: HandDetection] = [:]
        for hand in hands {
            let distance = wrists.map { pixelDistance(hand.points[0], $0, width: width, height: height) }.min()!
            guard distance <= reach else { continue }
            let start: Int
            switch hand.label {
            case "Right": start = SignSpec.rightLabelStart
            case "Left": start = SignSpec.leftLabelStart
            default: continue
            }
            // 같은 라벨의 손이 두 번 잡히면 점수가 높은 쪽만 쓴다 (같으면 먼저 나온 쪽)
            if let kept = slots[start], kept.score >= hand.score { continue }
            slots[start] = hand
        }
        for (start, hand) in slots {
            for (i, p) in hand.points.prefix(SignSpec.handPoints).enumerated() {
                put(p, at: start + i, into: &values)
            }
        }
        return FrameResult(values: values, person: person, shoulderWidth: size, hands: slots)
    }

    private static func put(_ p: Landmark, at point: Int, into values: inout [Float]) {
        values[point * 3] = p.x
        values[point * 3 + 1] = p.y
        values[point * 3 + 2] = p.z
    }
}
