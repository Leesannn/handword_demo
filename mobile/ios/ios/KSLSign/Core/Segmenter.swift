import Foundation

/// train_gru.py가 읽는 클립 형식(frames, times, start, end). 동작 앞 대기 구간까지 담고 [start, end]가 동작 구간이다
struct Clip {
    var frames: [[Float]]
    var times: [Double]   // 클립 첫 프레임 기준 초
    var start: Double
    var end: Double

    var duration: Double { end - start }
    /// 동작 구간 안 프레임 (판정에 쓰는 프레임)
    var window: [[Float]] { zip(frames, times).filter { $0.1 >= start && $0.1 <= end }.map(\.0) }
}

/// 프레임을 계속 받아 동작 구간을 정한다.
/// - 버튼: '시작'·'끝'을 누른 시각으로 정하고, 3초가 되면 자동으로 끝낸다 (live_test.py와 같음)
/// - 자동: 앞사람 손이 2프레임 연속 잡히면 시작, 0.4초 동안 손이 안 잡히면 마지막으로 잡힌 때가 끝이다.
///   3초가 되면 거기서 끊고, 손을 내렸다 다시 올려야 다음 동작을 시작한다.
///   학습 데이터와 구간 자르는 방식이 달라 정확도는 따로 확인해야 한다
/// 어느 쪽이든 동작 앞 1초를 함께 담는다 (재학습 때 '기타' 대기 구간으로 쓸 수 있게)
final class Segmenter {
    enum Mode: String { case auto, button }

    enum Event {
        case started
        case clip(Clip)
        case tooShort(seconds: Double)
    }

    static let preRoll = 1.0
    static let handGap = 0.4
    static let framesToStart = 2

    var mode: Mode { didSet { reset() } }
    private(set) var isRecording = false
    private(set) var startTime = 0.0
    private var frames: [(time: Double, values: [Float])] = []
    private var lastHandTime = 0.0
    private var handRun: [Double] = []   // 자동: 손이 연속으로 잡힌 프레임 시각
    private var waitForHandsDown = false

    init(mode: Mode) {
        self.mode = mode
    }

    func reset() {
        isRecording = false
        frames = []
        handRun = []
        waitForHandsDown = false
    }

    /// 버튼 '시작'
    func start(at time: Double) {
        guard mode == .button, !isRecording else { return }
        isRecording = true
        startTime = time
    }

    /// 버튼 '끝'
    func stop(at time: Double) -> Event? {
        guard mode == .button, isRecording else { return nil }
        return finish(end: time)
    }

    /// 프레임 하나를 넣는다. hasHand: 앞사람 손이 하나라도 잡혔는지
    func add(time: Double, values: [Float], hasHand: Bool) -> Event? {
        frames.append((time, values))
        if !isRecording {
            // 다음 동작의 앞 1초를 남겨 둔다 (잘라 쓸 때 정확히 1초로 맞춘다)
            frames.removeAll { $0.time < time - Self.preRoll - 0.5 }
        }
        switch mode {
        case .button:
            guard isRecording else { return nil }
            return time - startTime >= SignSpec.maxDuration ? finish(end: time) : nil
        case .auto:
            if isRecording {
                if hasHand { lastHandTime = time }
                if time - startTime >= SignSpec.maxDuration {
                    waitForHandsDown = true
                    return finish(end: time)
                }
                return !hasHand && time - lastHandTime >= Self.handGap ? finish(end: lastHandTime) : nil
            }
            guard hasHand else {
                handRun = []
                waitForHandsDown = false
                return nil
            }
            guard !waitForHandsDown else { return nil }
            handRun.append(time)
            guard handRun.count >= Self.framesToStart else { return nil }
            isRecording = true
            startTime = handRun[0]
            lastHandTime = time
            return .started
        }
    }

    private func finish(end: Double) -> Event {
        isRecording = false
        handRun = []
        let kept = frames.filter { $0.time >= startTime - Self.preRoll }
        let t0 = kept.first?.time ?? startTime
        let clip = Clip(frames: kept.map(\.values), times: kept.map { $0.time - t0 }, start: startTime - t0, end: end - t0)
        if clip.duration < SignSpec.minDuration || clip.window.count < 2 {
            return .tooShort(seconds: clip.duration)
        }
        return .clip(clip)
    }
}
