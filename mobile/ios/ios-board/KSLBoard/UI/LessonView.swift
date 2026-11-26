import SwiftUI

/// 낱말 배우기: 위에서 본보기 동작을 되풀이해 보여 주고, 아래에서 진도와 동작 순서를 보여 준다
struct LessonView: View {
    let model: BoardModel
    let progress: ProgressStore
    let word: String

    @State private var frame = 0
    @State private var playing = true
    @State private var slow = false
    /// 처음부터 거울에 비친 모습으로 보여 준다. 마주 본 모습을 거울처럼 따라 하면 반대쪽 손을 쓰게 되기 때문이다
    @State private var mirror = true
    @State private var yaw = 0.0
    @State private var practicing = false
    @Environment(\.still) private var still
    @Environment(\.dynamicTypeSize) private var typeSize
    @ScaledMetric(relativeTo: .body) private var sheetBase: CGFloat = 376

    private var demo: Demo? { Demo.library[word] }

    init(model: BoardModel, progress: ProgressStore, word: String, startFrame: Int = 0) {
        self.model = model
        self.progress = progress
        self.word = word
        _frame = State(initialValue: startFrame)
    }

    private struct PlayKey: Equatable {
        var playing: Bool
        var slow: Bool
        var covered: Bool
    }

    var body: some View {
        GeometryReader { geo in
            VStack(spacing: 0) {
                stage
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                // 본보기가 없는 낱말은 적을 것이 적으니 종이를 낮추고 칠판을 넓힌다
                BoardSheet { sheet }
                    .frame(height: min(demo == nil ? sheetBase * 0.56 : sheetBase, max(200, geo.size.height - 150)))
                    .padding(.top, -16)
            }
        }
        .background(Theme.bg)
        .inlineBar()
        .task(id: PlayKey(playing: playing, slow: slow, covered: practicing)) { await play() }
        .cover(isPresented: $practicing) {
            PracticeView(model: model, progress: progress, word: word)
        }
    }

