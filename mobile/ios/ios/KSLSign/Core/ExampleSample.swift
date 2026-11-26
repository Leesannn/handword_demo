import Foundation

/// model_bundle/example/thanks_T01.npz를 JSON으로 옮긴 것(coreml/make_fixtures.py가 만든다). null은 NaN
struct ExampleSample: Decodable {
    let frames: [[Float?]]
    let times: [Float]
    let aspect: Float
    let start: Float
    let end: Float
    let classes: [String]
    let expected: [Float]

    static func load(bundle: Bundle = .main) throws -> ExampleSample {
        guard let url = bundle.url(forResource: "example_thanks_T01", withExtension: "json") else {
            throw SignError.modelMissing("example_thanks_T01.json")
        }
        return try JSONDecoder().decode(ExampleSample.self, from: Data(contentsOf: url))
    }

    /// 이식한 전처리와 Core ML로 판정해서 expected.json과의 최대 차이를 돌려준다
    func check(with classifier: SignClassifier) throws -> (probabilities: [Float], maxDiff: Float) {
        let p = try classifier.predict(
            frames: frames.map { $0.map { $0 ?? .nan } },
            times: times.map(Double.init),
            aspect: Double(aspect), start: Double(start), end: Double(end))
        let diff = zip(p, expected).map { abs($0 - $1) }.max() ?? .infinity
        return (p, diff)
    }
}
