import SwiftUI

/// 자리 안내 상자와 고른 사람·손을 그린다. 좌표는 좌우 반전된 화면 기준이라 미리보기에 그대로 겹친다
struct OverlayView: View {
    let frame: FrameResult?
    let guide: GuideStatus
    let imageWidth: Int
    let imageHeight: Int

    static let rightLabelColor = Color.orange
    static let leftLabelColor = Color.cyan

    var body: some View {
        Canvas { context, size in
            func point(_ p: Landmark) -> CGPoint { CGPoint(x: CGFloat(p.x) * size.width, y: CGFloat(p.y) * size.height) }

            // 화면 픽셀 기준 상자를 미리보기 크기로 옮긴다
            let z = PositionGuide.zone(width: imageWidth, height: imageHeight)
            let sx = size.width / CGFloat(imageWidth), sy = size.height / CGFloat(imageHeight)
            let box = CGRect(x: CGFloat(z.x0) * sx, y: CGFloat(z.y0) * sy,
                             width: CGFloat(z.x1 - z.x0) * sx, height: CGFloat(z.y1 - z.y0) * sy).insetBy(dx: 1.5, dy: 1.5)
            context.stroke(Path(box), with: .color(guide.isOK ? .green : .red), lineWidth: 3)

            guard let frame, let person = frame.person else { return }
            var shoulders = Path()
            shoulders.move(to: point(person.points[SignSpec.leftShoulder]))
            shoulders.addLine(to: point(person.points[SignSpec.rightShoulder]))
            context.stroke(shoulders, with: .color(.white), lineWidth: 2)
            for i in [SignSpec.leftWrist, SignSpec.rightWrist] {
                let c = point(person.points[i])
                context.stroke(Path(ellipseIn: CGRect(x: c.x - 6, y: c.y - 6, width: 12, height: 12)), with: .color(.white), lineWidth: 2)
            }
            for (start, hand) in frame.hands {
                let color = start == SignSpec.rightLabelStart ? Self.rightLabelColor : Self.leftLabelColor
                for p in hand.points {
                    let c = point(p)
                    context.fill(Path(ellipseIn: CGRect(x: c.x - 3, y: c.y - 3, width: 6, height: 6)), with: .color(color))
                }
            }
        }
        .allowsHitTesting(false)
    }
}
