import SceneKit
import simd
#if canImport(UIKit)
import UIKit
typealias PlatformColor = UIColor
#else
import AppKit
typealias PlatformColor = NSColor
#endif

/// 수어 본보기를 보여 주는 3D 사람 모형 (남자).
///
/// 모형은 `Signer.usdz`다. MPFB(MakeHuman)로 만든 몸·얼굴·머리·옷과 손가락까지 있는 뼈대가 들어 있다
/// (만드는 법은 `~/sign-app/tools/avatar`). 여기서는 AvatarFrame의 관절 자리를 뼈의 방향으로 바꿔 뼈대를 움직인다.
/// - 팔: 위팔과 아래팔이 좌표의 어깨→팔꿈치, 팔꿈치→손목 방향을 향한다. 모형의 팔 길이는 그대로다
/// - 손: 손바닥의 방향을 손목 뼈에 주고, 손가락 마디마다 좌표의 마디 방향을 향한다
/// - 손목 띠: 오른손은 노랑, 왼손은 하늘색. 칠판 그림의 손 색과 같은 뜻이다
final class AvatarScene {
    let scene = SCNScene()
    let cameraNode = SCNNode()

    private let turn = SCNNode()        // 돌려 보기, 거울로 보기
    private var joints: [Joint] = []
    private var drivers: [Int: Driver] = [:]
    /// 화면 쪽 방향(위가 Y, 앞이 Z)을 뼈대가 쓰는 방향(파일에 따라 위가 Z일 수 있다)으로 바꾼다
    private var toRig = matrix_identity_float3x3

    private struct Joint {
        let node: SCNNode
        let parent: Int                 // 없으면 -1
        let rest: simd_float4x4         // 부모 기준
        let restRig: simd_float4x4      // 뼈대 기준
        var position: SIMD3<Float> { restRig.columns.3.xyz }
    }

    private static let fieldOfView: Double = 13

    private enum Side { case right, left }

    /// 모형의 팔: 어깨 관절 자리(어깨 중심 기준, 화면 쪽 방향)와 위팔·아래팔 길이
    private struct Reach {
        let shoulder: SIMD3<Float>
        let upper: Float
        let lower: Float
    }
    private var reach: [Side: Reach] = [:]
    /// 모형의 얼굴 자리(두 귀의 가운데, 어깨 중심 기준)와 얼굴 폭
    private var modelFace: (center: SIMD3<Float>, width: Float)?
    /// 뼈마다 마지막으로 준 방향. 같은 방향을 뜻하는 두 값(q와 -q)이 번갈아 나오면 사이를 잇는 동안 살갗이 늘어나 보여서 부호를 맞춘다
    private var lastTurn: [Int: simd_quatf] = [:]

    private enum Driver {
        /// 뼈가 가리키는 방향(쉬는 자세에서 restDirection)을 좌표의 두 점 사이 방향에 맞춘다
        case arm(Side, restDirection: SIMD3<Float>, upper: Bool)
        /// 엄지 마디: 좌표의 마디 방향을 향하되, 쉬는 자세에서 limit(라디안)보다 더 꺾이지는 않는다
        case finger(Side, restDirection: SIMD3<Float>, from: Int, to: Int, limit: Float)
        /// 손가락 뿌리 마디: 손바닥 쪽으로 굽히는 각도만 좌표에서 가져온다 (a는 뿌리, b는 다음 마디)
        case knuckle(Side, wrist: Int, restFrame: simd_float3x3, a: Int, b: Int, restAngle: Float)
        /// 손가락 가운데·끝 마디: 앞 마디와 이루는 각도만큼만 손바닥 쪽으로 굽힌다. 사람 손가락처럼 한 방향으로만 접힌다
        case bend(Side, wrist: Int, a: Int, b: Int, c: Int, restFrame: simd_float3x3, restAngle: Float, limit: Float)
        /// 손바닥 방향 전체. restFrame은 쉬는 자세의 손바닥 틀
        case palm(Side, restFrame: simd_float3x3)
        /// 아래팔 끝: 손목이 돌아간 만큼의 절반을 나눠 가진다 (손목만 비틀리면 살갗이 꼬인다)
        case twist(Side, wrist: Int, restFrame: simd_float3x3)
        case head
    }

