import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// 번역: 위는 칠판 무대(카메라가 본 사람을 점으로 그린 도식), 아래는 읽은 낱말을 적는 종이
struct TranslateView: View {
    let model: BoardModel

    @State private var detail: Token?
    @AppStorage("detailTipSeen") private var tipSeen = false
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.openURL) private var openURL
    @ScaledMetric(relativeTo: .body) private var sheetBase: CGFloat = 358

    var body: some View {
        GeometryReader { geo in
            VStack(spacing: 0) {
                stage
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                BoardSheet { sheet }
                    .frame(height: min(sheetBase, max(280, geo.size.height - 150)))
                    .padding(.top, -16)
            }
        }
        .background(Theme.bg)
        .onAppear { model.need(.translate) }
        .onDisappear { model.release(.translate) }
        .sheet(item: $detail) { token in
            TokenDetailView(model: model, tokenID: token.id)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationBackground(Theme.bgGrouped)
        }
        .sensoryFeedback(.impact(weight: .medium), trigger: model.isReading)
        .sensoryFeedback(trigger: model.latest) { _, new -> SensoryFeedback? in
            switch new {
            case .token(let id): return model.token(id)?.sure == true ? .success : .warning
            case .unread: return .error
            case nil: return nil
            }
        }
        .onChange(of: model.latest) { _, new in announce(new) }
    }

    // MARK: 무대

    private var blocked: Bool { model.setup != .ready || model.nobody }

    private var stage: some View {
        ZStack {
            Theme.board.ignoresSafeArea(edges: .top)
            if model.setup == .ready, !model.nobody {
                FigureView(pose: model.pose, trail: model.isReading ? model.trail : nil,
                           showZone: !model.guide.isOK && model.pose != nil) { size in
                    .camera(aspect: model.aspect, in: size, flipX: !model.isFront)
                }
                .ignoresSafeArea(edges: .top)
            }
            stageMessage
            stageControls
        }
    }

    @ViewBuilder
    private var stageMessage: some View {
        switch model.setup {
        case .cameraDenied:
            StageMessage(title: "카메라를 쓸 수 없어요",
                         detail: "설정에서 카메라를 허용하면 수어를 읽을 수 있습니다. 영상은 저장하지 않습니다.",
                         actionTitle: "설정 열기", action: openSettings)
        case .failed(let reason):
            StageMessage(title: "카메라를 시작하지 못했어요", detail: reason)
        case .ready where model.nobody:
            StageMessage(title: "사람이 보이지 않아요", detail: "수어하는 사람의 얼굴과 두 손이 화면에 들어오게 비춰 주세요.")
        default:
            EmptyView()
        }
    }

    private var stageControls: some View {
        VStack(spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                if !typeSize.isAccessibilitySize {
                    Legend(rightSeen: model.rightVisible, leftSeen: model.leftVisible, leftFirst: model.isFront)
                        .opacity(model.setup == .ready ? 1 : 0.5)
                }
                Spacer(minLength: 0)
                Button(action: model.switchCamera) {
                    Image(systemName: "arrow.triangle.2.circlepath.camera")
                }
                .buttonStyle(GlassCircleStyle())
                .disabled(model.setup != .ready || model.isReading)
                .accessibilityLabel(model.isFront ? "뒤쪽 카메라로 바꾸기" : "앞쪽 카메라로 바꾸기")
            }
            if !typeSize.isAccessibilitySize, model.setup == .ready, !model.nobody, let hint = model.guide.hint(selfView: model.isFront) {
                HintPill(text: hint)
            }
            Spacer(minLength: 0)
            if model.zoomLabels.count > 1 {
                HStack(spacing: 6) {
                    Spacer(minLength: 0)
                    ForEach(model.zoomLabels.indices, id: \.self) { i in
                        Button(model.zoomLabels[i]) { model.setZoom(i) }
                            .buttonStyle(StagePillStyle(on: i == model.zoomIndex))
                            .accessibilityAddTraits(i == model.zoomIndex ? .isSelected : [])
                    }
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 4)
        .padding(.bottom, 24)
    }

    private func openSettings() {
        #if canImport(UIKit)
        if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
        #endif
    }

    // MARK: 종이

    private var hero: Token? {
        if case .token(let id) = model.latest { return model.token(id) }
        return nil
    }

    private var sheet: some View {
        VStack(alignment: .leading, spacing: 0) {
            if typeSize.isAccessibilitySize {
                // 아주 큰 글자에서는 무대 위 표시를 글 줄로 옮겨 사람 도식을 가리지 않게 한다
                Legend(rightSeen: model.rightVisible, leftSeen: model.leftVisible, leftFirst: model.isFront, onPaper: true)
                if let hint = model.guide.hint(selfView: model.isFront), model.setup == .ready, !model.nobody {
                    Text(hint).font(.app(.footnote, .semibold)).foregroundStyle(Theme.ink2)
                }
            }
            FitOrScroll(alignment: model.latest == nil && !model.isReading && model.tokens.isEmpty ? .leading : .topLeading) {
                written
            }
            LaneView(phase: lane, showMinimum: !typeSize.isAccessibilitySize,
                     note: model.tooShort ? "너무 짧아요. 0.5초가 지난 뒤에 끝내 주세요" : nil)
                .padding(.top, 6)
            ReadButton(isOn: model.isReading, action: model.toggleRead)
                .disabled(blocked && !model.isReading)
                .frame(maxWidth: .infinity)
                .frame(height: 80)
                .padding(.bottom, 6)
        }
    }

    @ViewBuilder
    private var written: some View {
        VStack(alignment: .leading, spacing: 0) {
            if model.isReading {
                Text("읽는 중")
                    .font(.app(.title2, .bold))
                    .foregroundStyle(Theme.ink2)
                    .padding(.top, 10)
                Text("단추를 다시 누르면 괄호가 닫히고 낱말이 적혀요.")
                    .font(.app(.subheadline))
                    .foregroundStyle(Theme.ink2)
                    .padding(.top, 8)
            } else {
                if !model.tokens.isEmpty { history }
                switch model.latest {
                case .token:
                    if let hero { result(hero) }
                case .unread(let outcome, let seconds):
                    unread(outcome, seconds: seconds)
                case nil:
                    guidance
                }
            }
        }
    }

    /// 아직 읽은 것이 없을 때의 안내
    private var guidance: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("단추를 눌러 시작하고,\n다시 눌러 끝내세요")
                .font(.app(.title2, .bold))
                .foregroundStyle(Theme.ink)
            Text("3초가 지나면 저절로 끝납니다. 영상은 저장하지 않고, 손과 몸의 점만 읽습니다.")
                .font(.app(.subheadline))
                .foregroundStyle(Theme.ink2)
            if !model.words.isEmpty {
                Text("읽을 수 있는 낱말: " + model.words.joined(separator: " · "))
                    .font(.app(.footnote))
                    .foregroundStyle(Theme.ink2)
            }
        }
        .padding(.vertical, 8)
    }

    /// 읽은 낱말들. 지금 크게 보이는 낱말은 빼고 늘어놓는다
    private var history: some View {
        let past = model.tokens.filter { $0.id != hero?.id }
        let title = Text("읽은 수어").font(.app(.headline)).foregroundStyle(Theme.ink)
        let clear = Button("지우기", action: model.clear).buttonStyle(TextButtonStyle()).padding(.trailing, -10)
        // 왼쪽부터 늘어놓고, 넘치면 가장 최근 낱말이 보이게 끝으로 민다
        let row = ScrollViewReader { proxy in
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    ForEach(past) { token in
                        Button { open(token) } label: {
                            Gloss(token.word, style: .body, weight: .semibold, tone: token.sure ? .normal : .unsure)
                                .frame(minHeight: 44)
                        }
                        .buttonStyle(PressScale())
                        .id(token.id)
                    }
                }
                .padding(.horizontal, 10)
            }
            .onAppear { proxy.scrollTo(past.last?.id, anchor: .trailing) }
            .onChange(of: past.last?.id) { _, last in proxy.scrollTo(last, anchor: .trailing) }
        }

        return Group {
            if typeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 0) {
                    HStack { title; Spacer(minLength: 0); clear }
                    if !past.isEmpty { row.padding(.horizontal, -10) }
                }
            } else {
                HStack(spacing: 0) { title; row; clear }
            }
        }
        .frame(minHeight: 44)
    }

    private func result(_ token: Token) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { heroButton(token); Spacer(minLength: 0); status(token) }
                VStack(alignment: .leading, spacing: 0) { heroButton(token); status(token) }
            }
            .frame(minHeight: 58)
            if token.sure {
                Text(tipSeen ? " " : "낱말을 누르면 자세히 볼 수 있어요.")
                    .font(.app(.subheadline))
                    .foregroundStyle(Theme.ink2)
                    .frame(minHeight: 48, alignment: .leading)
            } else {
                // 확실하지 않을 때는 고칠 길을 바로 옆에 둔다
                FlowLayout(spacing: 8) {
                    Button(token.word) { model.setWord(token.word, for: token.id) }
                        .buttonStyle(ChipStyle(primary: true))
                        .accessibilityHint("이 낱말이 맞다고 확인합니다")
                    ForEach(token.reading.alternatives, id: \.self) { word in
                        Button(word) { model.setWord(word, for: token.id) }
                            .buttonStyle(ChipStyle())
                    }
                    Button("다시 읽기") { model.remove(token.id) }
                        .buttonStyle(TextButtonStyle())
                }
                .frame(minHeight: 48, alignment: .leading)
            }
        }
    }

    private func heroButton(_ token: Token) -> some View {
        Button { open(token) } label: {
            Gloss(token.word, tone: token.sure ? .normal : .unsure)
                .dynamicTypeSize(...DynamicTypeSize.accessibility1)
                .frame(minHeight: 52)
        }
        .buttonStyle(PressScale(scale: 0.98))
        .accessibilityHint("자세히 봅니다")
    }

    private func status(_ token: Token) -> some View {
        Group {
            if token.sure {
                Text(token.corrected ? token.reading.seconds.secondsText
                     : "\(token.reading.seconds.secondsText) · \(token.reading.top.probability.percentText)")
                    .foregroundStyle(Theme.ink2)
            } else {
                Text("확실하지 않아요 · \(token.reading.top.probability.percentText)")
                    .fontWeight(.semibold)
                    .foregroundStyle(Theme.warn)
            }
        }
        .font(.app(.subheadline))
        .monospacedDigit()
    }

    private func unread(_ outcome: Reading.Outcome, seconds: Double) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                Gloss("?", tone: .muted).dynamicTypeSize(...DynamicTypeSize.accessibility1)
                Spacer(minLength: 0)
                Text(seconds.secondsText).font(.app(.subheadline)).monospacedDigit().foregroundStyle(Theme.ink2)
            }
            .frame(minHeight: 58)
            Text(outcome == .handsUnseen
                 ? "손이 잘 보이지 않아 읽지 못했어요. 더 가까이에서 다시 눌러 주세요."
                 : "아는 낱말과 맞지 않아요. 지금은 \(model.words.joined(separator: "·"))만 읽을 수 있어요.")
                .font(.app(.subheadline))
                .foregroundStyle(Theme.ink2)
                .frame(minHeight: 48, alignment: .topLeading)
        }
    }

    private var lane: LaneView.Phase {
        if model.isReading { return .open(seconds: model.elapsed) }
        switch model.latest {
        case .token:
            guard let hero else { return .waiting }
            return .closed(seconds: hero.reading.seconds, word: hero.word, tone: hero.sure ? .normal : .unsure)
        case .unread(_, let seconds):
            return .closed(seconds: seconds, word: "?", tone: .muted)
        case nil:
            return .waiting
        }
    }

    private func open(_ token: Token) {
        tipSeen = true
        detail = token
    }

    private func announce(_ latest: BoardModel.Latest?) {
        let text: String? = switch latest {
        case .token(let id): model.token(id).map { $0.sure ? $0.word : "\($0.word), 확실하지 않아요" }
        case .unread: "읽지 못했어요"
        case nil: nil
        }
        if let text { AccessibilityNotification.Announcement(text).post() }
    }
}
