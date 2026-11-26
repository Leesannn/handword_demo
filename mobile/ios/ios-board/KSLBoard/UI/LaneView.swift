import SwiftUI

/// 시간 줄(0~3초). 읽기를 시작하면 괄호가 0에서 열려 시간만큼 늘어나고,
/// 끝나면 그 자리에서 닫히며 안에 낱말이 적힌다. 닫힌 괄호는 다음에 읽을 때까지 잰 길이대로 남는다
struct LaneView: View {
    enum Phase: Equatable {
        case waiting
        case open(seconds: Double)
        case closed(seconds: Double, word: String, tone: Gloss.Tone)
    }

    let phase: Phase
    /// '최소 0.5' 눈금 글자를 적을지 (따라 하기와 아주 큰 글자에서는 뺀다)
    var showMinimum = true
    /// 너무 짧게 끝났을 때의 안내
    var note: String?

    @ScaledMetric(relativeTo: .caption2) private var numbersHeight: CGFloat = 14
    @ScaledMetric(relativeTo: .footnote) private var noteHeight: CGFloat = 19
    private static let total = SignSpec.maxDuration
    private static let stroke: CGFloat = 3

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(note ?? " ")
                .font(.app(.footnote, .semibold))
                .foregroundStyle(Theme.bad)
                .frame(minHeight: noteHeight, alignment: .bottomLeading)
                .accessibilityHidden(note == nil)
            VStack(alignment: .leading, spacing: 0) {
                GeometryReader { geo in track(width: geo.size.width) }
                    .frame(height: 44)
                ticks.frame(height: 7)
                numbers.frame(height: numbersHeight).padding(.top, 3)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("시간 줄")
            .accessibilityValue(spoken)
        }
    }

    private var spoken: String {
        switch phase {
        case .waiting: "기다리는 중"
        case .open(let seconds): "읽는 중, \(seconds.secondsText)"
        case .closed(let seconds, let word, let tone):
            (word == "?" ? "읽지 못함" : tone == .unsure ? "\(word), 확실하지 않음" : word) + ", \(seconds.secondsText)"
        }
    }

    // MARK: 괄호가 놓이는 줄

    private func track(width: CGFloat) -> some View {
        ZStack(alignment: .topLeading) {
            // 바닥 줄. 0~0.5초는 점선이다 (이보다 짧으면 읽지 않는다)
            Canvas { ctx, size in
                let y = size.height - 0.75
                var dashed = Path()
                dashed.move(to: CGPoint(x: 0, y: y))
                dashed.addLine(to: CGPoint(x: size.width / 6, y: y))
                var solid = Path()
                solid.move(to: CGPoint(x: size.width / 6, y: y))
                solid.addLine(to: CGPoint(x: size.width, y: y))
                ctx.stroke(dashed, with: .color(Theme.sep), style: StrokeStyle(lineWidth: 1.5, dash: [3, 3]))
                ctx.stroke(solid, with: .color(Theme.sep), lineWidth: 1.5)
            }
            bracket(width: width)
                .frame(height: 36, alignment: .leading)
                .offset(y: 2)
        }
    }

    @ViewBuilder
    private func bracket(width: CGFloat) -> some View {
        switch phase {
        case .waiting:
            HStack(spacing: 8) {
                side(right: false, color: Theme.tint)
                Caret().frame(width: Self.stroke)
            }
        case .open(let seconds):
            let short = seconds < SignSpec.minDuration
            let color = short ? Theme.ink3 : Theme.tint
            let length = max(12, width * min(seconds, Self.total) / Self.total)
            ZStack(alignment: .leading) {
                Rectangle().fill(short ? Theme.fill : Theme.tintSoft)
                side(right: false, color: color)
                Rectangle().fill(color).frame(width: Self.stroke)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            .frame(width: length)
            .overlay(alignment: .leading) {
                Text(seconds.secondsText)
                    .font(.app(.footnote, .bold))
                    .monospacedDigit()
                    .foregroundStyle(color)
                    .fixedSize()
                    .dynamicTypeSize(...DynamicTypeSize.xxLarge)
                    .contentTransition(.identity)
                    .offset(x: length + 8)
            }
            .animation(.linear(duration: 1 / SignSpec.targetFPS), value: seconds)
        case .closed(let seconds, let word, let tone):
            let color = tone == .normal ? Theme.tint : tone == .unsure ? Theme.warn : Theme.ink3
            let length = max(24, width * min(seconds, Self.total) / Self.total)
            ZStack(alignment: .leading) {
                HStack(spacing: 0) {
                    side(right: false, color: color, dashed: tone == .unsure)
                    Spacer(minLength: 0)
                    side(right: true, color: color, dashed: tone == .unsure)
                }
                ViewThatFits(in: .horizontal) {
                    // 괄호 안에 적는다
                    written(word, tone).padding(.horizontal, 15)
                    // 괄호가 짧으면 바로 뒤에 적는다
                    Color.clear.frame(width: 1, height: 1)
                        .overlay(alignment: .leading) { written(word, tone).offset(x: length + 8) }
                }
            }
            .frame(width: length)
            .id("\(word)-\(seconds)")
        }
    }

    private func side(right: Bool, color: Color, dashed: Bool = false) -> some View {
        BracketShape(right: right)
            .stroke(color, style: StrokeStyle(lineWidth: Self.stroke, lineJoin: .miter, dash: dashed ? [6, 4] : []))
            .padding(Self.stroke / 2)
            .frame(width: 12)
    }

    private func written(_ word: String, _ tone: Gloss.Tone) -> some View {
        HStack(spacing: 0) {
            Text(word).foregroundStyle(tone == .muted ? Theme.ink3 : Theme.ink)
            if tone == .unsure { Text("?").foregroundStyle(Theme.warn) }
        }
        .font(.app(.title3, .bold))
        .tracking(-0.4)
        .lineLimit(1)
        .fixedSize()
        .dynamicTypeSize(...DynamicTypeSize.large)
        .modifier(Reveal())
    }

    // MARK: 눈금

    private var ticks: some View {
        Canvas { ctx, size in
            for k in 0...6 {
                let major = k % 2 == 0
                let x = (size.width * CGFloat(k) / 6).clamped(0.75, size.width - 0.75)
                var p = Path()
                p.move(to: CGPoint(x: x, y: 0))
                p.addLine(to: CGPoint(x: x, y: major ? 7 : 4))
                ctx.stroke(p, with: .color(Theme.ink3.opacity(major ? 1 : 0.7)), lineWidth: 1.5)
            }
        }
    }

    private var numbers: some View {
        GeometryReader { geo in
            let w = geo.size.width
            ZStack(alignment: .topLeading) {
                number("0").frame(width: 40, alignment: .leading)
                if showMinimum { number("최소 0.5").frame(width: 80).offset(x: w / 6 - 40) }
                number("1").frame(width: 40).offset(x: w / 3 - 20)
                number("2").frame(width: 40).offset(x: w * 2 / 3 - 20)
                number("3초").frame(width: 40, alignment: .trailing).offset(x: w - 40)
            }
        }
    }

    private func number(_ text: String) -> some View {
        Text(text)
            .font(.app(.caption2))
            .monospacedDigit()
            .foregroundStyle(Theme.ink3)
            .lineLimit(1)
            .fixedSize()
            .dynamicTypeSize(...DynamicTypeSize.xxLarge)
    }
}

/// 움직임을 멈춘 그림이 필요할 때(화면을 뽑아 볼 때) 켠다
private struct StillKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    var still: Bool {
        get { self[StillKey.self] }
        set { self[StillKey.self] = newValue }
    }
}

/// 빈 괄호 옆에서 깜빡이는 줄
private struct Caret: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.still) private var still

    var body: some View {
        if reduceMotion || still {
            Rectangle().fill(Theme.tint)
        } else {
            TimelineView(.periodic(from: Date(timeIntervalSinceReferenceDate: 0), by: 0.55)) { context in
                Rectangle().fill(Theme.tint)
                    .opacity(Int(context.date.timeIntervalSinceReferenceDate / 0.55) % 2 == 0 ? 1 : 0)
            }
        }
    }
}

/// 낱말이 왼쪽에서부터 적히듯 나타난다
struct Reveal: ViewModifier {
    @State private var shown = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.still) private var still

    func body(content: Content) -> some View {
        content
            .mask(alignment: .leading) {
                Rectangle().scaleEffect(x: shown || still ? 1 : 0, anchor: .leading)
            }
            .onAppear {
                if reduceMotion || still {
                    shown = true
                } else {
                    withAnimation(Theme.ease) { shown = true }
                }
            }
    }
}