    init(dark: Bool) {
        scene.rootNode.addChildNode(turn)
        load()

        // 빛: 고르게 밝히는 빛과 앞 위에서 비추는 빛, 뒤에서 윤곽을 살리는 빛
        func light(_ type: SCNLight.LightType, _ intensity: CGFloat, _ angles: SCNVector3 = SCNVector3Zero) {
            let node = SCNNode()
            node.light = SCNLight()
            node.light?.type = type
            node.light?.intensity = intensity
            node.eulerAngles = angles
            scene.rootNode.addChildNode(node)
        }
        light(.ambient, dark ? 430 : 480)
        light(.directional, dark ? 620 : 700, SCNVector3(-0.55, 0.45, 0))
        light(.directional, 260, SCNVector3(-0.2, -0.9, 0))
        light(.directional, 220, SCNVector3(-0.6, 3.0, 0))

        let camera = SCNCamera()
        // 좁은 화각으로 멀리서 본다. 화각이 넓으면 앞으로 내민 손이 몸보다 크게 그려져 손가락이 길어 보인다
        camera.fieldOfView = Self.fieldOfView
        camera.zNear = 0.1
        camera.zFar = 20
        cameraNode.camera = camera
        scene.rootNode.addChildNode(cameraNode)
        aim(aspect: 1.2)
        rest()
    }

    // MARK: 움직이기

    /// 한 장면의 자세로 옮긴다. duration 동안 이전 자세에서 이어지게 움직인다
    func apply(_ frame: AvatarFrame, duration: TimeInterval) {
        pose(frame, duration: duration)
    }

    /// 두 팔을 내린 자세
    func rest() {
        pose(AvatarFrame(right: Self.down(.right), left: Self.down(.left)), duration: 0)
    }

    /// 내린 팔 하나
    private static func down(_ side: Side) -> AvatarFrame.Arm {
        let sign: Float = side == .right ? -1 : 1
        var arm = AvatarFrame.Arm()
        arm.shoulder = SIMD3(sign * 0.17, 0, 0)
        arm.elbow = arm.shoulder + SIMD3(sign * 0.045, -0.27, 0.0)
        arm.wrist = arm.elbow + SIMD3(sign * 0.01, -0.24, 0.06)
        return arm
    }

