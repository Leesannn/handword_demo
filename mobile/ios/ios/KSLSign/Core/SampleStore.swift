import Foundation

/// 사용자가 '맞아요'를 눌렀거나 맞는 단어를 넣은 번역 한 건.
/// train_gru.py가 읽는 클립 형식(frames, times, aspect, start, end)에 정답과 판정 정보를 붙였다. JSON 키는 snake_case
struct Sample: Codable, Equatable {
    var id: String
    var created: String
    var person: String          // 수어한 사람. 재학습 때 사람별로 나누는 데 쓴다
    var label: String           // 사람이 확인한 정답 단어
    var feedback: String        // "confirmed"(맞아요) / "corrected"(맞는 단어를 넣음)
    var predicted: String       // 앱이 낸 1등 단어
    var classes: [String]
    var probabilities: [Float]
    var model: String
    var preprocessVersion: String
    var mode: String            // "auto" / "button"
    var camera: String          // "front" / "back" (+ 후면 줌, 예: "back 0.5×")
    var aspect: Double
    var start: Double           // 동작 구간 (클립 첫 프레임 기준 초)
    var end: Double
    var times: [Double]
    var frames: [[Float?]]      // 프레임마다 177개, null은 NaN(안 잡힌 점)
    var device: String
    var appVersion: String

    static var deviceModel: String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { String(decoding: $0.prefix { $0 != 0 }, as: UTF8.self) }
    }

    static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
    }
}

/// 샘플을 Documents/samples/<id>.json으로 폰에 쌓는다 (파일 앱·Finder로 꺼냄).
/// 서버·DB 규격이 나오면 여기에 업로드를 붙인다
enum SampleStore {
    static var folder: URL {
        URL.documentsDirectory.appending(path: "samples", directoryHint: .isDirectory)
    }

    static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    /// 같은 id면 덮어쓴다 (정답을 바꿨을 때)
    @discardableResult
    static func save(_ sample: Sample, in folder: URL = SampleStore.folder) throws -> URL {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let url = folder.appending(path: "\(sample.id).json")
        try encoder.encode(sample).write(to: url, options: .atomic)
        return url
    }

    static func count(in folder: URL = SampleStore.folder) -> Int {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: folder.path(percentEncoded: false))) ?? []
        return names.filter { $0.hasSuffix(".json") }.count
    }
}
