import SwiftUI

/// 따라 하기: 휴대폰을 세워 두고 시작을 누르면 셋을 센다. 그 뒤 손이 보이면 읽기 시작하고, 손을 내리면 끝난다.
/// 읽는 동안에는 아무것도 누르지 않는다 (수어에는 두 손이 필요하다)
struct PracticeView: View {
    let model: BoardModel
    let progress: ProgressStore
    let word: String

    enum Failure: Equatable {
        case noHands            // 기다리는 동안 손이 보이지 않았다
        case handsUnseen        // 읽는 동안 손이 절반 넘게 안 잡혔다
        case unknown            // 아는 낱말이 아니라고 봤다
        case other(String)      // 다른 낱말로 읽었다
        case unsure             // 이 낱말로 읽었지만 확률이 낮다
    }

    enum Step: Equatable {
        case ready
        case counting(Int)
        case armed
        case success(Reading)
        case failure(Failure, Reading?)
    }

    @State private var step: Step
    @State private var run = 0
    // 서버로 보내는 기록에 쓰는 값: 이 따라 하기의 번호, 시도와 성공 횟수, 직전 결과
    @State private var lessonID = UUID().uuidString.lowercased()
    @State private var attempts = 0
    @State private var successes = 0
    @State private var lastOutcome: String?

    init(model: BoardModel, progress: ProgressStore, word: String, initial: Step = .ready) {
        self.model = model
        self.progress = progress
        self.word = word
        _step = State(initialValue: initial)
    }
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var typeSize
    @ScaledMetric(relativeTo: .body) private var sheetBase: CGFloat = 400

    var body: some View {
        GeometryReader { geo in
            VStack(spacing: 0) {
                stage
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                BoardSheet { sheet }
                    .frame(height: min(sheetBase, max(300, geo.size.height - 150)))
                    .padding(.top, -16)
            }
        }
        .background(Theme.bg)
        .onAppear {
            model.onReading = { reading in receive(reading) }
            model.need(.practice)
            log(.lessonStarted)
        }
        .onDisappear {
            model.disarm()
            model.onReading = nil
            model.release(.practice)
            log(.lessonEnded) {
                $0.totalAttempts = attempts
                $0.successCount = successes
            }
        }
        .task(id: run) {
            guard run > 0 else { return }
            await countdown()
        }
        .sensoryFeedback(trigger: step) { _, new -> SensoryFeedback? in
            switch new {
            case .success: return .success
            case .failure: return .error
            case .armed: return .impact(weight: .medium)
            default: return nil
            }
        }
    }

    // MARK: 순서

    private func start() {
        if case .failure = step, let lastOutcome {
            log(.retry) { $0.previousOutcome = lastOutcome }
        }
        attempts += 1
        log(.practiceAttempt)
        step = .counting(3)
        run += 1
    }

    /// 서버로 보내는 기록. 이 따라 하기의 번호와 목표 낱말, 시도 번호를 붙인다
    private func log(_ kind: SyncEvent.Kind, _ fill: (inout SyncEvent) -> Void = { _ in }) {
        SyncCenter.shared.log(kind) {
            $0.source = "practice"
            $0.lessonId = lessonID
            $0.word = word
            // 시도 번호는 규격서대로 연습 시도·인식 결과·재시도에만 붙인다. 서버는 기록 종류마다 정해진 항목만 받는다
            if attempts > 0, [.practiceAttempt, .recognitionResult, .retry].contains(kind) { $0.attempt = attempts }
            fill(&$0)
        }
    }

    /// 인식 결과 한 건을 기록하고, 동의했으면 좌표 묶음도 쌓는다
    private func report(_ outcome: String, _ reading: Reading?) {
        lastOutcome = outcome
        let sample = reading.flatMap {
            SyncCenter.shared.saveSample(for: $0.id, label: word, feedback: "practice", source: "kslboard-practice", outcome: outcome)
        }
        log(.recognitionResult) {
            if let reading { SyncCenter.shared.fill(&$0, from: reading, target: word) }
            $0.outcome = outcome
            $0.isCorrect = outcome == "correct"
            $0.sampleId = sample
        }
    }

    private func countdown() async {
        for n in [3, 2, 1] {
            step = .counting(n)
            AccessibilityNotification.Announcement("\(n)").post()
            try? await Task.sleep(for: .seconds(0.9))
            if Task.isCancelled { return }
        }
        step = .armed
        model.armAuto()
        // 6초 동안 손이 한 번도 보이지 않으면 그만둔다. 읽는 중이면 끝날 때까지 기다린다
        try? await Task.sleep(for: .seconds(6))
        while !Task.isCancelled, step == .armed, model.isReading {
            try? await Task.sleep(for: .seconds(0.2))
        }
        if !Task.isCancelled, step == .armed {
            model.disarm()
            step = .failure(.noHands, nil)
            report("no_hands", nil)
        }
    }