    private func pose(_ shown: AvatarFrame, duration: TimeInterval) {
        guard !joints.isEmpty else { return }
        var frame = shown
        func turned(_ arm: AvatarFrame.Arm, _ reach: Reach?) -> AvatarFrame.Arm {
            let fitted = reach.map { Self.fit(arm, to: $0, face: shown.faceWidth > 0.02 ? (shown.face, shown.faceWidth) : nil, modelFace: modelFace) } ?? arm
            return AvatarFrame.Arm(shoulder: toRig * fitted.shoulder, elbow: toRig * fitted.elbow, wrist: toRig * fitted.wrist,
                                   hand: fitted.hand.map { toRig * $0 }, shape: arm.shape, curl: arm.curl, handOK: arm.handOK)
        }
        // 구간 내내 손이 한 번도 안 잡힌 팔은 화면 밖에 있던 것이다. 팔꿈치·손목 좌표를 믿을 수 없어서 내린 자세로 둔다
        frame.right = turned(shown.right.hand.isEmpty ? Self.down(.right) : shown.right, reach[.right])
        frame.left = turned(shown.left.hand.isEmpty ? Self.down(.left) : shown.left, reach[.left])
        SCNTransaction.begin()
        SCNTransaction.animationDuration = duration
        SCNTransaction.animationTimingFunction = CAMediaTimingFunction(name: .linear)

        var current = [simd_float4x4](repeating: matrix_identity_float4x4, count: joints.count)
        for (i, joint) in joints.enumerated() {
            let parent = joint.parent < 0 ? matrix_identity_float4x4 : current[joint.parent]
            var world = parent * joint.rest
            if let driver = drivers[i], let turned = rotation(driver, joint: joint, world: world, frame: frame, current: current) {
                world = Self.rotate(world, by: turned)
                joint.node.simdOrientation = steady(simd_quatf(Self.rotationPart(parent.inverse * world)), for: i)
            } else if drivers[i] != nil {
                joint.node.simdOrientation = steady(simd_quatf(Self.rotationPart(joint.rest)), for: i)
            }
            current[i] = world
        }
        SCNTransaction.commit()
        if ProcessInfo.processInfo.environment["AVATAR_DEBUG"] != nil {
            func at(_ name: String) -> (SIMD3<Float>, SIMD3<Float>, SIMD3<Float>)? {
                guard let i = joints.firstIndex(where: { $0.node.name == name }) else { return nil }
                return (joints[i].position, current[i].columns.3.xyz, joints[i].node.presentation.simdWorldPosition)
            }
            if let w = at("wrist_L"), let k = at("finger3_1_L"), let m = at("finger3_2_L"), let e = at("finger3_3_L") {
                let back = toRig.transpose
                let palm = back * (k.1 - w.1), one = back * (m.1 - k.1), two = back * (e.1 - m.1)
                func deg(_ a: SIMD3<Float>, _ b: SIMD3<Float>) -> Float { acos(simd_dot(simd_normalize(a), simd_normalize(b))) * 180 / .pi }
                print(String(format: "HAND L 손등 (%.3f %.3f %.3f) 첫마디 (%.3f %.3f %.3f) 손등↔첫마디 %.0f° 첫↔둘째 %.0f° | curl %@", palm.x, palm.y, palm.z, one.x, one.y, one.z, deg(palm, one), deg(one, two),
                             shown.left.curl.count == 4 ? String(format: "%.2f %.2f %.2f", shown.left.curl[1].x, shown.left.curl[1].y, shown.left.curl[1].z) : "없음"))
            }
            var line = "DBG"
            for (a, b) in [("wrist_R", "finger3_1_R"), ("finger3_1_R", "finger3_2_R"), ("finger3_2_R", "finger3_3_R"), ("lowerarm01_R", "wrist_R"), ("upperarm01_R", "lowerarm01_R")] {
                if let p = at(a), let q = at(b) {
                    line += String(format: " %@→%@ 쉼 %.4f 계산 %.4f 노드 %.4f |", a, b, simd_distance(p.0, q.0), simd_distance(p.1, q.1), simd_distance(p.2, q.2))
                }
            }
            let scales = joints.filter { abs(simd_length($0.rest.columns.0.xyz) - 1) > 0.01 }.count
            print(line, "크기가 1이 아닌 뼈", scales, "wrist 크기", joints.first { $0.node.name == "wrist_R" }.map { simd_length($0.restRig.columns.0.xyz) } ?? 0,
                  "노드 scale", joints.first { $0.node.name == "finger3_2_R" }?.node.simdWorldTransform.columns.0 ?? SIMD4())
        }
    }

