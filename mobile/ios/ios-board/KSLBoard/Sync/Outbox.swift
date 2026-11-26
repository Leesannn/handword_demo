import Foundation

/// 보낼 것을 폰에 먼저 쌓아 두고 서버로 보내는 곳.
///
/// - 기록과 좌표 묶음은 파일 하나씩으로 저장한다. 앱을 껐다 켜도 남는다
/// - 서버가 받았다(2xx)고 답한 것만 지운다. 답을 못 받으면 그대로 두고 간격을 늘려 가며 다시 보낸다
/// - 그래서 같은 것이 두 번 갈 수 있다. 기록에는 event_id, 묶음에는 id가 있어서 서버가 걸러낸다 (at-least-once)
/// - 서버가 내용이 틀렸다(400, 413, 422)고 답한 것은 다시 보내도 소용없으므로 rejected 폴더로 옮긴다
actor Outbox {
    struct Stats: Sendable, Equatable {
        var pendingEvents = 0
        var pendingSamples = 0
        var sentEvents = 0
        var sentSamples = 0
        var rejected = 0
        var lastError: String?
        var lastSentAt: Date?
    }

    static let maxEvents = 5000
    static let maxSamples = 300

    private let config: ServerConfig
    private let folder: URL
    private let session: URLSession
    private let defaults: UserDefaults
    private var flushing = false
    private var delay: Double = 0
    private var retry: Task<Void, Never>?
    private var stats = Stats()
    private var onChange: (@Sendable (Stats) -> Void)?

    private var events: URL { folder.appending(path: "events", directoryHint: .isDirectory) }
    private var samples: URL { folder.appending(path: "samples", directoryHint: .isDirectory) }
    private var rejected: URL { folder.appending(path: "rejected", directoryHint: .isDirectory) }

    init(config: ServerConfig, folder: URL = URL.applicationSupportDirectory.appending(path: "sync", directoryHint: .isDirectory),
         defaults: UserDefaults = .standard) {
        self.config = config
        self.folder = folder
        self.defaults = defaults
        let settings = URLSessionConfiguration.ephemeral
        settings.timeoutIntervalForRequest = 15
        settings.timeoutIntervalForResource = 60
        session = URLSession(configuration: settings)
        stats.sentEvents = defaults.integer(forKey: "sync.sentEvents")
        stats.sentSamples = defaults.integer(forKey: "sync.sentSamples")
    }

    func observe(_ onChange: @escaping @Sendable (Stats) -> Void) {
        self.onChange = onChange
        report()
    }

    // MARK: 쌓기

    /// 기록 한 건. 파일 이름이 순번으로 시작해서 이름 순서가 곧 일어난 순서다
    func add(event data: Data, seq: Int, id: String) {
        write(data, to: events.appending(path: String(format: "%012d-%@.json", seq, id)))
        trim(events, keep: Self.maxEvents)
        report()
    }

    func add(sample data: Data, id: String) {
        write(data, to: samples.appending(path: "\(id).json"))
        trim(samples, keep: Self.maxSamples)
        report()
    }

    /// 아직 안 보낸 좌표 묶음을 지운다 (사용자가 좌표 보내기를 껐을 때)
    func dropSamples() {
        for url in files(samples) { try? FileManager.default.removeItem(at: url) }
        report()
    }

    /// 서버가 받지 않아 치워 둔 것을 다시 보낼 줄에 세운다 (서버가 형식을 고친 뒤에 쓴다)
    func requeueRejected() {
        for url in files(rejected) {
            let target = events.appending(path: url.lastPathComponent)
            try? FileManager.default.createDirectory(at: events, withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: target)
            if let fixed = Self.repaired(url) {
                try? fixed.write(to: target, options: .atomic)
                try? FileManager.default.removeItem(at: url)
            } else {
                try? FileManager.default.moveItem(at: url, to: target)
            }
        }
        report()
    }

    /// 2026-11-23 이전 버전이 만든 기록에는 규격서에 없는 항목이 붙어 있어서 서버가 400으로 거절했다
    /// (닫기·학습 완료의 attempt, 정답 선택의 duration_ms 등). 그 항목을 떼어 내 다시 보낼 수 있게 한다
    private static func repaired(_ url: URL) -> Data? {
        guard let data = try? Data(contentsOf: url),
              var event = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let kind = event["event_type"] as? String else { return nil }
        let extra: [String]
        switch kind {
        case "lesson_ended", "lesson_completed": extra = ["attempt"]
        case "answer_selected": extra = ["duration_ms", "hand_missing_ratio", "target_probability"]
        default: return nil
        }
        guard extra.contains(where: { event[$0] != nil }) else { return nil }
        extra.forEach { event[$0] = nil }
        return try? JSONSerialization.data(withJSONObject: event, options: [.sortedKeys, .withoutEscapingSlashes])
    }

    func current() -> Stats {
        count()
        return stats
    }

    // MARK: 보내기

    func flush() async {
        guard !flushing else { return }
        guard let eventsURL = config.eventsURL else {
            report()
            return
        }
        let samplesURL = config.samplesURL
        flushing = true
        retry?.cancel()
        defer { flushing = false }

        while true {
            let batch = Array(files(events).prefix(config.batchSize))
            if !batch.isEmpty {
                switch await post(Self.body(of: batch), to: eventsURL) {
                case .accepted(let code):
                    note(batch, code: code)
                    batch.forEach { try? FileManager.default.removeItem(at: $0) }
                    stats.sentEvents += batch.count
                    defaults.set(stats.sentEvents, forKey: "sync.sentEvents")
                    succeeded()
                    continue
                case .refused(let why):
                    stats.lastError = why
                    guard batch.count > 1 else {
                        reject(batch[0])
                        report()
                        continue
                    }
                    // 묶음에 틀린 기록이 하나라도 있으면 서버가 묶음 전체를 거절한다.
                    // 멀쩡한 기록까지 버려지지 않게 한 건씩 다시 보내 틀린 것만 가려낸다
                    for one in batch {
                        switch await post(Self.body(of: [one]), to: eventsURL) {
                        case .accepted(let code):
                            note([one], code: code)
                            try? FileManager.default.removeItem(at: one)
                            stats.sentEvents += 1
                            defaults.set(stats.sentEvents, forKey: "sync.sentEvents")
                        case .refused:
                            reject(one)
                        case .later(let later):
                            failed(later)
                            return
                        }
                    }
                    report()
                    continue
                case .later(let why):
                    failed(why)
                    return
                }
            }
            // 좌표 묶음을 받는 주소가 아직 없으면 쌓아 두기만 한다
            guard let samplesURL, let one = files(samples).first else { break }
            guard let body = try? Data(contentsOf: one) else {
                reject(one)
                continue
            }
            switch await post(body, to: samplesURL) {
            case .accepted:
                try? FileManager.default.removeItem(at: one)
                stats.sentSamples += 1
                defaults.set(stats.sentSamples, forKey: "sync.sentSamples")
                succeeded()
            case .refused(let why):
                reject(one)
                stats.lastError = why
                report()
            case .later(let why):
                failed(why)
                return
            }
        }
        report()
    }

    /// 서버가 받은 기록을 한 줄씩 적어 둔다 (sync/sent.log, 최근 500건).
    /// 서버·Kafka·DB에서 기록을 추적할 때 event_id를 여기서 찾는다. 케이블로 앱 저장소를 꺼내 읽는다
    private func note(_ batch: [URL], code: Int) {
        let log = folder.appending(path: "sent.log")
        var lines = ((try? String(contentsOf: log, encoding: .utf8)) ?? "").split(separator: "\n").map(String.init)
        let sentAt = SyncEvent.timestamp()
        for url in batch {
            guard let data = try? Data(contentsOf: url),
                  let event = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { continue }
            let entry: [String: Any] = [
                "sent_at": sentAt, "http": code, "event_id": event["event_id"] ?? "", "event_type": event["event_type"] ?? "",
                "event_time": event["event_time"] ?? "", "seq": event["seq"] ?? 0, "source": event["source"] ?? "",
                "word": event["word"] ?? "", "outcome": event["outcome"] ?? "",
            ]
            if let line = try? JSONSerialization.data(withJSONObject: entry, options: [.sortedKeys]),
               let text = String(data: line, encoding: .utf8) { lines.append(text) }
        }
        if lines.count > 500 { lines.removeFirst(lines.count - 500) }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? (lines.joined(separator: "\n") + "\n").write(to: log, atomically: true, encoding: .utf8)
    }

    /// 기록 파일들을 서버가 받는 묶음 모양으로 만든다
    private static func body(of batch: [URL]) -> Data {
        let bodies = batch.compactMap { try? Data(contentsOf: $0) }
        var body = Data("{\"sent_at\":\"\(SyncEvent.timestamp())\",\"count\":\(bodies.count),\"events\":[".utf8)
        for (i, one) in bodies.enumerated() {
            if i > 0 { body.append(UInt8(ascii: ",")) }
            body.append(one)
        }
        body.append(Data("]}".utf8))
        return body
    }

    private enum Reply {
        case accepted(Int)     // 서버가 준 상태 코드 (2xx)
        case refused(String)   // 내용이 틀렸다. 다시 보내지 않는다
        case later(String)     // 서버가 꺼졌거나 바쁘다. 나중에 다시 보낸다
    }

    private func post(_ body: Data, to url: URL) async -> Reply {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !config.apiKey.isEmpty { request.setValue(config.apiKey, forHTTPHeaderField: "x-api-key") }
        do {
            let (_, response) = try await session.data(for: request)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            switch code {
            case 200..<300: return .accepted(code)
            case 400, 413, 422: return .refused("서버가 내용을 받지 않았어요 (\(code))")
            case 401, 403: return .later("인증에 실패했어요 (\(code)). 키를 확인하세요")
            case 404: return .later("주소를 찾지 못했어요 (404). 경로를 확인하세요")
            default: return .later("서버가 응답하지 못했어요 (\(code))")
            }
        } catch {
            return .later("서버에 닿지 못했어요: \(error.localizedDescription)")
        }
    }

    private func succeeded() {
        delay = 0
        stats.lastError = nil
        stats.lastSentAt = Date()
        report()
    }

    /// 2초부터 두 배씩, 많아야 30초 간격으로 다시 보낸다 (그 뒤로는 SyncCenter가 30초마다 부른다)
    private func failed(_ why: String) {
        stats.lastError = why
        delay = delay == 0 ? 2 : min(delay * 2, 30)
        report()
        let wait = delay
        retry?.cancel()
        retry = Task { [weak self] in
            try? await Task.sleep(for: .seconds(wait))
            guard !Task.isCancelled else { return }
            await self?.retryNow()
        }
    }

    /// 기다렸다가 다시 보낸다. flush가 retry를 취소하므로, 자기 자신을 취소하지 않게 먼저 비운다
    private func retryNow() async {
        retry = nil
        await flush()
    }

    // MARK: 파일

    private func files(_ directory: URL) -> [URL] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: directory.path(percentEncoded: false))) ?? []
        return names.filter { $0.hasSuffix(".json") }.sorted().map { directory.appending(path: $0) }
    }

    private func write(_ data: Data, to url: URL) {
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
    }

    private func trim(_ directory: URL, keep: Int) {
        let all = files(directory)
        guard all.count > keep else { return }
        all.prefix(all.count - keep).forEach { try? FileManager.default.removeItem(at: $0) }
    }

    private func reject(_ url: URL) {
        try? FileManager.default.createDirectory(at: rejected, withIntermediateDirectories: true)
        let target = rejected.appending(path: url.lastPathComponent)
        try? FileManager.default.removeItem(at: target)
        if (try? FileManager.default.moveItem(at: url, to: target)) == nil { try? FileManager.default.removeItem(at: url) }
        trim(rejected, keep: 200)
    }

    private func count() {
        stats.pendingEvents = files(events).count
        stats.pendingSamples = files(samples).count
        stats.rejected = files(rejected).count
    }

    private func report() {
        count()
        onChange?(stats)
    }
}