    private func receive(_ reading: Reading) {
        guard step == .armed else { return }
        model.disarm()
        switch reading.outcome {
        case .handsUnseen:
            step = .failure(.handsUnseen, reading)
            report("hands_unseen", reading)
        case .unknown:
            step = .failure(.unknown, reading)
            report("unknown", reading)
        case .word(let read, let sure):
            if read != word {
                step = .failure(.other(read), reading)
                report("wrong_word", reading)
            } else if !sure {
                step = .failure(.unsure, reading)
                report("unsure", reading)
            } else {
                let before = progress.count(word)
                progress.add(word)
                successes += 1
                step = .success(reading)
                report("correct", reading)
                if before < ProgressStore.goal, progress.count(word) == ProgressStore.goal {
                    log(.lessonCompleted) {
                        $0.totalAttempts = attempts
                        $0.successCount = successes
                    }
                }
            }
        }
    }

    private var busy: Bool {
        switch step {
        case .counting, .armed: true
        default: false
        }
    }

    // MARK: 무대

    private var stage: some View {
        ZStack(alignment: .bottomLeading) {
            Theme.board.ignoresSafeArea(edges: .top)
            if model.setup == .ready, !model.nobody {
                FigureView(pose: model.pose, trail: model.isReading ? model.trail : nil,
                           showZone: !model.guide.isOK && model.pose != nil) { size in
                    .camera(aspect: model.aspect, in: size, flipX: false)
                }
                .ignoresSafeArea(edges: .top)
            }
            Group {
                switch model.setup {
                case .cameraDenied:
                    StageMessage(title: "카메라를 쓸 수 없어요", detail: "설정에서 카메라를 허용하면 따라 해 볼 수 있습니다. 영상은 저장하지 않습니다.")
                case .failed(let reason):
                    StageMessage(title: "카메라를 시작하지 못했어요", detail: reason)
                case .ready where model.nobody:
                    StageMessage(title: "사람이 보이지 않아요", detail: "얼굴과 두 손이 화면에 들어오게 서 주세요.")
                default:
                    EmptyView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            VStack(spacing: 10) {
                HStack(alignment: .top, spacing: 12) {
                    Button { dismiss() } label: { Image(systemName: "xmark") }
                        .buttonStyle(GlassCircleStyle())
                        .accessibilityLabel("닫기")
                    Spacer(minLength: 0)
                    if !typeSize.isAccessibilitySize {
                        Legend(rightSeen: model.rightVisible, leftSeen: model.leftVisible, leftFirst: true)
                    }
                }
                if !typeSize.isAccessibilitySize, model.setup == .ready, !model.nobody, let hint = model.guide.hint(selfView: true) {
                    HintPill(text: hint)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16)
            .padding(.top, 4)

            if case .counting(let n) = step {
                Text("\(n)")
                    .font(.system(size: 96, weight: .bold))
                    .monospacedDigit()
                    .foregroundStyle(Theme.chalk)
                    .padding(.leading, 28)
                    .padding(.bottom, 30)
                    .accessibilityHidden(true)
            }
        }
    }

    // MARK: 종이

    private var sheet: some View {
        let count = progress.count(word)
        return VStack(alignment: .leading, spacing: 0) {
            if typeSize.isAccessibilitySize {
                Legend(rightSeen: model.rightVisible, leftSeen: model.leftVisible, leftFirst: true, onPaper: true)
            }
            FitOrScroll {
                VStack(alignment: .leading, spacing: 0) {
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 12) { gloss; Spacer(minLength: 0); badge }
                        VStack(alignment: .leading, spacing: 2) { gloss; badge }
                    }
                    .frame(minHeight: 58)
                    HStack(spacing: 8) {
                        Marks(count: count)
                        Text(ProgressStore.text(count))
                            .font(.app(.subheadline))
                            .foregroundStyle(Theme.ink2)
                    }
                    Text(message)
                        .font(.app(.subheadline))
                        .foregroundStyle(Theme.ink2)
                        .padding(.top, 10)
                }
            }
            LaneView(phase: lane, showMinimum: false)
                .padding(.top, 6)
            actions
                .padding(.top, 12)
                .padding(.bottom, 8)
        }
    }

    private var gloss: some View {
        Group {
            switch step {
            case .success: Gloss(word)
            case .failure(.other(let read), _): Gloss(read, tone: .muted)
            case .failure(.unsure, _): Gloss(word, tone: .unsure)
            case .failure: Gloss("?", tone: .muted)
            default: Gloss(word, tone: .muted)
            }
        }
        .dynamicTypeSize(...DynamicTypeSize.accessibility1)
        .frame(minHeight: 52)
    }

    @ViewBuilder
    private var badge: some View {
        switch step {
        case .success:
            Label("알아봤어요", systemImage: "checkmark").foregroundStyle(Theme.tint).modifier(Badge())
        case .failure(.other, _):
            Label("다르게 읽었어요", systemImage: "exclamationmark.circle").foregroundStyle(Theme.bad).modifier(Badge())
        case .failure(.unsure, _):
            Label("확실하지 않아요", systemImage: "exclamationmark.circle").foregroundStyle(Theme.warn).modifier(Badge())
        case .failure:
            Label("읽지 못했어요", systemImage: "exclamationmark.circle").foregroundStyle(Theme.bad).modifier(Badge())
        default:
            EmptyView()
        }
    }

    private struct Badge: ViewModifier {
        func body(content: Content) -> some View {
            content
                .font(.app(.subheadline, .bold))
                .labelStyle(.titleAndIcon)
                .lineLimit(1)
        }
    }

    private var message: String {
        switch step {
        case .ready:
            return "휴대폰을 세워 두고 시작을 누르세요. 셋을 센 뒤 손을 올려 수어를 하면 읽기 시작해요."
        case .counting:
            return "얼굴과 두 손이 화면에 들어오게 서 주세요."
        case .armed:
            return model.isReading ? "읽는 중이에요. 다 하면 손을 내려 주세요." : "지금 수어를 해 보세요. 손을 내리면 읽기가 끝나요."
        case .success(let reading):
            let right = Reading.ratio(reading.rightSeen), left = Reading.ratio(reading.leftSeen)
            if min(right, left) < 0.5 {
                let hand = right < left ? "오른손" : "왼손"
                return "\(hand)이 \(Float(min(right, left)).percentText)만 보였어요. 다음에는 조금 더 가까이 서 보세요."
            }
            return "확률 \(reading.top.probability.percentText)로 읽었어요."
        case .failure(.noHands, _):
            return "손이 보이지 않았어요. 두 손이 화면에 들어오게 서서 다시 해 보세요."
        case .failure(.handsUnseen, let reading):
            let seen = reading.map { Float(1 - $0.handMissing).percentText } ?? "절반 아래"
            return "읽는 동안 손이 \(seen)만 보였어요. 조금 더 가까이 와서 다시 해 보세요."
        case .failure(.unknown, _):
            return Demo.library[word] == nil ? "아는 낱말로 읽지 못했어요. 동작을 천천히 다시 해 보세요."
                : "아는 낱말로 읽지 못했어요. 본보기를 다시 보고 해 보세요."
        case .failure(.other(let read), _):
            return "\(word) 대신 \(read.withRo) 읽었어요. 동작을 다시 확인해 보세요."
        case .failure(.unsure, let reading):
            let p = reading.map { $0.probability(of: word).percentText } ?? ""
            return "\(word.withRo) 읽었지만 확률이 \(p)라서 세지 않았어요. 한 번 더 해 보세요."
        }
    }

    private var lane: LaneView.Phase {
        switch step {
        case .armed where model.isReading:
            return .open(seconds: model.elapsed)
        case .success(let reading):
            return .closed(seconds: reading.seconds, word: word, tone: .normal)
        case .failure(let why, let reading?):
            switch why {
            case .other(let read): return .closed(seconds: reading.seconds, word: read, tone: .muted)
            case .unsure: return .closed(seconds: reading.seconds, word: word, tone: .unsure)
            default: return .closed(seconds: reading.seconds, word: "?", tone: .muted)
            }
        default:
            return .waiting
        }
    }

    private var actions: some View {
        let done: Bool = {
            switch step {
            case .success, .failure: true
            default: false
            }
        }()
        let title: String = {
            switch step {
            case .ready: "시작"
            case .counting: "준비"
            case .armed: "읽는 중"
            case .success: "한 번 더"
            case .failure: "다시 하기"
            }
        }()
        return VStack(spacing: 2) {
            Button(title, action: start)
                .buttonStyle(CTAStyle())
                .disabled(busy || model.setup != .ready)
            Button("마치기") { dismiss() }
                .buttonStyle(TextButtonStyle(wide: true))
                .opacity(done ? 1 : 0)
                .disabled(!done)
                .accessibilityHidden(!done)
        }
    }
}