    /// 뼈를 뼈대 기준으로 더 돌릴 양. 좌표가 없으면 nil (쉬는 자세 그대로 둔다)
    private func rotation(_ driver: Driver, joint: Joint, world: simd_float4x4, frame: AvatarFrame,
                          current: [simd_float4x4]) -> simd_quatf? {
        // 지금 자세가 쉬는 자세에서 돌아가 있는 양
        let now = Self.rotationPart(world) * Self.rotationPart(joint.restRig).transpose
        func arm(_ side: Side) -> AvatarFrame.Arm { side == .right ? frame.right : frame.left }
        func swing(_ restDirection: SIMD3<Float>, to target: SIMD3<Float>) -> simd_quatf? {
            let length = simd_length(target)
            guard length > 0.0005 else { return nil }
            return Self.shortest(from: simd_normalize(now * restDirection), to: target / length)
        }

        switch driver {
        case let .arm(side, restDirection, upper):
            let a = arm(side)
            return upper ? swing(restDirection, to: a.elbow - a.shoulder) : swing(restDirection, to: a.wrist - a.elbow)

        case let .finger(side, restDirection, from, to, limit):
            let hand = arm(side).hand
            guard arm(side).handOK, hand.count == SignSpec.handPoints, let turn = swing(restDirection, to: hand[to] - hand[from]) else { return nil }
            return turn.angle > limit ? simd_quatf(angle: limit, axis: turn.axis) : turn

        case let .knuckle(side, wrist, restFrame, a, _, restAngle):
            let curl = arm(side).curl
            guard curl.count == 4 else { return nil }
            // 손을 믿을 수 없는 장면에서는 힘을 뺀 손 모양으로 둔다
            let flex = arm(side).handOK ? curl[(a - 5) / 4].x.clamped(-0.2, 1.6) : 0.3
            return hinge(side, wrist: wrist, restFrame: restFrame, by: flex - restAngle, current: current)

        case let .bend(side, wrist, a, _, _, restFrame, restAngle, limit):
            let curl = arm(side).curl
            guard curl.count == 4 else { return nil }
            // 가운데 마디는 a가 뿌리 점(5, 9, 13, 17), 끝 마디는 그다음 점이다
            let finger = curl[(a - 5) / 4]
            let angle = arm(side).handOK ? ((a - 5) % 4 == 0 ? finger.y : finger.z).clamped(0, limit) : ((a - 5) % 4 == 0 ? 0.45 : 0.3)
            return hinge(side, wrist: wrist, restFrame: restFrame, by: angle - restAngle, current: current)

        case let .palm(side, restFrame):
            // 믿을 수 없으면 손목을 돌리지 않는다. 손이 팔에 이어진 쉬는 방향으로 간다
            guard arm(side).handOK, let target = Self.palmFrame(arm(side).hand) else { return nil }
            // 손바닥 틀이 쉬는 자세에서 돌아가야 할 양에서, 이미 돌아가 있는 양을 뺀다
            return simd_quatf(target * restFrame.transpose * now.transpose)

        case let .twist(side, wrist, restFrame):
            let a = arm(side)
            guard a.handOK, let target = Self.palmFrame(a.hand) else { return nil }
            let axis = a.wrist - a.elbow
            guard simd_length(axis) > 0.0005 else { return nil }
            // 손목 뼈가 지금 자세에서 더 돌아가야 하는 양 가운데, 아래팔 축을 도는 성분의 절반
            let wristNow = Self.rotationPart(world * joints[wrist].rest) * Self.rotationPart(joints[wrist].restRig).transpose
            let more = simd_quatf(target * restFrame.transpose * wristNow.transpose)
            let n = simd_normalize(axis)
            let along = simd_dot(more.imag, n)
            let whole = simd_quatf(ix: n.x * along, iy: n.y * along, iz: n.z * along, r: more.real)
            guard simd_length(whole.vector) > 0.0001 else { return nil }
            return simd_slerp(simd_quatf(ix: 0, iy: 0, iz: 0, r: 1), simd_normalize(whole), 0.5)

        case .head:
            let want = simd_quatf(angle: frame.headYaw, axis: toRig * SIMD3(0, 1, 0)) * simd_quatf(angle: frame.headRoll, axis: toRig * SIMD3(0, 0, 1))
            return want * simd_quatf(now).inverse
        }
    }

    /// 손가락이 접히는 축(집게 뿌리 ↔ 새끼 뿌리)을 따라 손바닥 쪽으로 angle만큼 굽히는 회전
    private func hinge(_ side: Side, wrist: Int, restFrame: simd_float3x3, by angle: Float, current: [simd_float4x4]) -> simd_quatf {
        let wristNow = Self.rotationPart(current[wrist]) * Self.rotationPart(joints[wrist].restRig).transpose
        let axis = simd_normalize(wristNow * restFrame.columns.0) * (side == .left ? 1 : -1)
        return simd_quatf(angle: angle, axis: axis)
    }

