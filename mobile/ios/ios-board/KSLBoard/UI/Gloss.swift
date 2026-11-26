import SwiftUI

/// 각진 대괄호 한쪽
struct BracketShape: Shape {
    var right = false

    func path(in r: CGRect) -> Path {
        var p = Path()
        let open = right ? r.minX : r.maxX, closed = right ? r.maxX : r.minX
        p.move(to: CGPoint(x: open, y: r.minY))
        p.addLine(to: CGPoint(x: closed, y: r.minY))
        p.addLine(to: CGPoint(x: closed, y: r.maxY))
        p.addLine(to: CGPoint(x: open, y: r.maxY))
        return p
    }
}

/// 글로스: 읽은 수어 낱말을 대괄호 안에 적는다. 낱말 하나가 대괄호 하나다
struct Gloss: View {
    enum Tone {
        case normal     // 읽은 낱말
        case unsure     // 확실하지 않음: 점선 괄호와 물음표
        case muted      // 못 읽음, 아직 안 읽은 목표 낱말
    }

    let word: String
    let style: Font.TextStyle
    let weight: Font.Weight
    let tone: Tone
    @ScaledMetric private var em: CGFloat

    init(_ word: String, style: Font.TextStyle = .largeTitle, weight: Font.Weight = .bold, tone: Tone = .normal) {
        self.word = word
        self.style = style
        self.weight = weight
        self.tone = tone
        _em = ScaledMetric(wrappedValue: Theme.baseSize(style), relativeTo: style)
    }

    private var bracketColor: Color {
        switch tone {
        case .normal: Theme.tint
        case .unsure: Theme.warn
        case .muted: Theme.ink3
        }
    }

    var body: some View {
        let stroke = max(1.5, em * 0.095)
        HStack(spacing: em * 0.26) {
            bracket(right: false, stroke: stroke)
            HStack(spacing: 0) {
                Text(word).foregroundStyle(tone == .muted ? Theme.ink3 : Theme.ink)
                if tone == .unsure { Text("?").foregroundStyle(Theme.warn) }
            }
            .font(.app(style, weight))
            .tracking(-em * 0.02)
            .lineLimit(1)
            bracket(right: true, stroke: stroke)
        }
        .fixedSize()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(tone == .unsure ? "\(word), 확실하지 않음" : word == "?" ? "읽지 못함" : word)
    }

    private func bracket(right: Bool, stroke: CGFloat) -> some View {
        BracketShape(right: right)
            .stroke(bracketColor, style: StrokeStyle(lineWidth: stroke, lineCap: .butt, lineJoin: .miter,
                                                     dash: tone == .unsure ? [stroke * 1.9, stroke * 1.3] : []))
            .padding(stroke / 2)
            .frame(width: em * 0.24 + stroke, height: em * 1.3)
    }
}

/// 진도: 작은 대괄호 셋. 알아본 만큼 가운데를 채운다
struct Marks: View {
    let count: Int
    var total = ProgressStore.goal

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<total, id: \.self) { i in
                Canvas { ctx, size in
                    let on = i < count
                    let stroke: CGFloat = 1.6
                    let color = on ? Theme.tint : Theme.ink3.opacity(0.75)
                    let box = CGRect(origin: .zero, size: size).insetBy(dx: stroke / 2, dy: stroke / 2)
                    let arm: CGFloat = 4 - stroke / 2
                    var p = BracketShape().path(in: CGRect(x: box.minX, y: box.minY, width: arm, height: box.height))
                    p.addPath(BracketShape(right: true).path(in: CGRect(x: box.maxX - arm, y: box.minY, width: arm, height: box.height)))
                    ctx.stroke(p, with: .color(color), style: StrokeStyle(lineWidth: stroke, lineJoin: .miter))
                    if on {
                        ctx.fill(Path(CGRect(x: (size.width - 5) / 2, y: (size.height - 7) / 2, width: 5, height: 7)), with: .color(Theme.tint))
                    }
                }
                .frame(width: 13, height: 15)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("세 번 가운데 \(min(count, total))번 알아봄")
    }
}

/// 읽기 단추와 번역 탭에 쓰는 대괄호 한 쌍
struct BracketPair: Shape {
    func path(in r: CGRect) -> Path {
        let arm = r.width * 0.17
        var p = BracketShape().path(in: CGRect(x: r.minX, y: r.minY, width: arm, height: r.height))
        p.addPath(BracketShape(right: true).path(in: CGRect(x: r.maxX - arm, y: r.minY, width: arm, height: r.height)))
        return p
    }
}

#if os(iOS)
import UIKit

enum TabIcon {
    /// 번역 탭 그림: 점 셋이 든 대괄호 (SF Symbols에 없어서 직접 그린다)
    static let translate: UIImage = {
        let size = CGSize(width: 26, height: 26)
        let image = UIGraphicsImageRenderer(size: size).image { ctx in
            let box = CGRect(x: 3, y: 4, width: 20, height: 18)
            ctx.cgContext.setLineWidth(2)
            ctx.cgContext.setLineCap(.square)
            ctx.cgContext.setLineJoin(.miter)
            ctx.cgContext.setStrokeColor(UIColor.black.cgColor)
            ctx.cgContext.setFillColor(UIColor.black.cgColor)
            ctx.cgContext.addPath(BracketPair().path(in: box).cgPath)
            ctx.cgContext.strokePath()
            for k in [-1.0, 0.0, 1.0] {
                ctx.cgContext.fillEllipse(in: CGRect(x: box.midX + k * 3.6 - 1.2, y: box.midY - 1.2, width: 2.4, height: 2.4))
            }
        }
        return image.withRenderingMode(.alwaysTemplate)
    }()
}
#endif
