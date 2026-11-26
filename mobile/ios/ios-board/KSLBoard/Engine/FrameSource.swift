import Foundation

enum SourceError: Error {
    case cameraDenied
}

/// 프레임을 내는 곳. 실제 기기에서는 카메라(CameraSource), 카메라가 없는 곳에서는 본보기 좌표(DemoSource)
@MainActor
protocol FrameSource: AnyObject {
    /// (177개 값과 고른 사람·손, 초 단위 시각, 화면 너비, 화면 높이)
    var onFrame: ((FrameResult, Double, Int, Int) -> Void)? { get set }
    /// onFrame의 시각과 같은 시계로 잰 지금
    var now: Double { get }
    var isFront: Bool { get }
    var zoomLabels: [String] { get }
    var zoomIndex: Int { get }
    func prepare() async throws
    func start()
    func stop()
    func useFront(_ front: Bool) throws
    func setZoom(_ index: Int)
    /// 읽기를 시작할 때 불린다. 카메라는 할 일이 없고, 본보기 좌표는 동작의 처음으로 돌아간다
    func readingWillStart()
}

extension FrameSource {
    func readingWillStart() {}
}

/// 카메라 대신 앱에 들어 있는 본보기 좌표(example_thanks_T01, 웹캠으로 찍은 '감사')를 되풀이해 보낸다.
/// 시뮬레이터와 Mac에서 화면을 확인할 때 쓴다. 전처리와 판정은 실제와 같은 코드를 지난다
@MainActor
final class DemoSource: FrameSource {
    var onFrame: ((FrameResult, Double, Int, Int) -> Void)?
    private(set) var now = 0.0
    let isFront = true
    let zoomLabels: [String] = []
    let zoomIndex = 0

    private var frames: [[Float]] = []
    private var index = 0
    /// 동작이 시작되는 프레임 (읽기를 시작하면 여기로 돌아간다)
    private var signStart = 0
    private var timer: Timer?
    private let width = 1280
    private var height = 720
    private let timed: Bool

    /// timed가 false면 step()을 직접 불러 한 프레임씩 넘긴다
    init(timed: Bool = true) {
        self.timed = timed
    }

    func prepare() async throws {
        guard frames.isEmpty else { return }
        let sample = try ExampleSample.load()
        frames = sample.frames.map { $0.map { $0 ?? .nan } }
        signStart = max(0, (sample.times.firstIndex { $0 >= sample.start } ?? 0) - 1)
        height = Int((Double(width) / Double(sample.aspect)).rounded())
    }

    func start() {
        guard timed, timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 1 / SignSpec.targetFPS, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.step() }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    func useFront(_ front: Bool) throws {}
    func setZoom(_ index: Int) {}

    /// 읽기를 시작하면 동작의 처음부터 보여 준다. 그래야 단추를 언제 눌러도 같은 동작을 읽는다
    func readingWillStart() {
        index = signStart
    }

    /// 다음 프레임 하나를 보낸다
    func step() {
        guard !frames.isEmpty else { return }
        let values = frames[index]
        index = (index + 1) % frames.count
        now += 1 / SignSpec.targetFPS
        onFrame?(Self.result(values, width: width, height: height), now, width, height)
    }

    /// 저장된 177개 값을 카메라에서 막 나온 결과처럼 만든다
    static func result(_ values: [Float], width: Int, height: Int) -> FrameResult {
        func landmark(_ i: Int) -> Landmark {
            Landmark(x: values[i * 3], y: values[i * 3 + 1], z: values[i * 3 + 2])
        }
        guard !values[(SignSpec.poseStart + SignSpec.leftShoulder) * 3].isNaN else {
            return FrameResult(values: values, person: nil, shoulderWidth: nil, hands: [:])
        }
        var points = (0..<SignSpec.posePoints).map { landmark(SignSpec.poseStart + $0) }
        points += Array(repeating: Landmark(x: 0, y: 0, z: 0), count: 33 - points.count)
        let person = PoseDetection(points: points)
        var hands: [Int: HandDetection] = [:]
        for (start, label) in [(SignSpec.rightLabelStart, "Right"), (SignSpec.leftLabelStart, "Left")]
        where !values[start * 3].isNaN {
            hands[start] = HandDetection(label: label, score: 1,
                                         points: (0..<SignSpec.handPoints).map { landmark(start + $0) })
        }
        return FrameResult(values: values, person: person,
                           shoulderWidth: FrameBuilder.shoulderWidth(person, width: width, height: height), hands: hands)
    }
}
