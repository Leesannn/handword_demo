import SwiftUI

// MARK: 단추

struct PressScale: ButtonStyle {
    var scale: CGFloat = 0.96

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? scale : 1)
            .animation(Theme.ease, value: configuration.isPressed)
    }
}

/// 읽기 단추. 누르면 읽기 시작하고, 다시 누르면 끝난다 (수어에는 두 손이 필요해서 누르고 있지 않는다)
struct ReadButton: View {
    let isOn: Bool
    let action: () -> Void
    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle().fill(Theme.tint)
                    .frame(width: 72, height: 72)
                    // 읽는 동안에는 단추 둘레에 옅은 고리를 두른다 (자리는 차지하지 않는다)
                    .background {
                        Circle().fill(Theme.tintSoft).frame(width: 90, height: 90).opacity(isOn ? 1 : 0)
                    }
                if isOn {
                    Image(systemName: "stop.fill")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Theme.onTint)
                } else {
                    BracketPair()
                        .stroke(Theme.onTint, style: StrokeStyle(lineWidth: 2.6, lineCap: .square, lineJoin: .miter))
                        .frame(width: 20, height: 20)
                }
            }
            .frame(width: 72, height: 72)
            .animation(Theme.ease, value: isOn)
        }
        .buttonStyle(PressScale(scale: 0.94))
        .opacity(isEnabled ? 1 : 0.4)
        .accessibilityLabel(isOn ? "읽기 끝내기" : "읽기 시작")
        .accessibilityHint(isOn ? "" : "다시 누르면 끝납니다. 3초가 지나면 저절로 끝납니다")
    }
}

/// 낱말 칩 (후보 고르기, 고치기)
struct ChipStyle: ButtonStyle {
    var primary = false
    var onRow = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.app(.subheadline, .semibold))
            .foregroundStyle(primary ? Theme.onTint : Theme.ink)
            .lineLimit(1)
            .padding(.horizontal, 14)
            .frame(minHeight: 36)
            .background(primary ? Theme.tint : onRow ? Theme.bgRow : Theme.fill, in: Capsule())
            .frame(minHeight: 44)
            .contentShape(Rectangle())
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(Theme.ease, value: configuration.isPressed)
    }
}

/// 화면에서 가장 중요한 단추 (따라 하기, 시작)
struct CTAStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.app(.body, .semibold))
            .foregroundStyle(Theme.onTint)
            .padding(.horizontal, 20)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(Theme.tint, in: Capsule())
            .opacity(isEnabled ? 1 : 0.42)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(Theme.ease, value: configuration.isPressed)
    }
}

/// 글자만 있는 단추 (마치기, 다시 읽기, 완료)
struct TextButtonStyle: ButtonStyle {
    /// 화면 너비를 다 쓰는 굵은 글자 (마치기)
    var wide = false
    /// 본문 크기의 굵은 글자 (완료)
    var strong = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.app(wide || strong ? .body : .subheadline, wide || strong ? .semibold : .regular))
            .foregroundStyle(Theme.tint)
            .padding(.horizontal, 10)
            .frame(maxWidth: wide ? .infinity : nil, minHeight: wide ? 48 : 44)
            .contentShape(Rectangle())
            .opacity(configuration.isPressed ? 0.5 : 1)
    }
}

/// 묶음 목록의 한 줄처럼 생긴 단추 (이 낱말 지우기)
struct RowButtonStyle: ButtonStyle {
    var color = Theme.bad

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.app(.body))
            .foregroundStyle(color)
            .frame(maxWidth: .infinity, minHeight: 50)
            .background(configuration.isPressed ? Theme.fill : Theme.bgRow, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}

/// 칠판 위의 둥근 단추 (카메라 바꾸기, 닫기).
/// 칠판 위 단추와 표시는 옅은 흰색 아래에 칠판 색을 한 겹 깔아, 뒤에 그린 선이 비치지 않게 한다
struct GlassCircleStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(Theme.chalk)
            .frame(width: 44, height: 44)
            .background(Color.white.opacity(configuration.isPressed ? 0.24 : 0.14), in: Circle())
            .background(Theme.board, in: Circle())
            .scaleEffect(configuration.isPressed ? 0.94 : 1)
            .animation(Theme.ease, value: configuration.isPressed)
    }
}

/// 칠판 위의 알약 단추 (느리게, 거울로 보기, 0.5×). 켜지면 분필 색으로 채운다
struct StagePillStyle: ButtonStyle {
    var on = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.app(.footnote, .semibold))
            .foregroundStyle(on ? Theme.onChalk : Theme.chalk)
            .lineLimit(1)
            .padding(.horizontal, 13)
            .frame(minWidth: 44, minHeight: 36)
            .background(on ? Theme.chalk : Color.white.opacity(configuration.isPressed ? 0.24 : 0.14), in: Capsule())
            .background(Theme.board, in: Capsule())
            .frame(minHeight: 44)
            .contentShape(Rectangle())
            .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
    }
}

// MARK: 칠판 위의 표시

