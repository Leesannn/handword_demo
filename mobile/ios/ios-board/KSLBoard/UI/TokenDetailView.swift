import SwiftUI

/// 낱말 자세히: 읽는 동안 낱말·오른손·왼손·몸이 보인 구간을 한 시간 줄에 놓아 보여 주고, 고치거나 지울 수 있다
struct TokenDetailView: View {
    let model: BoardModel
    let tokenID: UUID
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            if let token = model.token(tokenID) {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 12) {
                        Gloss(token.word, style: .title, tone: token.sure ? .normal : .unsure)
                            .dynamicTypeSize(...DynamicTypeSize.accessibility1)
                        Spacer(minLength: 0)
                        Button("완료") { dismiss() }
                            .buttonStyle(TextButtonStyle(strong: true))
                            .padding(.trailing, -10)
                    }
                    .frame(minHeight: 56)
                    .padding(.horizontal, 4)

                    TiersPlate(word: token.word, reading: token.reading)
                    facts(token)
                    fix(token)

                    Button("이 낱말 지우기", role: .destructive) {
                        model.remove(token.id)
                        dismiss()
                    }
                    .buttonStyle(RowButtonStyle())
                    .padding(.top, 14)
                }
                .padding(.horizontal, 16)
                .padding(.top, 18)
                .padding(.bottom, 24)
            }
        }
        .background(Theme.bgGrouped)
    }

    private func facts(_ token: Token) -> some View {
        let reading = token.reading
        var rows = [
            ("걸린 시간", reading.seconds.secondsText),
            ("오른손이 보인 시간", Float(Reading.ratio(reading.rightSeen)).percentText),
            ("왼손이 보인 시간", Float(Reading.ratio(reading.leftSeen)).percentText),
        ]
        rows.append(token.corrected
                    ? ("처음 읽은 낱말", "\(reading.top.word) \(reading.top.probability.percentText)")
                    : ("확률", reading.top.probability.percentText))
        return VStack(spacing: 0) {
            ForEach(rows.indices, id: \.self) { i in
                if i > 0 { Rectangle().fill(Theme.sep).frame(height: 0.6).padding(.leading, 16) }
                HStack(spacing: 12) {
                    Text(rows[i].0).foregroundStyle(Theme.ink)
                    Spacer(minLength: 0)
                    Text(rows[i].1).monospacedDigit().foregroundStyle(Theme.ink2)
                }
                .font(.app(.body))
                .padding(.horizontal, 16)
                .frame(minHeight: 48)
                .accessibilityElement(children: .combine)
            }
        }
        .background(Theme.bgRow, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .padding(.top, 12)
    }

    /// 다른 낱말로 고치기: 모델이 그럴듯하다고 본 순서로 늘어놓는다
    @ViewBuilder
    private func fix(_ token: Token) -> some View {
        let others = token.reading.ranking.map(\.word).filter { $0 != Reading.other && $0 != token.word }
        if !others.isEmpty {
            Text("다른 낱말로 고치기")
                .font(.app(.headline))
                .foregroundStyle(Theme.ink)
                .padding(.horizontal, 4)
                .padding(.top, 22)
                .padding(.bottom, 2)
            FlowLayout(spacing: 8) {
                ForEach(others, id: \.self) { word in
                    Button(word) { model.setWord(word, for: token.id) }
                        .buttonStyle(ChipStyle(onRow: true))
                }
            }
        }
    }
}

/// 칠판 판 위의 네 줄: 낱말(괄호), 오른손(채운 노랑), 왼손(빈 하늘색), 몸(분필 흰색). 같은 시간 축을 쓴다
struct TiersPlate: View {
    let word: String
    let reading: Reading

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 9) {
            GridRow {
                label("낱말")
                Text(word)
                    .font(.app(.footnote, .bold))
                    .foregroundStyle(Theme.chalk)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, minHeight: 26)
                    .overlay {
                        HStack(spacing: 0) {
                            BracketShape().stroke(Theme.chalk, style: StrokeStyle(lineWidth: 2.2, lineJoin: .miter)).padding(1.1).frame(width: 9)
                            Spacer(minLength: 0)
                            BracketShape(right: true).stroke(Theme.chalk, style: StrokeStyle(lineWidth: 2.2, lineJoin: .miter)).padding(1.1).frame(width: 9)
                        }
                    }
            }
            GridRow { label("오른손"); bars(reading.rightSeen, kind: .right) }
            GridRow { label("왼손"); bars(reading.leftSeen, kind: .left) }
            GridRow { label("몸"); bars(reading.bodySeen, kind: .body) }
            GridRow {
                Color.clear.frame(width: 1, height: 1)
                axis
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 16)
        .padding(.bottom, 10)
        .background(Theme.board, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("읽는 동안 보인 구간")
        .accessibilityValue("오른손 \(Float(Reading.ratio(reading.rightSeen)).percentText), 왼손 \(Float(Reading.ratio(reading.leftSeen)).percentText)")
    }

    private enum Kind { case right, left, body }

    private func label(_ text: String) -> some View {
        Text(text)
            .font(.app(.caption, .semibold))
            .foregroundStyle(Theme.chalk)
            .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
    }

    /// 보인 프레임이 이어진 구간마다 막대 하나
    private func bars(_ seen: [Bool], kind: Kind) -> some View {
        Canvas { ctx, size in
            ctx.fill(Path(roundedRect: CGRect(x: 0, y: size.height / 2 - 1, width: size.width, height: 2), cornerRadius: 1),
                     with: .color(.white.opacity(0.16)))
            guard !seen.isEmpty else { return }
            let step = size.width / CGFloat(seen.count)
            var start: Int?
            for i in 0...seen.count {
                let on = i < seen.count && seen[i]
                if on, start == nil { start = i }
                guard !on, let s = start else { continue }
                start = nil
                let rect = CGRect(x: CGFloat(s) * step, y: 0, width: max(3, CGFloat(i - s) * step), height: size.height)
                switch kind {
                case .right:
                    ctx.fill(Path(roundedRect: rect, cornerRadius: 3), with: .color(Theme.rightHand))
                case .left:
                    ctx.fill(Path(roundedRect: rect, cornerRadius: 3), with: .color(Theme.board))
                    ctx.stroke(Path(roundedRect: rect.insetBy(dx: 0.9, dy: 0.9), cornerRadius: 2.4), with: .color(Theme.leftHand), lineWidth: 1.8)
                case .body:
                    ctx.fill(Path(roundedRect: rect, cornerRadius: 3), with: .color(Theme.chalk))
                }
            }
        }
        .frame(height: 14)
    }

    /// 눈금: 0.5초마다 짧은 줄, 1초마다 긴 줄과 숫자
    private var axis: some View {
        Canvas { ctx, size in
            let seconds = max(reading.seconds, 0.5)
            var k = 0
            while Double(k) * 0.5 <= seconds + 0.001 {
                let major = k % 2 == 0
                let x = (size.width * CGFloat(Double(k) * 0.5 / seconds)).clamped(0.6, size.width - 0.6)
                var p = Path()
                p.move(to: CGPoint(x: x, y: 0))
                p.addLine(to: CGPoint(x: x, y: major ? 7 : 4))
                ctx.stroke(p, with: .color(Theme.chalk2), lineWidth: 1.2)
                if major {
                    let text = Text(k == 0 ? "0" : "\(k / 2)초").font(.app(.caption2)).foregroundStyle(Theme.chalk2)
                    ctx.draw(text, at: CGPoint(x: x, y: 10), anchor: k == 0 ? .topLeading : .top)
                }
                k += 1
            }
        }
        .frame(height: 24)
    }
}
