import Foundation

// Outbox(폰에 쌓고 보내는 부분)를 Mac에서 시험한다. tools/sync_test.sh가 컴파일해서 돌린다.
//   synctest <폴더> <서버 주소> add <기록 수> <묶음 수>   쌓고 한 번 보내 본다 (앱을 쓰다가 끈 것)
//   synctest <폴더> <서버 주소> flush <초>                다 보낼 때까지 기다린다 (앱을 다시 켠 것)
let arguments = CommandLine.arguments
let folder = URL(fileURLWithPath: arguments[1]), address = arguments[2], command = arguments[3]
let defaults = UserDefaults(suiteName: "kslboard.synctest")!
let config = ServerConfig(baseURL: URL(string: address), apiKey: "test-key", eventsPath: "/v1/events", samplesPath: "/v1/samples", batchSize: 100)
let outbox = Outbox(config: config, folder: folder, defaults: defaults)

func show(_ title: String) async {
    let s = await outbox.current()
    print("\(title): 기다리는 기록 \(s.pendingEvents), 기다리는 묶음 \(s.pendingSamples), 보낸 기록 \(s.sentEvents), 보낸 묶음 \(s.sentSamples), 받지 않은 것 \(s.rejected)\(s.lastError.map { " | \($0)" } ?? "")")
}

if command == "reset" {
    defaults.removePersistentDomain(forName: "kslboard.synctest")
    try? FileManager.default.removeItem(at: folder)
} else if command == "add" {
    var seq = defaults.integer(forKey: "seq")
    let kinds: [SyncEvent.Kind] = [.lessonStarted, .practiceAttempt, .recognitionResult, .retry, .practiceAttempt, .recognitionResult, .lessonCompleted, .lessonEnded]
    for i in 0..<Int(arguments[4])! {
        var event = SyncEvent(kinds[i % kinds.count])
        seq += 1
        event.seq = seq
        event.eventTime = SyncEvent.timestamp()
        event.userId = "test-user"
        event.sessionId = "test-session"
        event.word = ["커피", "춥다", "우유", "감사", "자다"][i % 5]
        event.source = "practice"
        if event.eventType == .recognitionResult {
            event.outcome = i % 3 == 0 ? "correct" : "unknown"
            event.isCorrect = i % 3 == 0
            event.confidence = 0.9
        }
        await outbox.add(event: try! SyncEvent.encoder.encode(event), seq: seq, id: event.eventId)
    }
    defaults.set(seq, forKey: "seq")
    for i in 0..<Int(arguments[5])! {
        let id = UUID().uuidString.lowercased()
        let body = try! JSONSerialization.data(withJSONObject: ["id": id, "label": "감사", "frames": [[0.1, 0.2, 0.3]], "n": i])
        await outbox.add(sample: body, id: id)
    }
    await show("쌓은 뒤")
    await outbox.flush()
    await show("한 번 보내 본 뒤")
} else if command == "flush" {
    let limit = Date().addingTimeInterval(Double(arguments[4])!)
    await outbox.flush()
    while Date() < limit {
        let s = await outbox.current()
        if s.pendingEvents == 0 && s.pendingSamples == 0 { break }
        try? await Task.sleep(for: .seconds(0.5))
    }
    await show("다 보낸 뒤")
}
