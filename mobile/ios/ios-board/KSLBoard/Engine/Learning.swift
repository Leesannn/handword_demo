import CoreGraphics
import Foundation
import Observation

/// 낱말마다 앱이 알아본 횟수. 세 번 알아보면 익힌 낱말이다
@Observable
@MainActor
final class ProgressStore {
    static let goal = 3
    private(set) var marks: [String: Int]
    @ObservationIgnored private let saves: Bool

    init() {
        marks = (UserDefaults.standard.dictionary(forKey: "marks") as? [String: Int]) ?? [:]
        saves = true
    }

    /// 저장하지 않는 것 (화면을 뽑아 볼 때)
    init(marks: [String: Int]) {
        self.marks = marks
        saves = false
    }

    func count(_ word: String) -> Int {
        min(Self.goal, marks[word, default: 0])
    }

    func add(_ word: String) {
        marks[word] = min(Self.goal, count(word) + 1)
        if saves { UserDefaults.standard.set(marks, forKey: "marks") }
    }

    func learned(among words: [String]) -> Int {
        words.filter { count($0) >= Self.goal }.count
    }

    static func text(_ count: Int) -> String {
        switch count {
        case 0: "아직 알아본 적이 없어요"
        case 1: "한 번 알아봤어요. 두 번 더 하면 익힘"
        case 2: "두 번 알아봤어요. 한 번 더 하면 익힘"
        default: "세 번 알아봐서 익힌 낱말이에요"
        }
    }
}

/// 낱말의 본보기 동작.
/// - 감사: example_thanks_T01 (팀원이 웹캠으로 녹화)
/// - 그 밖: `demo_*.json` (KSLSign 앱으로 아이폰에서 녹화해 "맞아요"로 확인했고, 모델도 같은 낱말로 읽은 샘플)
struct Demo {
    let poses: [Pose2D]
    let aspect: CGFloat
    /// 사람을 무대 가운데에 맞추는 데 쓰는 평균 어깨 중심과 어깨 폭
    let center: CGPoint
    let shoulder: CGFloat
    /// 3D 사람 모형으로 옮긴 동작. 깊이를 어림하고 빈 프레임을 채워 다듬은 것이다 (AvatarMotion)
    let motion: AvatarMotion?

    /// 앱에 넣은 본보기 파일 하나 (null은 NaN)
    private struct File: Decodable {
        let word: String
        let frames: [[Float?]]
        let times: [Float]
        let aspect: Float
        let start: Float
        let end: Float
        /// 깊이까지 잰 3D 관절(AIHub). 있으면 사람 모형은 이것으로 움직인다
        let avatar: [AvatarMotion.Joints]?
        /// "estimated"면 카메라 한 대의 영상에서 어림한 3D다 (직접 찍은 영상). 없으면 여러 각도로 잰 3D다 (AIHub)
        let depth: String?
    }

    /// 낱말 → 본보기
    static let library: [String: Demo] = {
        var all: [String: Demo] = [:]
        // 감사: 본보기 파일이 가리키는 낱말(기대 확률이 가장 높은 라벨)에 붙인다
        if let sample = try? ExampleSample.load(),
           let best = sample.expected.indices.max(by: { sample.expected[$0] < sample.expected[$1] }) {
            all[sample.classes[best]] = make(frames: sample.frames, times: sample.times, aspect: sample.aspect, start: sample.start, end: sample.end)
        }
        for url in Bundle.main.urls(forResourcesWithExtension: "json", subdirectory: nil) ?? []
        where url.lastPathComponent.hasPrefix("demo_") {
            guard let data = try? Data(contentsOf: url), let file = try? JSONDecoder().decode(File.self, from: data) else { continue }
            all[file.word] = make(frames: file.frames, times: file.times, aspect: file.aspect, start: file.start, end: file.end, joints: file.avatar,
                                  estimated: file.depth == "estimated")
        }
        return all
    }()

    private static func make(frames: [[Float?]], times: [Float], aspect: Float, start: Float, end: Float,
                             joints: [AvatarMotion.Joints]? = nil, estimated: Bool = false) -> Demo? {
        let values = frames.map { $0.map { $0 ?? Float.nan } }
        let inside = times.indices.filter { times[$0] >= start && times[$0] <= end }
        guard let first = inside.first, let last = inside.last else { return nil }
        let poses = values[first...last].map { Pose2D(values: $0) }
        let shoulders = poses.compactMap { $0.shoulders(aspect: CGFloat(aspect)) }
        guard !shoulders.isEmpty else { return nil }
        let n = CGFloat(shoulders.count)
        let center = CGPoint(x: shoulders.map(\.center.x).reduce(0, +) / n, y: shoulders.map(\.center.y).reduce(0, +) / n)
        let width = shoulders.map(\.width).reduce(0, +) / n
        let motion = joints.flatMap { $0.count == frames.count ? AvatarMotion(joints: $0, window: first..<(last + 1), screen: estimated ? (values, aspect) : nil) : nil }
            ?? AvatarMotion(values: values, window: first..<(last + 1), aspect: aspect)
        return Demo(poses: poses, aspect: CGFloat(aspect), center: center, shoulder: width, motion: motion)
    }

    /// 동작 순서로 보여 줄 프레임 넷 (구간을 고르게 나눈 자리)
    var keyFrames: [Int] {
        [0.12, 0.38, 0.64, 0.9].map { Int((Double(poses.count - 1) * $0).rounded()) }
    }
}
