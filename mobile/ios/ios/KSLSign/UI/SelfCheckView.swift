import SwiftUI

/// 이 기기에서 이식한 전처리 + Core ML로 example/thanks_T01을 판정해 expected.json과 비교한다
struct SelfCheckView: View {
    @State private var rows: [(word: String, app: Float, expected: Float)] = []
    @State private var maxDiff: Float?
    @State private var error: String?

    var body: some View {
        List {
            Section {
                if let error {
                    Text(error).foregroundStyle(.red)
                } else if let maxDiff {
                    let ok = maxDiff <= 1e-4
                    Label(ok ? "OK: expected.json과 같음" : "다름: 전처리나 모델을 확인하세요",
                          systemImage: ok ? "checkmark.seal.fill" : "xmark.octagon.fill")
                        .foregroundStyle(ok ? .green : .red)
                    Text("최대 차이 \(maxDiff, format: .number.notation(.scientific).precision(.significantDigits(3))) (기준 1e-4 이하)")
                } else {
                    ProgressView()
                }
            } footer: {
                Text("T01 웹캠 '감사' 좌표. 학습에 쓴 영상이라 정답 확인용이며 성능 근거가 아닙니다.")
            }
            Section("단어별 확률 (앱 / expected.json)") {
                ForEach(rows, id: \.word) { row in
                    HStack {
                        Text(row.word)
                        Spacer()
                        Text("\(row.app, format: .number.precision(.significantDigits(6))) / \(row.expected, format: .number.precision(.significantDigits(6)))")
                            .monospacedDigit()
                            .font(.caption)
                    }
                }
            }
        }
        .navigationTitle("기준값 확인")
        .navigationBarTitleDisplayMode(.inline)
        .task { run() }
    }

    private func run() {
        do {
            let classifier = try SignClassifier()
            let example = try ExampleSample.load()
            let (p, diff) = try example.check(with: classifier)
            rows = classifier.classes.indices.map { (classifier.classes[$0], p[$0], example.expected[$0]) }
            maxDiff = diff
        } catch {
            self.error = error.localizedDescription
        }
    }
}
