import SwiftUI
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif

/// 색과 글자. 값의 뜻과 규칙은 디자인 기록(DESIGN.md)의 '수어 교실의 칠판'을 따른다
enum Theme {
    // 종이 쪽 (시트, 목록)
    static let bg = Color(light: 0xFFFFFF, dark: 0x0F1512)
    static let bgGrouped = Color(light: 0xF1F4F1, dark: 0x0B100D)
    static let bgRow = Color(light: 0xFFFFFF, dark: 0x182019)
    static let fill = Color(light: 0xE6ECE7, dark: 0x222C26)
    static let sep = Color(light: 0x14201A, dark: 0xE8F4EC, alpha: 0.16)
    static let ink = Color(light: 0x14201A, dark: 0xECF3EE)
    static let ink2 = Color(light: 0x4A5850, dark: 0xA9B8AE)
    static let ink3 = Color(light: 0x5F6E65, dark: 0x8E9D94)
    /// 누를 수 있는 것과 표기(대괄호)의 색. 하나뿐이다
    static let tint = Color(light: 0x1F5E46, dark: 0x7AD3A6)
    static let onTint = Color(light: 0xFFFFFF, dark: 0x092016)
    static let tintSoft = Color(light: 0xDDEBE3, dark: 0x1B3328)
    static let warn = Color(light: 0x7A4A00, dark: 0xF0C06A)
    static let bad = Color(light: 0x9E2F27, dark: 0xF2A49C)

    // 칠판 쪽 (무대)
    static let board = Color(light: 0x1B4332, dark: 0x173A2B)
    static let board2 = Color(light: 0x27583F, dark: 0x215039)
    static let boardGlass = Color.white.opacity(0.14)
    static let chalk = Color(hex: 0xF2F7F3)
    static let chalk2 = Color(hex: 0xB8D4C6)
    static let onChalk = Color(hex: 0x1B4332)
    /// 오른손은 분필 노랑으로 채우고, 왼손은 분필 하늘색 테두리로 비워 그린다 (색만으로 구분하지 않는다)
    static let rightHand = Color(hex: 0xF4D35E)
    static let leftHand = Color(hex: 0x9AD4F5)

    static let ease = Animation.timingCurve(0.16, 1, 0.3, 1, duration: 0.3)
}

extension Color {
    init(hex: UInt32, alpha: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255, opacity: alpha)
    }

    /// 밝은 화면과 어두운 화면에서 값이 다른 색
    init(light: UInt32, dark: UInt32, alpha: Double = 1) {
        #if canImport(UIKit)
        self.init(uiColor: UIColor { traits in
            UIColor(Color(hex: traits.userInterfaceStyle == .dark ? dark : light, alpha: alpha))
        })
        #else
        self.init(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            return NSColor(Color(hex: isDark ? dark : light, alpha: alpha))
        })
        #endif
    }
}

extension Font {
    /// iOS에서는 시스템 글자 크기(사용자가 정한 크기를 따른다)를 그대로 쓴다.
    /// Mac에서 화면을 뽑아 볼 때만 아이폰의 기본 크기를 흉내 낸다
    static func app(_ style: Font.TextStyle, _ weight: Font.Weight = .regular) -> Font {
        #if os(iOS)
        return .system(style, weight: weight)
        #else
        return .system(size: Theme.baseSize(style), weight: weight)
        #endif
    }
}

extension Theme {
    /// 아이폰 기본 글자 크기(Large)에서 글자 종류별 크기
    static func baseSize(_ style: Font.TextStyle) -> CGFloat {
        switch style {
        case .largeTitle: 34
        case .title: 28
        case .title2: 22
        case .title3: 20
        case .headline, .body: 17
        case .callout: 16
        case .subheadline: 15
        case .footnote: 13
        case .caption: 12
        case .caption2: 11
        @unknown default: 17
        }
    }
}

extension Comparable {
    func clamped(_ low: Self, _ high: Self) -> Self {
        min(max(self, low), high)
    }
}

extension View {
    /// 다른 화면으로 넘어가지 않는 화면 제목 (아이폰에서만 뜻이 있다)
    func inlineBar() -> some View {
        #if os(iOS)
        return self.navigationBarTitleDisplayMode(.inline).toolbarBackground(.hidden, for: .navigationBar)
        #else
        return self
        #endif
    }

    /// 화면 전체를 덮는 화면. Mac에는 없어서 시트로 대신한다
    func cover<Content: View>(isPresented: Binding<Bool>, @ViewBuilder content: @escaping () -> Content) -> some View {
        #if os(iOS)
        return self.fullScreenCover(isPresented: isPresented, content: content)
        #else
        return self.sheet(isPresented: isPresented, content: content)
        #endif
    }
}
