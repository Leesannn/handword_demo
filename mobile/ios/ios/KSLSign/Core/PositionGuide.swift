import Foundation

enum GuideStatus: Equatable {
    case ok, noPerson, moveRight, moveLeft, closer, farther

    var isOK: Bool { self == .ok }

    /// live_test.py의 안내 글자 (No person in box, Move right, Move left, Move closer, Step back)
    var message: String {
        switch self {
        case .ok: "좋아요"
        case .noPerson: "상자 안에 앉아 주세요"
        case .moveRight: "오른쪽으로"
        case .moveLeft: "왼쪽으로"
        case .closer: "가까이"
        case .farther: "뒤로"
        }
    }
}

/// 자리 안내. live_test.py의 zone_of, placement와 같다. 상자는 안내일 뿐이고 인식은 화면 전체에서 한다.
enum PositionGuide {
    /// 상자 너비(화면 너비 대비, 가운데 기준)
    static let zoneWidth = 0.6
    /// 상자 위쪽 끝(화면 높이 대비). 상자는 여기부터 화면 아래까지
    static let zoneTop = 0.0
    /// 어깨 폭(화면 너비 대비)이 이보다 작으면 '가까이', 크면 '뒤로'
    static let guideMin = 0.12
    static let guideMax = 0.30

    /// 상자 (x0, y0, x1, y1) 픽셀
    static func zone(width: Int, height: Int) -> (x0: Int, y0: Int, x1: Int, y1: Int) {
        let x0 = Int(Double(width) * (1 - zoneWidth) / 2)
        return (x0, Int(Double(height) * zoneTop), width - x0, height)
    }

    /// 어깨 중심이 상자 안쪽(양옆 20% 여백 안)에 있는지 먼저 보고, 그다음 어깨 폭으로 거리를 본다.
    /// 좌표가 좌우 반전된 화면 기준이라 '오른쪽으로'는 화면에서 오른쪽(사용자 기준으로도 오른쪽)이다
    static func status(for frame: FrameResult, width: Int, height: Int) -> GuideStatus {
        guard let person = frame.person, let size = frame.shoulderWidth else { return .noPerson }
        let z = zone(width: width, height: height)
        let center = (Double(person.points[SignSpec.leftShoulder].x) + Double(person.points[SignSpec.rightShoulder].x)) / 2 * Double(width)
        let margin = Double(z.x1 - z.x0) * 0.2
        if center < Double(z.x0) + margin { return .moveRight }
        if center > Double(z.x1) - margin { return .moveLeft }
        if size < guideMin { return .closer }
        if size > guideMax { return .farther }
        return .ok
    }
}