    private func steady(_ turn: simd_quatf, for joint: Int) -> simd_quatf {
        var result = turn
        if let last = lastTurn[joint], simd_dot(last.vector, turn.vector) < 0 { result = simd_quatf(vector: -turn.vector) }
        lastTurn[joint] = result
        return result
    }

    /// 인형을 돌린다(도). mirror가 true면 거울에 비친 모습으로 뒤집는다
    func setView(yaw: Double, mirror: Bool, duration: TimeInterval = 0) {
        SCNTransaction.begin()
        SCNTransaction.animationDuration = duration
        turn.simdEulerAngles = SIMD3(0, Float(yaw * .pi / 180), 0)
        turn.simdScale = SIMD3(mirror ? -1 : 1, 1, 1)
        SCNTransaction.commit()
    }

    /// 머리 위부터 허리쯤까지, 그리고 팔을 벌린 폭이 화면에 들어오게 카메라를 놓는다.
    /// bottomInset은 화면 아래쪽에서 다른 것(단추 줄)이 덮는 비율이다. 그만큼을 뺀 위쪽에 맞춘다
    /// topInset은 화면 위쪽에서 다른 것(손 표시, 안내 문구)이 덮는 비율이다. 무대에서 얼굴이 그 뒤에 가리지 않게 한다
    func aim(aspect: CGFloat, bottomInset: CGFloat = 0, topInset: CGFloat = 0) {
        let top: Float = 0.43, bottom: Float = -0.44, width: Float = 0.98
        let half = Float(Self.fieldOfView * Double.pi / 360)
        let above = Float(min(max(topInset, 0), 0.3))
        let free = 1 - Float(min(max(bottomInset, 0), 0.6)) - above
        let span = (top - bottom) / free
        let byHeight = span / 2 / tan(half)
        let byWidth = width / 2 / (tan(half) * Float(max(aspect, 0.3)))
        let distance = max(byHeight, byWidth)
        // 거리가 너비 때문에 늘어났을 때 남는 높이는 위아래로 나눈다
        let shown = distance * tan(half) * 2
        let slack = shown * free - (top - bottom)
        cameraNode.simdPosition = SIMD3(0, top + above * shown + slack / 2 - shown / 2, distance)
    }

    // MARK: 만들기

