import CoreML
import Foundation

/// Core ML로 바꾼 r0006. model_bundle/predict.py의 load/predict와 같은 일을 한다.
final class SignClassifier {
    static let modelName = "ksl_r0006"
    let classes: [String]
    let run: String
    let preprocessVersion: String
    private let model: MLModel

    init(bundle: Bundle = .main) throws {
        guard let url = bundle.url(forResource: Self.modelName, withExtension: "mlmodelc") else {
            throw SignError.modelMissing("\(Self.modelName).mlmodelc")
        }
        let config = MLModelConfiguration()
        // 기준값(float32)과 맞추려고 CPU에서만 돌린다. 모델이 작아 충분히 빠르다
        config.computeUnits = .cpuOnly
        model = try MLModel(contentsOf: url, configuration: config)
        let meta = model.modelDescription.metadata[.creatorDefinedKey] as? [String: String]
        guard let json = meta?["classes"],
              let classes = try? JSONDecoder().decode([String].self, from: Data(json.utf8)) else {
            throw SignError.badModelMetadata
        }
        self.classes = classes
        run = meta?["run"] ?? ""
        preprocessVersion = meta?["preprocess_version"] ?? ""
    }

    /// frames: 프레임마다 177개 값(안 잡힌 점은 NaN). 동작 구간 [start, end]초만 쓴다. 반환: 단어별 확률(classes 순서)
    func predict(frames: [[Float]], times: [Double], aspect: Double, start: Double, end: Double) throws -> [Float] {
        let window = zip(frames, times).filter { $0.1 >= start && $0.1 <= end }.map(\.0)
        guard window.count >= 2 else { throw SignError.tooFewFrames }
        return try probabilities(Preprocess.run(window, aspect: aspect))
    }

    /// x: 전처리를 마친 30 × 177
    func probabilities(_ x: [Float]) throws -> [Float] {
        let input = try MLMultiArray(shape: [1, NSNumber(value: SignSpec.numFrames), NSNumber(value: SignSpec.numValues)], dataType: .float32)
        input.withUnsafeMutableBufferPointer(ofType: Float.self) { ptr, strides in
            for f in 0..<SignSpec.numFrames {
                for v in 0..<SignSpec.numValues {
                    ptr[f * strides[1] + v * strides[2]] = x[f * SignSpec.numValues + v]
                }
            }
        }
        let output = try model.prediction(from: MLDictionaryFeatureProvider(dictionary: ["x": input]))
        guard let p = output.featureValue(for: "probabilities")?.multiArrayValue else { throw SignError.badModelMetadata }
        return (0..<classes.count).map { p[[0, NSNumber(value: $0)]].floatValue }
    }
}
