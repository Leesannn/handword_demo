import Metal
import SceneKit
import SwiftUI

/// 3D 인형이 본보기 동작을 보여 주는 화면. 좌우로 끌면 인형이 돌아가고, 두 번 누르면 정면으로 돌아온다
struct AvatarView: View {
    let motion: AvatarMotion
    let frame: Int
    /// 다음 장면까지 걸리는 시간. 이 시간 동안 자세가 이어지게 움직인다
    var stepDuration: Double = 1 / SignSpec.targetFPS
    var mirror = false
    /// 화면 아래쪽에서 단추 같은 것이 덮는 높이. 인형의 손이 그 위에 오게 한다
    var bottomInset: CGFloat = 0
    /// 인형을 돌린 각도(도). 0이면 정면
    @Binding var yaw: Double

    @Environment(\.still) private var still
    @Environment(\.colorScheme) private var scheme
    @GestureState private var dragging: Double = 0

    var body: some View {
        GeometryReader { geo in
            let angle = (yaw + dragging).clamped(-80, 80)
            Group {
                if still {
                    AvatarStill(motion: motion, frame: frame, mirror: mirror, yaw: angle, bottomInset: bottomInset, size: geo.size)
                } else {
                    AvatarLive(motion: motion, frame: frame, stepDuration: stepDuration, mirror: mirror,
                               yaw: angle, dark: scheme == .dark, size: geo.size, bottomInset: bottomInset)
                }
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 10)
                    .updating($dragging) { value, state, _ in state = value.translation.width * 0.45 }
                    .onEnded { value in yaw = (yaw + value.translation.width * 0.45).clamped(-80, 80) }
            )
            .onTapGesture(count: 2) { yaw = 0 }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityAdjustableAction { direction in
            yaw = (yaw + (direction == .increment ? 20 : -20)).clamped(-80, 80)
        }
    }
}

/// 한 장면을 멈춘 그림으로 그린다 (동작 순서의 작은 그림, 목록의 그림, 화면을 뽑아 볼 때)
struct AvatarStill: View {
    let motion: AvatarMotion
    let frame: Int
    var mirror = false
    var yaw: Double = 0
    var bottomInset: CGFloat = 0
    let size: CGSize
    @Environment(\.colorScheme) private var scheme
    @Environment(\.displayScale) private var displayScale

    var body: some View {
        if let image = AvatarSnapshot.image(motion: motion, frame: frame, size: size, scale: max(displayScale, 2),
                                            mirror: mirror, yaw: yaw, dark: scheme == .dark, bottomInset: bottomInset) {
            Image(decorative: image, scale: max(displayScale, 2))
                .resizable()
                .frame(width: size.width, height: size.height)
        }
    }
}

enum AvatarSnapshot {
    private static var cache: [String: CGImage] = [:]

    /// 화면 밖에서 인형을 한 번 그려 그림으로 돌려준다. 같은 조건이면 그려 둔 것을 다시 쓴다
    static func image(motion: AvatarMotion, frame: Int, size: CGSize, scale: CGFloat, mirror: Bool, yaw: Double, dark: Bool,
                      bottomInset: CGFloat = 0) -> CGImage? {
        guard size.width >= 8, size.height >= 8, motion.frames.indices.contains(frame) else { return nil }
        let key = "\(motion.id)-\(frame)-\(Int(size.width))x\(Int(size.height))@\(scale)-\(mirror)-\(Int(yaw))-\(dark)-\(Int(bottomInset))"
        if let hit = cache[key] { return hit }
        guard let device = MTLCreateSystemDefaultDevice() else { return nil }
        let avatar = AvatarScene(dark: dark)
        avatar.apply(motion.frames[frame], duration: 0)
        avatar.setView(yaw: yaw, mirror: mirror)
        avatar.aim(aspect: size.width / size.height, bottomInset: bottomInset / size.height)
        let renderer = SCNRenderer(device: device, options: nil)
        renderer.scene = avatar.scene
        renderer.pointOfView = avatar.cameraNode
        let rendered = renderer.snapshot(atTime: 0, with: CGSize(width: size.width * scale, height: size.height * scale),
                                         antialiasingMode: .multisampling4X)
        #if canImport(UIKit)
        let image = rendered.cgImage
        #else
        let image = rendered.cgImage(forProposedRect: nil, context: nil, hints: nil)
        #endif
        if cache.count > 80 { cache.removeAll() }
        cache[key] = image
        return image
    }
}