    private func load() {
        guard let url = Bundle.main.url(forResource: "Signer", withExtension: "usdz"),
              let loaded = try? SCNScene(url: url, options: nil) else { return }
        let model = SCNNode()
        for child in loaded.rootNode.childNodes { model.addChildNode(child) }
        turn.addChildNode(model)
        model.enumerateHierarchy { node, _ in
            node.light = nil
            node.camera = nil
            for material in node.geometry?.materials ?? [] {
                material.isDoubleSided = true
                let name = material.name ?? ""
                if name.contains("short") || name.contains("eyebrow") || name.contains("eyelash") {
                    material.roughness.contents = 0.9
                    material.metalness.contents = 0.0
                }
                if name.contains("body") { material.roughness.contents = 0.62 }
            }
        }

        // 뼈대: 부모가 먼저 오도록 차례로 모은다
        guard let skeleton = model.childNode(withName: "root", recursively: true)?.skinnerRoot(in: model) else { return }
        var index: [String: Int] = [:]
        func collect(_ node: SCNNode, parent: Int, parentRig: simd_float4x4) {
            let rig = parentRig * node.simdTransform
            let i = joints.count
            joints.append(Joint(node: node, parent: parent, rest: node.simdTransform, restRig: rig))
            if let name = node.name { index[name] = i }
            for child in node.childNodes { collect(child, parent: i, parentRig: rig) }
        }
        collect(skeleton, parent: -1, parentRig: matrix_identity_float4x4)
        if let holder = skeleton.parent {
            toRig = Self.rotationPart(holder.simdConvertTransform(matrix_identity_float4x4, to: model)).transpose
        }

        // 원점을 어깨 중심에 둔다 (AvatarFrame의 원점과 같다)
        if let r = index["upperarm01_R"], let l = index["upperarm01_L"] {
            let center = (joints[r].position + joints[l].position) / 2
            let inRig = skeleton.parent?.simdConvertPosition(center, to: model) ?? center
            model.simdPosition = -inRig
        }

        func position(_ name: String) -> SIMD3<Float>? { index[name].map { joints[$0].position } }
        for (side, tag, band) in [(Side.right, "R", 0xF4D35E), (Side.left, "L", 0x9AD4F5)] as [(Side, String, UInt32)] {
            if let upper = index["upperarm01_\(tag)"], let lower = index["lowerarm01_\(tag)"], let wrist = index["wrist_\(tag)"] {
                let fromRig = toRig.transpose
                let center = ((position("upperarm01_R") ?? .zero) + (position("upperarm01_L") ?? .zero)) / 2
                reach[side] = Reach(shoulder: fromRig * (joints[upper].position - center),
                                    upper: simd_distance(joints[upper].position, joints[lower].position),
                                    lower: simd_distance(joints[lower].position, joints[wrist].position))
                drivers[upper] = .arm(side, restDirection: simd_normalize(joints[lower].position - joints[upper].position), upper: true)
                drivers[lower] = .arm(side, restDirection: simd_normalize(joints[wrist].position - joints[lower].position), upper: false)
                if let w = position("wrist_\(tag)"), let i = position("finger2_1_\(tag)"),
                   let p = position("finger5_1_\(tag)"), let m = position("finger3_1_\(tag)"),
                   let restFrame = Self.frame(wrist: w, index: i, pinky: p, middle: m) {
                    drivers[wrist] = .palm(side, restFrame: restFrame)
                    if let end = index["lowerarm02_\(tag)"] { drivers[end] = .twist(side, wrist: wrist, restFrame: restFrame) }
                }
                if let end = index["lowerarm02_\(tag)"] { addBand(to: joints[end].node, toward: joints[wrist].rest.columns.3.xyz, color: band) }
            }
            // 손가락. 좌표의 손 깊이는 어림한 값이라 마디 방향을 그대로 따르면 손가락이 뒤나 옆으로 꺾인다.
            // 그래서 네 손가락은 굽힌 각도만 가져와 손바닥 쪽으로만 접고, 엄지는 꺾이는 양에 한도를 둔다
            guard let wrist = index["wrist_\(tag)"], let w = position("wrist_\(tag)"), let i = position("finger2_1_\(tag)"),
                  let p = position("finger5_1_\(tag)"), let m = position("finger3_1_\(tag)"),
                  let restFrame = Self.frame(wrist: w, index: i, pinky: p, middle: m) else { continue }
            for segment in 1...3 {
                guard let bone = index["finger1_\(segment)_\(tag)"] else { continue }
                let here = joints[bone].position
                let direction = position("finger1_\(segment + 1)_\(tag)").map { $0 - here }
                    ?? (joints[bone].parent >= 0 ? here - joints[joints[bone].parent].position : SIMD3(0, 0, 1))
                drivers[bone] = .finger(side, restDirection: simd_normalize(direction), from: segment, to: segment + 1,
                                        limit: segment == 1 ? 0.9 : 0.8)
            }
            for finger in 2...5 {
                let first = 5 + (finger - 2) * 4
                guard let one = index["finger\(finger)_1_\(tag)"], let two = index["finger\(finger)_2_\(tag)"],
                      let three = index["finger\(finger)_3_\(tag)"] else { continue }
                let a = joints[one].position, b = joints[two].position, c = joints[three].position
                let inPalm = restFrame.transpose * (b - a)
                let restKnuckle = atan2(side == .left ? inPalm.z : -inPalm.z, inPalm.y)
                let restBend = acos(simd_dot(simd_normalize(b - a), simd_normalize(c - b)).clamped(-1, 1))
                drivers[one] = .knuckle(side, wrist: wrist, restFrame: restFrame, a: first, b: first + 1, restAngle: restKnuckle)
                drivers[two] = .bend(side, wrist: wrist, a: first, b: first + 1, c: first + 2, restFrame: restFrame, restAngle: restBend, limit: 1.9)
                drivers[three] = .bend(side, wrist: wrist, a: first + 1, b: first + 2, c: first + 3, restFrame: restFrame, restAngle: 0.12, limit: 1.4)
            }
        }
        if let head = index["head"] { drivers[head] = .head }
        // 얼굴 자리: 두 눈의 가운데에서 귀 쪽으로 조금 뒤. 얼굴 폭은 MakeHuman 머리의 귀 사이 거리(어림)
        if let left = position("eye_L"), let right = position("eye_R"),
           let r = position("upperarm01_R"), let l = position("upperarm01_L") {
            let eyes = toRig.transpose * ((left + right) / 2 - (r + l) / 2)
            modelFace = (SIMD3(eyes.x, eyes.y - 0.005, eyes.z - 0.085), 0.15)
        }
    }