    /// 본보기를 15fps(느리게는 그 0.4배)로 넘기고, 끝에서 잠깐 멈췄다가 처음으로 돌아간다
    private func play() async {
        guard let demo, playing, !practicing, !still else { return }
        let step = 1 / SignSpec.targetFPS / (slow ? 0.4 : 1)
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(step))
            if Task.isCancelled { return }
            if frame >= demo.poses.count - 1 {
                try? await Task.sleep(for: .seconds(0.7))
                if Task.isCancelled { return }
                frame = 0
            } else {
                frame += 1
            }
        }
    }

    // MARK: 무대

    private var stage: some View {
        ZStack {
            Theme.board.ignoresSafeArea(edges: .top)
            if let demo {
                let now = min(frame, demo.poses.count - 1)
                if let motion = demo.motion {
                    // 3D 인형. 장면 사이를 이어서 움직인다
                    // 아래쪽 단추 줄에 손이 가리지 않게 그 위에 맞추고, 위로는 뒤로 단추가 있는 줄까지 쓴다
                    AvatarView(motion: motion, frame: now, stepDuration: 1 / SignSpec.targetFPS / (slow ? 0.4 : 1),
                               mirror: mirror, bottomInset: 62, yaw: $yaw)
                        .padding(.top, -44)
                        .accessibilityLabel("\(word) 본보기 동작")
                        .accessibilityHint("좌우로 쓸어 인형을 돌립니다")
                } else {
                    FigureView(pose: demo.poses[now], trail: Trail(poses: demo.poses[...now])) { size in
                        .person(demo, in: size, flipX: !mirror)
                    }
                    .accessibilityHidden(false)
                    .accessibilityLabel("\(word) 본보기 동작")
                }
            } else {
                StageMessage(title: "이 낱말은 아직 본보기가 없어요", detail: "동작을 알고 있다면 따라 하기로 확인해 볼 수 있어요.")
            }
            if demo != nil { controls }
        }
    }

    private var controls: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer(minLength: 0)
                // 아주 큰 글자에서는 손 표시를 종이 쪽으로 옮겨 인형을 가리지 않게 한다
                if !typeSize.isAccessibilitySize {
                    Legend(rightSeen: true, leftSeen: true, leftFirst: mirror)
                }
            }
            Spacer(minLength: 0)
            HStack(spacing: 8) {
                Button { playing.toggle() } label: {
                    Image(systemName: playing ? "pause.fill" : "play.fill")
                }
                .buttonStyle(StagePillStyle())
                .accessibilityLabel(playing ? "멈춤" : "재생")
                Button("느리게") { slow.toggle() }
                    .buttonStyle(StagePillStyle(on: slow))
                    .accessibilityAddTraits(slow ? .isSelected : [])
                Button("거울로 보기") { mirror.toggle() }
                    .buttonStyle(StagePillStyle(on: mirror))
                    .accessibilityAddTraits(mirror ? .isSelected : [])
                if yaw != 0 {
                    Button("정면") { withAnimation(Theme.ease) { yaw = 0 } }
                        .buttonStyle(StagePillStyle())
                }
                Spacer(minLength: 0)
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 4)
        .padding(.bottom, 22)
    }

    // MARK: 종이

    private var sheet: some View {
        let count = progress.count(word)
        return VStack(alignment: .leading, spacing: 0) {
            if typeSize.isAccessibilitySize, demo != nil {
                Legend(rightSeen: true, leftSeen: true, leftFirst: mirror, onPaper: true)
            }
            FitOrScroll {
                VStack(alignment: .leading, spacing: 0) {
                    Gloss(word)
                        .dynamicTypeSize(...DynamicTypeSize.accessibility1)
                        .padding(.top, 6)
                    HStack(spacing: 8) {
                        Marks(count: count)
                        Text(ProgressStore.text(count))
                            .font(.app(.subheadline))
                            .foregroundStyle(Theme.ink2)
                    }
                    .padding(.top, 6)
                    if let demo { steps(demo) }
                }
            }
            Button("따라 하기") { practicing = true }
                .buttonStyle(CTAStyle())
                .padding(.vertical, 12)
        }
    }

    /// 동작 순서: 본보기에서 고르게 뽑은 네 장면. 누르면 그 장면에서 멈춘다
    private func steps(_ demo: Demo) -> some View {
        let keys = demo.keyFrames
        let current = keys.indices.min { abs(keys[$0] - frame) < abs(keys[$1] - frame) }
        return VStack(alignment: .leading, spacing: 0) {
            Text("동작 순서")
                .font(.app(.title3, .bold))
                .foregroundStyle(Theme.ink)
                .padding(.top, 20)
            HStack(alignment: .top, spacing: 8) {
                ForEach(keys.indices, id: \.self) { i in
                    Button {
                        playing = false
                        frame = keys[i]
                    } label: {
                        VStack(spacing: 5) {
                            ZStack {
                                Theme.board
                                if let motion = demo.motion {
                                    GeometryReader { geo in
                                        AvatarStill(motion: motion, frame: keys[i], mirror: mirror, size: geo.size)
                                    }
                                } else {
                                    FigureView(pose: demo.poses[keys[i]]) { size in
                                        .person(demo, in: size, flipX: !mirror, maxFill: 0.4)
                                    }
                                }
                            }
                            .aspectRatio(1, contentMode: .fit)
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .padding(5)
                            .overlay {
                                RoundedRectangle(cornerRadius: 21, style: .continuous)
                                    .strokeBorder(Theme.tint, lineWidth: 2.5)
                                    .opacity(!playing && current == i ? 1 : 0)
                            }
                            Text("\(i + 1)")
                                .font(.app(.caption, !playing && current == i ? .bold : .regular))
                                .monospacedDigit()
                                .foregroundStyle(!playing && current == i ? Theme.ink : Theme.ink2)
                        }
                    }
                    .buttonStyle(PressScale())
                    .accessibilityLabel("동작 \(i + 1)")
                    .accessibilityAddTraits(!playing && current == i ? .isSelected : [])
                }
            }
            .padding(.horizontal, -5)
            .padding(.top, 5)
            Text(demo.motion == nil ? "팀원이 녹화한 동작입니다. 수어 사용자의 확인을 받기 전이에요."
                 : "인형을 좌우로 끌면 돌려 볼 수 있어요. 팀원이 녹화한 동작을 옮긴 것이고, 수어 사용자의 확인을 받기 전이에요.")
                .font(.app(.footnote))
                .foregroundStyle(Theme.ink2)
                .padding(.top, 8)
        }
    }
}
