import Foundation

/// 서버로 보내는 학습 기록 한 건. JSON 키는 snake_case다 (`docs/서버_연결_규격.md`).
/// 값이 없는 항목은 JSON에서 빠진다
struct SyncEvent: Codable, Sendable {
    enum Kind: String, Codable, Sendable {
        case lessonStarted = "lesson_started"           // 학습 시작: 따라 하기를 열었다
        case practiceAttempt = "practice_attempt"       // 연습 시도: 셋을 세기 시작했다
        case recognitionResult = "recognition_result"   // 인식 결과: 한 번 읽은 결과 (못 읽은 것 포함)
        case retry = "retry"                            // 재시도: 실패한 뒤 다시 하기를 눌렀다
        case lessonCompleted = "lesson_completed"       // 학습 완료: 세 번 알아봐서 익혔다
        case lessonEnded = "lesson_ended"               // 따라 하기를 닫았다
        case answerSelected = "answer_selected"         // 정답 선택: 번역 화면에서 사용자가 낱말을 확인하거나 고쳤다
    }

    // 모든 기록에 붙는 값
    var eventId = UUID().uuidString.lowercased()   // 중복을 걸러내는 번호. 다시 보내도 같다
    var schemaVersion = 1
    var eventType: Kind
    var eventTime = ""       // 폰에서 일어난 시각 (UTC, ISO 8601, 밀리초)
    var seq = 0              // 이 폰에서 1씩 늘어나는 순번. 빠진 기록을 찾는 데 쓴다
    var userId = ""          // 앱을 처음 켤 때 만든 익명 번호
    var sessionId = ""       // 앱을 켤 때마다 새로 만드는 번호
    var appVersion = ""
    var modelVersion = ""
    var device = ""

    // 기록마다 다른 값
    var source: String?              // "practice"(따라 하기) / "translate"(번역)
    var lessonId: String?            // 따라 하기를 한 번 열고 닫을 때까지 같은 번호
    var word: String?                // 목표 낱말
    var attempt: Int?                // 이 따라 하기에서 몇 번째 시도인지 (1부터)
    var readingId: String?           // 한 번 읽은 결과의 번호. 정답 선택이 어느 결과에 대한 것인지 잇는다
    var predictedWord: String?       // 모델의 1등 낱말 ('기타' 포함)
    var outcome: String?             // correct / wrong_word / unsure / unknown / hands_unseen / no_hands / read
    var isCorrect: Bool?             // 목표 낱말로 알아봤는지 (따라 하기)
    var confidence: Double?          // 1등 낱말의 확률
    var targetProbability: Double?   // 목표 낱말의 확률
    var probabilities: [String: Double]?
    var durationMs: Int?             // 동작 구간의 길이
    var handMissingRatio: Double?    // 동작 손이 안 잡힌 프레임 비율
    var previousOutcome: String?     // 재시도: 직전 결과
    var totalAttempts: Int?
    var successCount: Int?
    var selectedWord: String?        // 정답 선택: 사용자가 고른 낱말
    var wasCorrected: Bool?          // 정답 선택: 모델의 낱말과 달랐는지
    var sampleId: String?            // 함께 올리는 좌표 묶음의 번호 (동의한 경우만)

    init(_ kind: Kind) { eventType = kind }

    static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }()

    static func timestamp(_ date: Date = Date()) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: date)
    }
}

/// 기록에 붙이는 기기 종류와 앱 버전
enum AppInfo {
    static let device: String = {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { String(decoding: $0.prefix { $0 != 0 }, as: UTF8.self) }
    }()

    static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
}