    /// 손목 띠. 아래팔 끝 뼈에 붙여 손목 바로 위에 두른다
    private func addBand(to bone: SCNNode, toward wrist: SIMD3<Float>, color: UInt32) {
        let length = simd_length(wrist)
        guard length > 0.001 else { return }
        let tube = SCNTube(innerRadius: 0.037, outerRadius: 0.042, height: 0.016)
        tube.radialSegmentCount = 36
        let material = SCNMaterial()
        material.lightingModel = .lambert
        material.diffuse.contents = Self.color(color)
        material.emission.contents = Self.color(color)
        material.emission.intensity = 0.25
        tube.firstMaterial = material
        let node = SCNNode(geometry: tube)
        node.simdPosition = wrist * 0.8
        node.simdOrientation = Self.shortest(from: SIMD3(0, 1, 0), to: wrist / length)
        bone.addChildNode(node)
    }

    // MARK: 계산

    /// 좌표의 손목 자리(어깨 기준)에 모형의 손목이 닿도록 팔꿈치 자리를 다시 정한다.
    /// 좌표의 사람과 모형은 팔 길이가 달라서, 방향만 따라 하면 두 손이 만나야 할 때 만나지 않는다.
    /// 팔꿈치가 향하는 쪽은 좌표의 팔꿈치를 따른다. 손이 닿지 않는 거리면 팔을 다 편 데까지만 간다
    private static func fit(_ arm: AvatarFrame.Arm, to reach: Reach, face: (center: SIMD3<Float>, width: Float)?,
                            modelFace: (center: SIMD3<Float>, width: Float)?) -> AvatarFrame.Arm {
        let start = reach.shoulder
        var toWrist = arm.wrist - arm.shoulder
        // 손이 얼굴 가까이 있으면 어깨가 아니라 얼굴을 기준으로 자리를 옮긴다.
        // 좌표의 사람과 모형은 목 길이와 얼굴 크기가 달라서, 어깨 기준으로만 옮기면 뺨에 댄 손이 턱 밑이나 머리 옆 허공에 간다
        if let face, let modelFace {
            let away = simd_length(SIMD2(arm.wrist.x - face.center.x, arm.wrist.y - face.center.y)) / face.width
            let near = 1 - ((away - 1.0) / 1.0).clamped(0, 1)
            if near > 0 {
                let k = modelFace.width / face.width
                let byFace = SIMD2(modelFace.center.x + (arm.wrist.x - face.center.x) * k, modelFace.center.y + (arm.wrist.y - face.center.y) * k)
                let byShoulder = SIMD2(start.x + toWrist.x, start.y + toWrist.y)
                let mixed = simd_mix(byShoulder, byFace, SIMD2(repeating: near * near * (3 - 2 * near)))
                toWrist = SIMD3(mixed.x - start.x, mixed.y - start.y, toWrist.z)
            }
        }
        let far = reach.upper + reach.lower - 0.004, near = abs(reach.upper - reach.lower) + 0.02
        var distance = simd_length(toWrist)
        guard distance > 0.001 else { return arm }
        let direction = toWrist / distance
        distance = min(max(distance, near), far)
        toWrist = direction * distance
        let along = (reach.upper * reach.upper - reach.lower * reach.lower + distance * distance) / (2 * distance)
        let out = (max(0, reach.upper * reach.upper - along * along)).squareRoot()
        var pole = arm.elbow - arm.shoulder
        pole -= simd_dot(pole, direction) * direction
        if simd_length(pole) < 0.001 { pole = SIMD3(0, -1, 0) - simd_dot(SIMD3(0, -1, 0), direction) * direction }
        if simd_length(pole) < 0.001 { pole = SIMD3(1, 0, 0) }
        let wrist = start + toWrist
        return AvatarFrame.Arm(shoulder: start, elbow: start + direction * along + simd_normalize(pole) * out, wrist: wrist,
                               hand: arm.hand.map { $0 - arm.wrist + wrist }, shape: arm.shape, curl: arm.curl, handOK: arm.handOK)
    }

