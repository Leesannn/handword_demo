import SwiftUI

/// 학습: 모델이 읽을 수 있는 낱말의 목록. 낱말을 고르면 본보기를 보고 따라 해 볼 수 있다
struct LearnView: View {
    let model: BoardModel
    let progress: ProgressStore
    @State private var path: [String] = []

    var body: some View {
        NavigationStack(path: $path) {
            List {
                Section {
                    Text(summary)
                        .font(.app(.subheadline))
                        .foregroundStyle(Theme.ink2)
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: 0, leading: 4, bottom: 0, trailing: 4))
                }
                if let next {
                    Section {
                        NavigationLink(value: next) { ContinueCard(word: next, count: progress.count(next)) }
                            .listRowBackground(Theme.bgRow)
                    } header: {
                        Text(progress.count(next) > 0 ? "이어서 하기" : "먼저 해 보기")
                    }
                    .headerProminence(.increased)
                }
                Section {
                    ForEach(model.words, id: \.self) { word in
                        NavigationLink(value: word) {
                            HStack(spacing: 10) {
                                Text(word).font(.app(.body)).foregroundStyle(Theme.ink)
                                Spacer(minLength: 0)
                                Marks(count: progress.count(word))
                            }
                            .frame(minHeight: 32)
                        }
                        .listRowBackground(Theme.bgRow)
                    }
                } header: {
                    Text("낱말")
                }
                .headerProminence(.increased)
            }
            .grouped()
            .scrollContentBackground(.hidden)
            .background(Theme.bgGrouped)
            .navigationTitle("학습")
            .navigationDestination(for: String.self) { word in
                LessonView(model: model, progress: progress, word: word)
            }
        }
        // 낱말 화면에서는 뒤로 단추가 칠판 위에 놓이므로 분필 색으로 바꾼다
        .tint(path.isEmpty ? Theme.tint : Theme.chalk)
    }

    private var summary: String {
        model.words.isEmpty
            ? "낱말 목록을 읽지 못했어요."
            : "배울 수 있는 낱말 \(model.words.count)개 중 \(progress.learned(among: model.words))개를 익혔어요"
    }

    /// 하던 낱말이 있으면 그것, 없으면 본보기가 있는 낱말부터
    private var next: String? {
        let open = model.words.filter { progress.count($0) < ProgressStore.goal }
        return open.first { progress.count($0) > 0 } ?? open.first { Demo.library[$0] != nil } ?? open.first
    }
}

private extension View {
    func grouped() -> some View {
        #if os(iOS)
        return self.listStyle(.insetGrouped)
        #else
        return self
        #endif
    }
}

/// 이어서 할 낱말 한 장: 본보기의 한 장면, 낱말, 진도
struct ContinueCard: View {
    let word: String
    let count: Int

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Theme.board
                if let demo = Demo.library[word], let motion = demo.motion {
                    AvatarStill(motion: motion, frame: demo.keyFrames[2], size: CGSize(width: 88, height: 88))
                } else if let demo = Demo.library[word] {
                    FigureView(pose: demo.poses[demo.keyFrames[2]]) { size in
                        .person(demo, in: size, flipX: true, maxFill: 0.4)
                    }
                } else {
                    BracketPair()
                        .stroke(Theme.chalk2, style: StrokeStyle(lineWidth: 3, lineCap: .square, lineJoin: .miter))
                        .frame(width: 30, height: 30)
                }
            }
            .frame(width: 88, height: 88)
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 6) {
                Gloss(word, style: .title2)
                    .dynamicTypeSize(...DynamicTypeSize.accessibility1)
                Text(ProgressStore.text(count))
                    .font(.app(.footnote))
                    .foregroundStyle(Theme.ink2)
                Marks(count: count)
            }
        }
        .padding(.vertical, 4)
    }
}
