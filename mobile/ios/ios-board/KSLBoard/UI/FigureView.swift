import SwiftUI

/// 좌표(0~1)를 무대 위의 점으로 옮기는 방법
struct FigureMapping {
    /// 카메라 화면 전체가 무대에서 차지하는 자리
    var rect: CGRect
    var flipX = false

    func callAsFunction(_ p: CGPoint) -> CGPoint {
        CGPoint(x: rect.minX + (flipX ? 1 - p.x : p.x) * rect.width, y: rect.minY + p.y * rect.height)
    }

    /// 카메라가 본 그대로 무대에 맞춘다. 사람이 멀면 작게, 가까우면 크게 보인다.
    /// 세로 화면은 위에서 78%까지 보이게 하고, 정사각·가로 화면은 무대를 채운다
    static func camera(aspect: CGFloat, in size: CGSize, flipX: Bool) -> FigureMapping {
        let height = max(size.height, min(size.width / aspect, size.height / 0.78))
        let width = height * aspect
        return FigureMapping(rect: CGRect(x: (size.width - width) / 2, y: 0, width: width, height: height), flipX: flipX)
    }

    /// 본보기: 사람이 무대 가운데에 알맞은 크기로 오게 맞춘다.
    /// 어깨 폭은 무대 너비의 maxFill까지, 머리 위부터 손이 움직이는 자리(어깨 아래로 어깨 폭의 1.3배)까지 들어가는 크기로 잡는다
    static func person(_ demo: Demo, in size: CGSize, flipX: Bool, maxFill: CGFloat = 0.32) -> FigureMapping {
        let shoulder = max(8, min(size.width * maxFill, (size.height - 24) / 2.45))
        let width = shoulder / max(demo.shoulder, 0.01)
        let height = width / demo.aspect
        let cx = flipX ? 1 - demo.center.x : demo.center.x
        return FigureMapping(rect: CGRect(x: size.width / 2 - cx * width, y: shoulder * 1.15 - demo.center.y * height,
                                          width: width, height: height), flipX: flipX)
    }
}

