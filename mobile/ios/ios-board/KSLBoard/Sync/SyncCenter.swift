import Foundation
import Observation

/// 서버로 올리는 좌표 묶음 한 건. KSLSign의 Sample과 같은 키(train_gru.py가 읽는 클립 형식)에 몇 가지를 더했다.
/// JSON 키는 snake_case, frames의 null은 NaN(안 잡힌 점)
struct SyncSample: Codable, Sendable {
    var id: String
    var created: String
    var person: String          // 익명 사용자 번호 (재학습 때 사람별로 나누는 데 쓴다)
    var label: String           // 따라 하기: 목표 낱말. 번역: 사용자가 고른 낱말
    var feedback: String        // "practice"(따라 하기의 목표 낱말. 사람이 확인한 것이 아니다) / "confirmed" / "corrected"
    var predicted: String       // 모델의 1등 낱말
    var classes: [String]
    var probabilities: [Float]
    var model: String
    var preprocessVersion: String
    var mode: String            // "auto" / "button"
    var camera: String          // "front" / "back"
    var aspect: Double
    var start: Double
    var end: Double
    var times: [Double]
    var frames: [[Float?]]      // 프레임마다 177개
    var device: String
    var appVersion: String
    var source: String          // "kslboard-practice" / "kslboard-translate"
    var outcome: String         // 인식 결과 기록의 outcome과 같은 값
    var mirrored: Bool          // 좌우를 뒤집어 판정했는지 (왼손으로 한 동작). frames는 뒤집지 않은 원래 좌표다
    var readingId: String
}

/// 학습 기록과 좌표 묶음을 만들어 Outbox에 넣는 곳. 화면과 모델은 여기만 부른다
@Observable
@MainActor
final class SyncCenter {
    static let shared = SyncCenter()

    /// 화면을 그림으로 뽑는 Mac 도구에서는 아무것도 쌓지 않는다
    static let isOff: Bool = {
        #if os(iOS)
        return ProcessInfo.processInfo.arguments.contains("-noSync")
        #else
        return true
        #endif
    }()

    let config = ServerConfig.load()
    private(set) var stats = Outbox.Stats()
    /// 처음 켰을 때 데이터 사용에 동의했는지. 동의해야 앱을 쓸 수 있다.
    /// 학습 기록과 수어 동작의 좌표는 고르는 것이 아니라 항상 보낸다 (대표 결정, 2026-11-23). 영상과 이름은 보내지 않는다
    private(set) var agreed = UserDefaults.standard.bool(forKey: "sync.agreed")

    @ObservationIgnored var modelVersion = ""
    @ObservationIgnored var preprocessVersion = ""
    @ObservationIgnored var classes: [String] = []

    let userID: String
    @ObservationIgnored private let sessionID = UUID().uuidString.lowercased()
    @ObservationIgnored private let outbox: Outbox
    @ObservationIgnored private var seq = UserDefaults.standard.integer(forKey: "sync.seq")
    @ObservationIgnored private var soon: Task<Void, Never>?

    /// 방금 읽은 구간들. 나중에 좌표 묶음으로 만들 수 있게 잠깐 들고 있는다 (보내기 전에는 폰 밖으로 나가지 않는다)
    private struct Kept {
        let reading: Reading
        let clip: Clip
        let aspect: Double
        let mode: String
        let camera: String
    }
    @ObservationIgnored private var kept: [UUID: Kept] = [:]
    @ObservationIgnored private var order: [UUID] = []