/// 손 표시: 오른손은 채운 노란 점, 왼손은 빈 하늘색 고리. 손이 안 보이면 그렇다고 적는다
struct Legend: View {
    let rightSeen: Bool
    let leftSeen: Bool
    /// 거울처럼 보이는 화면(전면 카메라)에서는 왼손이 화면 왼쪽에 오므로 왼손을 먼저 적는다
    var leftFirst = false
    /// 시트 안에 글 줄로 놓을 때 (아주 큰 글자). 칠판 색 네모 안에 표시를 그려 색이 묻히지 않게 한다
    var onPaper = false

    var body: some View {
        let row = HStack(spacing: onPaper ? 16 : 14) {
            item(right: !leftFirst, seen: leftFirst ? leftSeen : rightSeen)
            item(right: leftFirst, seen: leftFirst ? rightSeen : leftSeen)
        }
        .font(.app(.footnote, .semibold))
        .accessibilityElement(children: .combine)

        if onPaper {
            row
        } else {
            row
                .padding(.horizontal, 14)
                .frame(minHeight: 36)
                .background(Theme.boardGlass, in: Capsule())
                .background(Theme.board, in: Capsule())
                .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
        }
    }

    private func item(right: Bool, seen: Bool) -> some View {
        HStack(spacing: 6) {
            ZStack {
                if onPaper { RoundedRectangle(cornerRadius: 5).fill(Theme.board).frame(width: 18, height: 18) }
                if right {
                    Circle().fill(Theme.rightHand).frame(width: 11, height: 11)
                } else {
                    Circle().strokeBorder(Theme.leftHand, lineWidth: 2).frame(width: 11, height: 11)
                }
            }
            .opacity(seen || onPaper ? 1 : 0.45)
            Text((right ? "오른손" : "왼손") + (seen ? "" : " 안 보임"))
                .foregroundStyle(onPaper ? (seen ? Theme.ink2 : Theme.ink3) : (seen ? Theme.chalk : Theme.chalk2))
                .lineLimit(1)
        }
    }
}

/// 자리 안내 한 줄 ("조금 더 가까이 비춰 주세요")
struct HintPill: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.app(.footnote, .bold))
            .foregroundStyle(Theme.onChalk)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(Theme.chalk, in: Capsule())
            .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
    }
}

/// 사람 도식 대신 칠판 가운데에 적는 말 (사람이 안 보임, 카메라를 쓸 수 없음, 본보기 없음)
struct StageMessage: View {
    let title: String
    let detail: String
    var actionTitle: String?
    var action: (() -> Void)?

    var body: some View {
        VStack(spacing: 8) {
            Text(title)
                .font(.app(.title3, .bold))
                .foregroundStyle(Theme.chalk)
            Text(detail)
                .font(.app(.subheadline))
                .foregroundStyle(Theme.chalk2)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(ChalkButtonStyle())
                    .padding(.top, 8)
            }
        }
        .multilineTextAlignment(.center)
        .padding(.horizontal, 28)
        .dynamicTypeSize(...DynamicTypeSize.accessibility1)
    }
}

struct ChalkButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.app(.subheadline, .bold))
            .foregroundStyle(Theme.onChalk)
            .padding(.horizontal, 18)
            .frame(minHeight: 44)
            .background(Theme.chalk, in: Capsule())
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
    }
}

extension GuideStatus {
    /// 자리 안내 문구. front가 true면 자기 모습을 보는 중(따라 하기), 아니면 남을 비추는 중일 수 있다
    func hint(selfView: Bool) -> String? {
        switch self {
        case .ok, .noPerson: nil
        case .closer: selfView ? "조금 더 가까이 서 주세요" : "조금 더 가까이 비춰 주세요"
        case .farther: selfView ? "조금 더 뒤로 가 주세요" : "조금 더 멀리서 비춰 주세요"
        case .moveLeft, .moveRight: selfView ? "화면 가운데에 서 주세요" : "사람이 가운데에 오게 비춰 주세요"
        }
    }
}

// MARK: 시트와 배치

/// 칠판 무대 아래에서 올라오는 종이. 높이는 부르는 쪽에서 고정한다 (낱말이 적혀도 무대와의 경계가 움직이지 않게)
struct BoardSheet<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(.top, 12)
            .padding(.horizontal, 20)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background {
                UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28, style: .continuous)
                    .fill(Theme.bg)
                    .ignoresSafeArea(edges: .bottom)
            }
    }
}

/// 내용이 자리에 들어가면 그대로 두고, 넘칠 때만 스크롤한다
struct FitOrScroll<Content: View>: View {
    var alignment: Alignment = .topLeading
    @ViewBuilder var content: Content

    var body: some View {
        ViewThatFits(in: .vertical) {
            content.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: alignment)
            ScrollView { content.frame(maxWidth: .infinity, alignment: .leading) }
        }
    }
}

/// 칩처럼 폭이 제각각인 것을 줄바꿈하며 늘어놓는다
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(width: proposal.width ?? .infinity, subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let placed = arrange(width: bounds.width, subviews)
        for (i, origin) in placed.origins.enumerated() {
            subviews[i].place(at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y), proposal: .unspecified)
        }
    }

    private func arrange(width: CGFloat, _ subviews: Subviews) -> (size: CGSize, origins: [CGPoint]) {
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        var origins: [CGPoint] = []
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                x = 0
                y += rowHeight
                rowHeight = 0
            }
            origins.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            widest = max(widest, x - spacing)
        }
        return (CGSize(width: widest, height: y + rowHeight), origins)
    }
}
