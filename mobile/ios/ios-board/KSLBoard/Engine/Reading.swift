import CoreGraphics
import Foundation

/// 그림에 쓰는 한 프레임. 좌표는 좌우 반전한 화면 기준 0~1 (학습 규격 그대로)
struct Pose2D: Equatable {
    var body: [CGPoint?]     // Pose 0~16
    var right: [CGPoint]?    // 수어하는 사람의 오른손 21점
    var left: [CGPoint]?     // 왼손 21점

    /// 177개 값에서 만든다.
    /// 좌우 반전한 화면에서는 MediaPipe "Left" 라벨(21~41번)이 실제 오른손이고
    /// "Right" 라벨(0~20번)이 실제 왼손이다 (model_bundle/먼저읽기.txt).
    /// 기기에서 오른손을 들었을 때 노란 손이 움직이지 않으면 아래 두 줄의 슬롯을 서로 바꾼다
    init(values: [Float]) {
        func point(_ i: Int) -> CGPoint? {
            let x = values[i * 3], y = values[i * 3 + 1]
            return x.isNaN || y.isNaN ? nil : CGPoint(x: CGFloat(x), y: CGFloat(y))
        }
        func hand(_ start: Int) -> [CGPoint]? {
            let points = (0..<SignSpec.handPoints).compactMap { point(start + $0) }
            return points.count == SignSpec.handPoints ? points : nil
        }
        body = (0..<SignSpec.posePoints).map { point(SignSpec.poseStart + $0) }
        right = hand(SignSpec.leftLabelStart)
        left = hand(SignSpec.rightLabelStart)
    }

    /// 어깨 중심과 어깨 폭 (화면 너비 대비. 세로 차이는 화면비로 너비 단위에 맞춘다)
    func shoulders(aspect: CGFloat) -> (center: CGPoint, width: CGFloat)? {
        guard let a = body[SignSpec.leftShoulder], let b = body[SignSpec.rightShoulder] else { return nil }
        let width = hypot(a.x - b.x, (a.y - b.y) / aspect)
        return (CGPoint(x: (a.x + b.x) / 2, y: (a.y + b.y) / 2), width)
    }
}

/// 읽는 동안 손목이 지나간 길. 손이 안 보인 구간에서는 끊는다 (본 만큼만 그린다)
struct Trail: Equatable {
    var right: [[CGPoint]] = []
    var left: [[CGPoint]] = []
    private var rightOpen = false
    private var leftOpen = false

    mutating func add(_ pose: Pose2D) {
        Self.extend(&right, &rightOpen, pose.right?.first)
        Self.extend(&left, &leftOpen, pose.left?.first)
    }

    private static func extend(_ runs: inout [[CGPoint]], _ open: inout Bool, _ point: CGPoint?) {
        guard let point else {
            open = false
            return
        }
        if open {
            runs[runs.count - 1].append(point)
        } else {
            runs.append([point])
            open = true
        }
    }

    init() {}

    /// 본보기처럼 이미 다 있는 프레임에서 한꺼번에 만든다
    init(poses: ArraySlice<Pose2D>) {
        for pose in poses { add(pose) }
    }
}

/// 한 번 읽은 결과 (동작 구간 하나를 모델이 판정한 것)
struct Reading: Identifiable, Equatable {
    struct Candidate: Identifiable, Equatable {
        let word: String
        let probability: Float
        var id: String { word }
    }

    enum Outcome: Equatable {
        case word(String, sure: Bool)
        case unknown        // 모델이 '기타'(목표가 아닌 동작)로 봤다
        case handsUnseen    // 동작 손이 절반 넘게 안 잡혔다
    }

    /// 모델의 '목표가 아닌 동작' 라벨 (model.json classes의 첫 항목)
    static let other = "기타"
    /// 화면에 '확실하지 않아요'로 적는 임시 기준.
    /// 팀이 신뢰도 기준을 정하지 않았다(model.json confidence_threshold: null). 정해지면 그 값으로 바꾼다
    static let sureAt: Float = 0.6

    let id = UUID()
    let seconds: Double
    let ranking: [Candidate]     // 확률 높은 순 ('기타' 포함)
    let handMissing: Double      // 동작 손이 안 잡힌 프레임 비율
    let rightSeen: [Bool]        // 구간 안 프레임마다 오른손이 보였는지
    let leftSeen: [Bool]
    let bodySeen: [Bool]
    /// 좌우를 뒤집어 판정한 결과인지 (왼손으로 한 동작)
    let mirrored: Bool

    init(clip: Clip, classes: [String], probabilities: [Float], mirrored: Bool = false) {
        self.mirrored = mirrored
        let window = clip.window
        func seen(_ point: Int) -> [Bool] { window.map { !$0[point * 3].isNaN } }
        seconds = min(clip.duration, SignSpec.maxDuration)
        ranking = zip(classes, probabilities).map { Candidate(word: $0, probability: $1) }
            .sorted { $0.probability > $1.probability }
        handMissing = Preprocess.mainHandMissingRatio(window)
        rightSeen = seen(SignSpec.leftLabelStart)
        leftSeen = seen(SignSpec.rightLabelStart)
        bodySeen = seen(SignSpec.poseStart + SignSpec.leftShoulder)
    }

    var top: Candidate { ranking[0] }

    var outcome: Outcome {
        if handMissing > SignSpec.missingWarn { return .handsUnseen }
        if top.word == Self.other { return .unknown }
        return .word(top.word, sure: top.probability >= Self.sureAt)
    }

    /// 1등 다음으로 그럴듯한 낱말 (많아야 둘)
    var alternatives: [String] {
        ranking.dropFirst().filter { $0.word != Self.other && $0.probability >= 0.05 }.prefix(2).map(\.word)
    }

    func probability(of word: String) -> Float {
        ranking.first { $0.word == word }?.probability ?? 0
    }

    static func ratio(_ seen: [Bool]) -> Double {
        seen.isEmpty ? 0 : Double(seen.filter { $0 }.count) / Double(seen.count)
    }
}

/// 번역 화면에 적힌 낱말 하나
struct Token: Identifiable, Equatable {
    let id: UUID
    var word: String
    var sure: Bool
    var corrected = false
    let reading: Reading
}

extension Double {
    /// "1.8초"
    var secondsText: String { String(format: "%.1f초", self) }
}

extension Float {
    /// "87%"
    var percentText: String { "\(Int((self * 100).rounded()))%" }
}

extension String {
    /// 받침에 따라 '로' 또는 '으로'를 붙인다 ("감사로", "집으로")
    var withRo: String {
        guard let last = unicodeScalars.last, (0xAC00...0xD7A3).contains(last.value) else { return self + "(으)로" }
        let final = (last.value - 0xAC00) % 28
        return self + (final == 0 || final == 8 ? "로" : "으로")
    }
}