    private init() {
        if let saved = UserDefaults.standard.string(forKey: "sync.user") {
            userID = saved
        } else {
            userID = UUID().uuidString.lowercased()
            UserDefaults.standard.set(userID, forKey: "sync.user")
        }
        outbox = Outbox(config: config)
        guard !Self.isOff else { return }
        Task {
            await outbox.observe { stats in
                Task { @MainActor in SyncCenter.shared.stats = stats }
            }
            // 서버가 받지 않아 치워 둔 것은 하루에 한 번만 다시 줄에 세운다 (서버가 그사이 형식을 고쳤을 수 있다).
            // 켤 때마다 다시 보내면 서버에 같은 400이 계속 쌓인다
            let last = UserDefaults.standard.double(forKey: "sync.requeuedAt2")
            if Date().timeIntervalSince1970 - last > 24 * 3600 {
                UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: "sync.requeuedAt2")
                await outbox.requeueRejected()
            }
            await outbox.flush()
        }
        // 보내기는 사용자가 누르는 것이 아니라 앱이 알아서 한다. 기록이 생기면 곧 보내고,
        // 못 보낸 것이 남아 있으면 30초마다 다시 보낸다 (대표 결정, 2026-11-23)
        Task { [outbox] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(Self.resendEvery))
                await outbox.flush()
            }
        }
    }

    /// 못 보낸 것을 다시 보내는 간격(초)
    static let resendEvery: Double = 30

    // MARK: 동의

    func agree() {
        agreed = true
        UserDefaults.standard.set(true, forKey: "sync.agreed")
    }

    // MARK: 기록

    func log(_ kind: SyncEvent.Kind, _ fill: (inout SyncEvent) -> Void = { _ in }) {
        guard !Self.isOff, agreed else { return }
        var event = SyncEvent(kind)
        seq += 1
        UserDefaults.standard.set(seq, forKey: "sync.seq")
        event.seq = seq
        event.eventTime = SyncEvent.timestamp()
        event.userId = userID
        event.sessionId = sessionID
        event.appVersion = AppInfo.version
        event.modelVersion = modelVersion
        event.device = AppInfo.device
        fill(&event)
        guard let data = try? SyncEvent.encoder.encode(event) else { return }
        let number = seq, id = event.eventId
        Task {
            await outbox.add(event: data, seq: number, id: id)
            flushSoon()
        }
    }

    /// 인식 결과 한 건의 공통 내용을 채운다
    func fill(_ event: inout SyncEvent, from reading: Reading, target: String? = nil) {
        event.readingId = reading.id.uuidString.lowercased()
        event.predictedWord = reading.top.word
        event.confidence = Double(reading.top.probability)
        event.probabilities = Dictionary(uniqueKeysWithValues: reading.ranking.map { ($0.word, Double($0.probability)) })
        event.durationMs = Int((reading.seconds * 1000).rounded())
        event.handMissingRatio = reading.handMissing
        if let target { event.targetProbability = Double(reading.probability(of: target)) }
    }

    // MARK: 좌표 묶음

    func remember(_ reading: Reading, clip: Clip, aspect: Double, mode: String, camera: String) {
        guard !Self.isOff else { return }
        kept[reading.id] = Kept(reading: reading, clip: clip, aspect: aspect, mode: mode, camera: camera)
        order.append(reading.id)
        while order.count > 30 { kept[order.removeFirst()] = nil }
    }

    /// 읽은 구간을 좌표 묶음으로 쌓는다. 구간이 남아 있지 않으면 nil.
    /// 같은 읽기는 같은 번호를 쓰므로, 정답을 다시 고르면 서버에서 같은 묶음을 덮어쓴다
    @discardableResult
    func saveSample(for readingID: UUID, label: String, feedback: String, source: String, outcome: String) -> String? {
        guard !Self.isOff, agreed, let one = kept[readingID] else { return nil }
        let id = readingID.uuidString.lowercased()
        let sample = SyncSample(
            id: id, created: SyncEvent.timestamp(), person: userID, label: label, feedback: feedback,
            predicted: one.reading.top.word, classes: classes, probabilities: classes.map { one.reading.probability(of: $0) },
            model: modelVersion, preprocessVersion: preprocessVersion, mode: one.mode, camera: one.camera, aspect: one.aspect,
            start: one.clip.start, end: one.clip.end, times: one.clip.times,
            frames: one.clip.frames.map { $0.map { $0.isNaN ? nil : $0 } },
            device: AppInfo.device, appVersion: AppInfo.version, source: source, outcome: outcome, mirrored: one.reading.mirrored, readingId: id)
        guard let data = try? SyncEvent.encoder.encode(sample) else { return nil }
        Task {
            await outbox.add(sample: data, id: id)
            flushSoon()
        }
        return id
    }

    // MARK: 보내기

    /// 조금 모았다가 보낸다 (한 번 따라 할 때 기록이 서너 건 연달아 생긴다)
    private func flushSoon() {
        soon?.cancel()
        soon = Task {
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }
            await outbox.flush()
        }
    }

    func flushNow() {
        guard !Self.isOff else { return }
        Task { await outbox.flush() }
    }
}