    /// 손 21점에서 손바닥 틀을 만든다
    private static func palmFrame(_ hand: [SIMD3<Float>]) -> simd_float3x3? {
        guard hand.count == SignSpec.handPoints else { return nil }
        return frame(wrist: hand[0], index: hand[5], pinky: hand[17], middle: hand[9])
    }

    /// 손바닥 틀: y는 손목 → 가운뎃손가락 뿌리, x는 집게 뿌리 → 새끼 뿌리, z는 둘에 수직
    private static func frame(wrist: SIMD3<Float>, index: SIMD3<Float>, pinky: SIMD3<Float>, middle: SIMD3<Float>) -> simd_float3x3? {
        let up = middle - wrist
        guard simd_length(up) > 0.001 else { return nil }
        let y = simd_normalize(up)
        var across = pinky - index
        across -= simd_dot(across, y) * y
        guard simd_length(across) > 0.001 else { return nil }
        let x = simd_normalize(across)
        return simd_float3x3(x, y, simd_cross(x, y))
    }

    private static func rotationPart(_ m: simd_float4x4) -> simd_float3x3 {
        simd_float3x3(simd_normalize(m.columns.0.xyz), simd_normalize(m.columns.1.xyz), simd_normalize(m.columns.2.xyz))
    }

    /// 자리는 그대로 두고 방향만 q만큼 더 돌린다
    private static func rotate(_ m: simd_float4x4, by q: simd_quatf) -> simd_float4x4 {
        let r = simd_float3x3(q)
        var result = simd_float4x4(SIMD4(r * m.columns.0.xyz, 0), SIMD4(r * m.columns.1.xyz, 0), SIMD4(r * m.columns.2.xyz, 0), m.columns.3)
        result.columns.3.w = 1
        return result
    }

    /// 한 방향을 다른 방향으로 옮기는 가장 작은 회전
    private static func shortest(from a: SIMD3<Float>, to b: SIMD3<Float>) -> simd_quatf {
        if simd_dot(a, b) < -0.9999 {
            // 정반대면 축을 정할 수 없어서 아무 수직 축으로 반 바퀴 돌린다
            let other: SIMD3<Float> = abs(a.x) < 0.9 ? SIMD3(1, 0, 0) : SIMD3(0, 1, 0)
            return simd_quatf(angle: .pi, axis: simd_normalize(simd_cross(a, other)))
        }
        return simd_quatf(from: a, to: b)
    }

    private static func color(_ hex: UInt32) -> PlatformColor {
        PlatformColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                      blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

private extension SIMD4 where Scalar == Float {
    var xyz: SIMD3<Float> { SIMD3(x, y, z) }
}

private extension SCNNode {
    /// 뼈대의 맨 위 뼈. 이름이 같은 묶음 노드(파일의 최상위 'root')가 아니라 살갗이 실제로 쓰는 뼈를 찾는다
    func skinnerRoot(in model: SCNNode) -> SCNNode? {
        var bones: [SCNNode] = []
        model.enumerateHierarchy { node, stop in
            if let skinner = node.skinner, !skinner.bones.isEmpty {
                bones = skinner.bones
                stop.pointee = true
            }
        }
        guard var top = bones.first else { return nil }
        let set = Set(bones.map(ObjectIdentifier.init))
        while let parent = top.parent, set.contains(ObjectIdentifier(parent)) { top = parent }
        return top
    }
}
