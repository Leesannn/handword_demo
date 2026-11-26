import SwiftUI

/// 지금 고른 번역. 1등 단어와 확률을 크게 보여주고, 확인하지 않았으면 '맞아요'/'틀려요'를 띄운다.
/// 신뢰도 기준(이 값 미만이면 인식 실패)은 아직 정하지 않아 확률만 보여준다
struct TranslationCard: View {
    let translation: Translation?
    let mode: Segmenter.Mode
    let isRecording: Bool
    let elapsed: Double
    let message: String?
    let onConfirm: () -> Void
    let onCorrect: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if isRecording {
                Label(String(format: "인식 중 %.1f초", elapsed), systemImage: "record.circle")
                    .font(.callout.bold())
                    .foregroundStyle(.red)
            } else if let message {
                Text(message).font(.callout).foregroundStyle(.orange)
            }
            if let t = translation {
                HStack(alignment: .firstTextBaseline) {
                    Text(t.top.word).font(.system(size: 44, weight: .bold))
                    Text(percent(t.top.probability)).font(.title3).foregroundStyle(.secondary)
                    Spacer()
                    Text(t.ranking.dropFirst().prefix(2).map { "\($0.word) \(percent($0.probability))" }.joined(separator: "\n"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.trailing)
                }
                if t.handMissing > SignSpec.missingWarn {
                    Text("※ 손이 절반 넘게 안 잡혀 판정을 믿기 어려움").font(.caption).foregroundStyle(.orange)
                }
                feedback(t)
            } else if !isRecording && message == nil {
                Text(mode == .auto ? "손을 올려 수어를 하고, 손을 내리면 번역합니다" : "'시작'을 누르고 수어를 한 뒤 '끝'을 누르세요")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private func feedback(_ t: Translation) -> some View {
        if let label = t.label {
            HStack {
                Label(t.corrected ? "정답 '\(label)'(으)로 저장함" : "맞음 확인 · 저장함",
                      systemImage: t.corrected ? "pencil.circle.fill" : "checkmark.circle.fill")
                    .foregroundStyle(t.corrected ? .orange : .green)
                Spacer()
                Button("바꾸기", action: onCorrect)
            }
            .font(.callout)
        } else {
            HStack(spacing: 10) {
                Button(action: onConfirm) {
                    Label("맞아요", systemImage: "checkmark").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
                Button(action: onCorrect) {
                    Label("틀려요", systemImage: "xmark").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .tint(.orange)
            }
            .controlSize(.large)
        }
    }

    private func percent(_ p: Float) -> String { String(format: "%.1f%%", p * 100) }
}

/// 맞는 단어 고르기: 학습 단어 중에서 고르거나, 목록에 없는 단어를 직접 넣는다
struct CorrectionSheet: View {
    let translation: Translation
    let classes: [String]
    let onSave: (String) -> Void
    @State private var custom = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(classes, id: \.self) { word in
                        Button {
                            onSave(word)
                            dismiss()
                        } label: {
                            HStack {
                                Text(word).foregroundStyle(.primary)
                                if word == translation.top.word {
                                    Text("앱 판정").font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                if word == translation.label { Image(systemName: "checkmark") }
                            }
                        }
                    }
                } header: {
                    Text("학습 단어")
                }
                Section {
                    TextField("단어 입력", text: $custom)
                    Button("이 단어로 저장") {
                        onSave(trimmed)
                        dismiss()
                    }
                    .disabled(trimmed.isEmpty)
                } header: {
                    Text("목록에 없는 단어")
                } footer: {
                    Text("새 단어는 다음 재학습 때 단어를 추가해야 모델이 배웁니다.")
                }
            }
            .navigationTitle("맞는 단어 고르기")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private var trimmed: String { custom.trimmingCharacters(in: .whitespacesAndNewlines) }
}

/// 번역 기록 (최신이 왼쪽). 눌러서 고르면 위 카드에서 확인하거나 고칠 수 있다
struct HistoryStrip: View {
    let translations: [Translation]
    let selectedID: UUID?
    let onSelect: (UUID) -> Void

    var body: some View {
        if !translations.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(translations) { t in
                        Button {
                            onSelect(t.id)
                        } label: {
                            Label(title(t), systemImage: icon(t))
                                .font(.callout)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 6)
                                .background(t.id == selectedID ? Color.accentColor.opacity(0.3) : Color.secondary.opacity(0.15),
                                            in: Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private func title(_ t: Translation) -> String {
        guard let label = t.label else { return t.top.word }
        return t.corrected ? "\(t.top.word)→\(label)" : label
    }

    private func icon(_ t: Translation) -> String {
        guard t.label != nil else { return "questionmark.circle" }
        return t.corrected ? "pencil.circle.fill" : "checkmark.circle.fill"
    }
}
