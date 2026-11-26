import Foundation

/// 서버 연결 설정. `Resources/Server.plist`에서 읽는다.
/// 주소가 비어 있으면 아무것도 보내지 않고 폰에 쌓기만 한다 (서버가 준비되면 주소만 넣으면 된다).
/// 시험할 때는 실행 인자로 덮어쓸 수 있다: `-serverURL http://192.168.0.10:8787 -serverKey abc`
struct ServerConfig: Sendable {
    var baseURL: URL?
    var apiKey: String
    var eventsPath: String
    var samplesPath: String
    var batchSize: Int

    var isSet: Bool { baseURL != nil }
    var eventsURL: URL? { baseURL.map { Self.join($0, eventsPath) } }
    /// 좌표 묶음을 받는 주소. 경로가 비어 있으면 서버가 아직 받지 않는 것이다 (보내지 않고 폰에 쌓아 둔다)
    var samplesURL: URL? { samplesPath.isEmpty ? nil : baseURL.map { Self.join($0, samplesPath) } }

    static func load(bundle: Bundle = .main, defaults: UserDefaults = .standard) -> ServerConfig {
        let file = bundle.url(forResource: "Server", withExtension: "plist")
            .flatMap { NSDictionary(contentsOf: $0) as? [String: Any] } ?? [:]
        func text(_ key: String, _ fallback: String) -> String {
            ((file[key] as? String) ?? fallback).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let address = defaults.string(forKey: "serverURL") ?? text("BaseURL", "")
        let url = URL(string: address).flatMap { $0.scheme?.hasPrefix("http") == true && $0.host != nil ? $0 : nil }
        return ServerConfig(baseURL: url, apiKey: defaults.string(forKey: "serverKey") ?? text("APIKey", ""),
                            eventsPath: text("EventsPath", "/v1/events"), samplesPath: text("SamplesPath", ""),
                            batchSize: min(max((file["BatchSize"] as? Int) ?? 100, 1), 500))
    }

    private static func join(_ base: URL, _ path: String) -> URL {
        let trimmed = base.absoluteString.hasSuffix("/") ? String(base.absoluteString.dropLast()) : base.absoluteString
        return URL(string: trimmed + (path.hasPrefix("/") ? path : "/" + path)) ?? base
    }
}