/// SCNView 하나와 인형 하나를 묶어 들고 있는 것
final class AvatarHolder {
    var avatar: AvatarScene?
    var dark: Bool?
    var frame = -1
    var motionCount = -1

    func update(_ view: SCNView, motion: AvatarMotion, frame: Int, stepDuration: Double, mirror: Bool, yaw: Double, dark: Bool,
                size: CGSize, bottomInset: CGFloat) {
        if avatar == nil || self.dark != dark {
            // 밝은 화면과 어두운 화면은 칠판 색이 달라서 인형을 새로 만든다
            let made = AvatarScene(dark: dark)
            avatar = made
            self.dark = dark
            self.frame = -1
            view.scene = made.scene
            view.pointOfView = made.cameraNode
        }
        guard let avatar, motion.frames.indices.contains(frame) else { return }
        if size.width > 1, size.height > 1 { avatar.aim(aspect: size.width / size.height, bottomInset: bottomInset / size.height) }
        avatar.setView(yaw: yaw, mirror: mirror)
        guard frame != self.frame || motion.frames.count != motionCount else { return }
        // 바로 다음 장면이면 그 시간만큼 이어서 움직이고, 처음으로 돌아가거나 건너뛸 때는 짧게 넘어간다
        let next = frame == self.frame + 1
        avatar.apply(motion.frames[frame], duration: self.frame < 0 ? 0 : next ? stepDuration : 0.22)
        self.frame = frame
        motionCount = motion.frames.count
    }


    static func prepare(_ view: SCNView) {
        view.backgroundColor = .clear
        #if os(iOS)
        view.isOpaque = false
        #endif
        view.antialiasingMode = .multisampling4X
        view.allowsCameraControl = false
        view.autoenablesDefaultLighting = false
        view.rendersContinuously = false
    }
}

#if os(iOS)
private struct AvatarLive: UIViewRepresentable {
    let motion: AvatarMotion
    let frame: Int
    let stepDuration: Double
    let mirror: Bool
    let yaw: Double
    let dark: Bool
    let size: CGSize
    let bottomInset: CGFloat

    func makeCoordinator() -> AvatarHolder { AvatarHolder() }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        AvatarHolder.prepare(view)
        view.isUserInteractionEnabled = false
        return view
    }

    func updateUIView(_ view: SCNView, context: Context) {
        context.coordinator.update(view, motion: motion, frame: frame, stepDuration: stepDuration,
                                   mirror: mirror, yaw: yaw, dark: dark, size: size, bottomInset: bottomInset)
    }
}
#else
private struct AvatarLive: NSViewRepresentable {
    let motion: AvatarMotion
    let frame: Int
    let stepDuration: Double
    let mirror: Bool
    let yaw: Double
    let dark: Bool
    let size: CGSize
    let bottomInset: CGFloat

    func makeCoordinator() -> AvatarHolder { AvatarHolder() }

    func makeNSView(context: Context) -> SCNView {
        let view = SCNView()
        AvatarHolder.prepare(view)
        return view
    }

    func updateNSView(_ view: SCNView, context: Context) {
        context.coordinator.update(view, motion: motion, frame: frame, stepDuration: stepDuration,
                                   mirror: mirror, yaw: yaw, dark: dark, size: size, bottomInset: bottomInset)
    }
}
#endif
