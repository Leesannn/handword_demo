import SwiftUI

struct SettingsView: View {
    @Bindable var model: TranslatorModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            Section {
                TextField("예: 형준", text: $model.person)
            } header: {
                Text("수어하는 사람")
            } footer: {
                Text("확인한 데이터에 함께 저장합니다. 재학습 때 사람별로 나누는 데 씁니다.")
            }
            Section {
                LabeledContent("저장된 샘플", value: "\(model.savedCount)개")
            } header: {
                Text("데이터")
            } footer: {
                Text("'맞아요'를 눌렀거나 맞는 단어를 넣은 번역만 학습 형식(frames, times, aspect, start, end)으로 폰에 쌓입니다. 파일 앱 → 나의 iPhone → 수어 인식 → samples. 서버·DB가 준비되면 업로드를 붙입니다.")
            }
            Section {
                NavigationLink("기준값 확인") { SelfCheckView() }
            } footer: {
                Text("r0006 · 개발·시험용 후보 모델 (라벨은 AI 검수만 거침, 사람 검수·정식 평가 전). 신뢰도 기준 미정이라 확률만 보여줍니다.")
            }
        }
        .navigationTitle("설정")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) { Button("완료") { dismiss() } }
        }
    }
}