/// 칠판 위에 사람을 그린다. 영상은 쓰지 않고 손과 몸의 점만으로 그린다.
/// 몸통은 칠판보다 한 단계 밝은 면, 머리 테두리와 팔은 분필 흰 선, 오른손은 채운 노랑, 왼손은 빈 하늘색 테두리
enum FigureRenderer {
    private static let palm = [0, 1, 5, 9, 13, 17]
    private static let fingers = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16], [17, 18, 19, 20]]

    static func draw(_ ctx: inout GraphicsContext, pose: Pose2D, map: FigureMapping, size: CGSize, trail: Trail? = nil) {
        func joint(_ i: Int) -> CGPoint? { pose.body[i].map { map($0) } }
        guard let ls = joint(SignSpec.leftShoulder), let rs = joint(SignSpec.rightShoulder) else { return }
        let d = hypot(ls.x - rs.x, ls.y - rs.y)
        guard d > 3 else { return }
        let chalk = GraphicsContext.Shading.color(Theme.chalk)
        let cloth = GraphicsContext.Shading.color(Theme.board2)

        // 몸통: 어깨에서 허리쯤(어깨 폭의 1.75배 아래)까지의 면. 손이 몸 앞을 지날 때 바탕과 구분되게 한다.
        // 좌표에는 어깨 아래의 몸이 없어서 길이는 어림이다. 사람이 가까우면 무대 아래로 잘린다
        let (a, b) = ls.x < rs.x ? (ls, rs) : (rs, ls)
        let bottom = max(a.y, b.y) + d * 1.75
        var torso = Path()
        torso.move(to: a)
        torso.addLine(to: b)
        torso.addLine(to: CGPoint(x: b.x - d * 0.1, y: bottom))
        torso.addLine(to: CGPoint(x: a.x + d * 0.1, y: bottom))
        torso.closeSubpath()
        ctx.fill(torso, with: cloth)
        ctx.stroke(torso, with: cloth, style: StrokeStyle(lineWidth: d * 0.16, lineJoin: .round))

        // 목과 머리
        let mid = CGPoint(x: (ls.x + rs.x) / 2, y: (ls.y + rs.y) / 2)
        if let le = joint(7), let re = joint(8) {
            let e = max(hypot(le.x - re.x, le.y - re.y), d * 0.3)
            let c = CGPoint(x: (le.x + re.x) / 2, y: (le.y + re.y) / 2 - 0.07 * e)
            var neck = Path()
            neck.move(to: mid)
            neck.addLine(to: CGPoint(x: c.x, y: c.y + 0.6 * e))
            ctx.stroke(neck, with: cloth, style: StrokeStyle(lineWidth: d * 0.26, lineCap: .round))
            let head = Path(ellipseIn: CGRect(x: c.x - 0.6 * e, y: c.y - 0.8 * e, width: 1.2 * e, height: 1.6 * e))
            let line = (d * 0.028).clamped(1.4, 3.6)
            ctx.fill(head, with: cloth)
            ctx.stroke(head, with: chalk, lineWidth: line)
            for i in [2, 5] {
                guard let eye = joint(i) else { continue }
                let r = max(1, e * 0.04)
                ctx.fill(Path(ellipseIn: CGRect(x: eye.x - r, y: eye.y - r, width: r * 2, height: r * 2)), with: chalk)
            }
            if let m1 = joint(9), let m2 = joint(10) {
                var mouth = Path()
                mouth.move(to: m1)
                mouth.addLine(to: m2)
                ctx.stroke(mouth, with: chalk, style: StrokeStyle(lineWidth: max(1, line * 0.8), lineCap: .round))
            }
        }

        // 읽는 동안 손목이 지나간 길
        if let trail {
            for run in trail.right { drawTrail(&ctx, run.map { map($0) }, right: true) }
            for run in trail.left { drawTrail(&ctx, run.map { map($0) }, right: false) }
        }

        // 팔. 손이 잡혔으면 팔 끝을 그 손목에 맞춘다. 손은 가까운 쪽 Pose 손목의 팔에 붙인다
        var wristEnd: [Int: CGPoint] = [:]
        for hand in [pose.right, pose.left] {
            guard let first = hand?.first else { continue }
            let w = map(first)
            let near = [SignSpec.leftWrist, SignSpec.rightWrist]
                .compactMap { i in joint(i).map { (i, hypot($0.x - w.x, $0.y - w.y)) } }
                .min { $0.1 < $1.1 }
            if let near, wristEnd[near.0] == nil { wristEnd[near.0] = w }
        }
        let armWidth = (d * 0.075).clamped(2.4, 12)
        for (shoulder, elbow, wrist) in [(11, 13, 15), (12, 14, 16)] {
            guard let p0 = joint(shoulder), let p1 = joint(elbow) else { continue }
            var arm = Path()
            arm.move(to: p0)
            arm.addLine(to: p1)
            if let p2 = wristEnd[wrist] ?? joint(wrist) { arm.addLine(to: p2) }
            ctx.stroke(arm, with: chalk, style: StrokeStyle(lineWidth: armWidth, lineCap: .round, lineJoin: .round))
        }

        // 안 잡힌 손은 손목 자리에 흐린 표시만 남긴다.
        // 좌우 반전한 화면에서는 Pose의 15번(왼 손목 라벨)이 실제 오른손목이다
        let markRadius = armWidth * 0.8
        if pose.right == nil, wristEnd[SignSpec.leftWrist] == nil, let w = joint(SignSpec.leftWrist) {
            ctx.fill(Path(ellipseIn: CGRect(x: w.x - markRadius, y: w.y - markRadius, width: markRadius * 2, height: markRadius * 2)),
                     with: .color(Theme.rightHand.opacity(0.42)))
        }
        if pose.left == nil, wristEnd[SignSpec.rightWrist] == nil, let w = joint(SignSpec.rightWrist) {
            ctx.stroke(Path(ellipseIn: CGRect(x: w.x - markRadius, y: w.y - markRadius, width: markRadius * 2, height: markRadius * 2)),
                       with: .color(Theme.leftHand.opacity(0.6)), lineWidth: 1.6)
        }

        if let left = pose.left { drawHand(&ctx, left.map { map($0) }, right: false) }
        if let right = pose.right { drawHand(&ctx, right.map { map($0) }, right: true) }
    }

    private static func drawHand(_ ctx: inout GraphicsContext, _ p: [CGPoint], right: Bool) {
        let finger = (hypot(p[5].x - p[17].x, p[5].y - p[17].y) * 0.26).clamped(1.6, 9)
        var palmPath = Path()
        palmPath.addLines(palm.map { p[$0] })
        palmPath.closeSubpath()
        var fingerPath = Path()
        for f in fingers { fingerPath.addLines(f.map { p[$0] }) }

        func paint(_ color: Color, width: CGFloat) {
            let style = StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round)
            ctx.fill(palmPath, with: .color(color))
            ctx.stroke(palmPath, with: .color(color), style: style)
            ctx.stroke(fingerPath, with: .color(color), style: style)
        }
        if right {
            paint(Theme.rightHand, width: finger * 1.25)
        } else {
            // 테두리 색으로 한 번 굵게 칠하고, 그 안을 칠판 색으로 덮어 속이 빈 손을 만든다
            let edge = (finger * 0.22).clamped(1.1, 1.8)
            paint(Theme.leftHand, width: finger * 1.25 + edge * 2)
            paint(Theme.board, width: finger * 1.25)
        }
    }

    private static func drawTrail(_ ctx: inout GraphicsContext, _ raw: [CGPoint], right: Bool) {
        guard raw.count >= 3 else { return }
        var points = raw
        for _ in 0..<2 {
            points = points.indices.map { i in
                let a = points[max(i - 1, 0)], b = points[i], c = points[min(i + 1, points.count - 1)]
                return CGPoint(x: (a.x + b.x * 2 + c.x) / 4, y: (a.y + b.y * 2 + c.y) / 4)
            }
        }
        // 손이 잠깐 잡혔다 사라진 짧은 조각은 길로 보이지 않고 얼룩처럼 보여서 그리지 않는다
        let length = zip(points, points.dropFirst()).reduce(0) { $0 + hypot($1.1.x - $1.0.x, $1.1.y - $1.0.y) }
        guard length >= 24 else { return }
        var path = Path()
        path.addLines(points)
        if right {
            ctx.stroke(path, with: .color(Theme.rightHand), style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
        } else {
            ctx.stroke(path, with: .color(Theme.leftHand), style: StrokeStyle(lineWidth: 2.6, lineCap: .round, lineJoin: .round, dash: [0.1, 6]))
        }
    }

    /// 자리 안내 상자(화면 가운데 60%)의 양쪽 끝을 점선 괄호로 그린다. 안내일 뿐이고 읽기는 화면 전체에서 한다
    static func drawZone(_ ctx: inout GraphicsContext, map: FigureMapping, size: CGSize) {
        let inset = (1 - PositionGuide.zoneWidth) / 2
        let x0 = max(14, map.rect.minX + inset * map.rect.width)
        let x1 = min(size.width - 14, map.rect.maxX - inset * map.rect.width)
        let top = size.height * 0.34, bottom = size.height * 0.8
        var p = BracketShape().path(in: CGRect(x: x0, y: top, width: 12, height: bottom - top))
        p.addPath(BracketShape(right: true).path(in: CGRect(x: x1 - 12, y: top, width: 12, height: bottom - top)))
        ctx.stroke(p, with: .color(Theme.chalk2), style: StrokeStyle(lineWidth: 2, dash: [5, 4]))
    }
}

/// 무대에 그리는 사람 도식
struct FigureView: View {
    var pose: Pose2D?
    var trail: Trail?
    var showZone = false
    let mapping: (CGSize) -> FigureMapping

    var body: some View {
        Canvas { ctx, size in
            let map = mapping(size)
            if showZone { FigureRenderer.drawZone(&ctx, map: map, size: size) }
            if let pose { FigureRenderer.draw(&ctx, pose: pose, map: map, size: size, trail: trail) }
        }
        .accessibilityHidden(true)
    }
}
