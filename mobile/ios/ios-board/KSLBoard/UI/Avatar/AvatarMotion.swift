import Foundation
import simd

/// 3D 인형의 한 장면. 단위는 미터.
/// 인형은 +Z(보는 사람 쪽)를 보고 있고, X는 보는 사람의 오른쪽, Y는 위다. 원점은 구간 전체의 어깨 중심이다
struct AvatarFrame {
    struct Arm {
        var shoulder = SIMD3<Float>()
        var elbow = SIMD3<Float>()
        var wrist = SIMD3<Float>()
        /// 손 21점(0번이 손목). 구간 내내 한 번도 안 잡힌 손이면 비어 있다
        var hand: [SIMD3<Float>] = []
        /// 손 모양만 볼 때 쓰는 21점(손목 기준). 깊이를 부풀리지 않은 값이라 손가락이 굽은 각도를 재는 데 쓴다.
        /// hand는 손바닥 방향을 맞추려고 깊이를 키운 값이어서, 그걸로 각도를 재면 편 손가락도 굽은 것으로 나온다
        var shape: [SIMD3<Float>] = []
        /// 네 손가락(집게~새끼)이 굽은 각도(라디안): x는 뿌리 마디, y는 가운데 마디, z는 끝 마디.
        /// 손가락이 카메라 쪽을 향해 짧게 보이는 프레임은 각도를 믿을 수 없어서, 앞뒤의 믿을 만한 프레임 값으로 이어 채운 것이다
        var curl: [SIMD3<Float>] = []
        /// 이 프레임의 손 좌표를 믿을 수 있는지. false면 손 방향과 손가락을 좌표에서 가져오지 않고
        /// 팔에 이어진 편한 손 모양으로 둔다 (손이 빨리 움직여 흐릿하거나 카메라를 똑바로 가리켜 잘못 잡힌 장면)
        var handOK = true
    }

    /// 인형의 오른팔. 마주 보고 있으므로 보는 사람의 왼쪽에 보인다
    var right = Arm()
    var left = Arm()
    var head = SIMD3<Float>()
    var headRoll: Float = 0
    var headYaw: Float = 0
    /// 좌표에서 본 얼굴 자리(두 귀의 가운데)와 얼굴 폭(두 귀 사이). 팔과 같은 좌표다.
    /// head는 인형 머리에 맞게 높이를 옮긴 값이라, 손이 얼굴 어디에 있는지 볼 때는 이 값을 쓴다. 폭이 0이면 얼굴을 못 본 것이다
    var face = SIMD3<Float>()
    var faceWidth: Float = 0
}

/// 녹화한 좌표(177값)를 3D 인형의 동작으로 옮긴다.
///
/// 좌표에는 화면 위의 자리(x, y)만 믿을 만하게 들어 있어서 깊이는 어림한다.
/// - 팔: 위팔·아래팔의 길이는 변하지 않으므로, 화면에서 짧아 보이는 만큼 앞(보는 사람 쪽)으로 나온 것으로 본다
/// - 손: MediaPipe가 준 손목 기준 깊이를 쓰되, 손바닥 길이가 유지되도록 깊이의 크기를 맞춘다
/// - 손이 안 잡힌 프레임은 앞뒤 프레임 사이를 이어서 채우고, 전체를 시간 방향으로 부드럽게 다듬는다
/// 그래서 이 동작은 기록 그대로가 아니라 본보기로 보여 주려고 다듬은 것이다
struct AvatarMotion {
    /// 인형의 어깨 관절 사이 거리. 좌표의 어깨 폭을 이 길이에 맞춰 전체 크기를 정한다
    static let shoulderSpan: Float = 0.33
    /// 어깨 선에서 머리 중심까지의 높이
    static let neckHeight: Float = 0.204

    let frames: [AvatarFrame]
    /// 동작마다 다른 표. 그려 둔 그림을 낱말끼리 섞지 않는 데 쓴다
    let id = UUID()

    /// 이미 만든 장면들로 동작을 만든다 (실시간으로 한 장씩 만든 장면을 모아 볼 때)
    init(frames: [AvatarFrame]) {
        self.frames = frames
    }

    /// 오래 본 값으로 정한 팔 길이(어깨 폭에 대한 비)와 손바닥 길이(미터). 없으면 그 구간에서 어림한다
    struct Known {
        var upper: Float?
        var lower: Float?
        var palm: Float?
    }

    init?(values all: [[Float]], window: Range<Int>, aspect: Float, known: Known? = nil) {
        guard !window.isEmpty, window.upperBound <= all.count else { return nil }
        let pose = SignSpec.poseStart

        // 화면 좌표를 가로세로 같은 단위(화면 높이)로 바꾼다
        func point(_ frame: [Float], _ index: Int) -> SIMD3<Float>? {
            let x = frame[index * 3], y = frame[index * 3 + 1], z = frame[index * 3 + 2]
            return x.isNaN || y.isNaN ? nil : SIMD3(x * aspect, y, (z.isNaN ? 0 : z) * aspect)
        }
        func flat(_ p: SIMD3<Float>) -> SIMD2<Float> { SIMD2(p.x, p.y) }

        // 크기와 원점: 어깨 폭과 어깨 중심의 가운데값
        var spans: [Float] = [], upper: [Float] = [], lower: [Float] = [], midX: [Float] = [], midY: [Float] = []
        for (i, frame) in all.enumerated() {
            guard let a = point(frame, pose + 11), let b = point(frame, pose + 12) else { continue }
            spans.append(simd_distance(flat(a), flat(b)))
            if window.contains(i) {
                midX.append((a.x + b.x) / 2)
                midY.append((a.y + b.y) / 2)
            }
            for (s, e, w) in [(11, 13, 15), (12, 14, 16)] {
                guard let ps = point(frame, pose + s), let pe = point(frame, pose + e), let pw = point(frame, pose + w) else { continue }
                upper.append(simd_distance(flat(ps), flat(pe)))
                lower.append(simd_distance(flat(pe), flat(pw)))
            }
        }
        guard let span = Self.percentile(spans, 0.5), span > 0.01,
              let ox = Self.percentile(midX, 0.5), let oy = Self.percentile(midY, 0.5) else { return nil }
        let k = Self.shoulderSpan / span
        // 마주 본 모습이 되게 좌우를 뒤집는다 (좌표는 거울처럼 좌우 반전한 화면 기준이다)
        func world(_ p: SIMD3<Float>) -> SIMD2<Float> { SIMD2(-(p.x - ox) * k, -(p.y - oy) * k) }

        // 팔 길이: 가장 길게 보였을 때가 화면과 나란할 때다
        let upperArm = (known?.upper.map { $0 * Self.shoulderSpan } ?? (Self.percentile(upper, 0.95) ?? span) * k).clamped(0.26, 0.40)
        let forearm = (known?.lower.map { $0 * Self.shoulderSpan } ?? (Self.percentile(lower, 0.95) ?? span * 0.85) * k).clamped(0.22, 0.33)

        // 인형의 오른팔 = 실제 오른팔. 좌우 반전한 화면에서는 Pose의 '왼쪽'(11, 13, 15)과 "Left" 라벨 손(21~41번)이 실제 오른쪽이다
        let sides = [(shoulder: 11, elbow: 13, wrist: 15, hand: SignSpec.leftLabelStart),
                     (shoulder: 12, elbow: 14, wrist: 16, hand: SignSpec.rightLabelStart)]
        let count = window.count
        var arms = [[AvatarFrame.Arm]](repeating: [], count: 2)
        var head = [SIMD3<Float>](repeating: SIMD3(), count: count)
        var roll = [Float](repeating: 0, count: count), yaw = [Float](repeating: 0, count: count)

        for (side, joints) in sides.enumerated() {
            var shoulders = [SIMD3<Float>](), elbows = [SIMD3<Float>](), wrists = [SIMD3<Float>]()
            // 손: 손목 기준으로 화면 위의 자리(x, y)와 MediaPipe의 깊이(z)를 따로 모은다
            var offsets = [[SIMD3<Float>]?](repeating: nil, count: count)
            for (n, i) in window.enumerated() {
                let frame = all[i]
                let s = point(frame, pose + joints.shoulder).map(world) ?? shoulders.last.map { SIMD2($0.x, $0.y) } ?? SIMD2()
                let e = point(frame, pose + joints.elbow).map(world) ?? elbows.last.map { SIMD2($0.x, $0.y) } ?? s
                var w = point(frame, pose + joints.wrist).map(world) ?? wrists.last.map { SIMD2($0.x, $0.y) } ?? e
                if let root = point(frame, joints.hand) {
                    w = world(root)
                    offsets[n] = (0..<SignSpec.handPoints).map { j in
                        guard let p = point(frame, joints.hand + j) else { return SIMD3() }
                        return SIMD3(-(p.x - root.x) * k, -(p.y - root.y) * k, -(p.z - root.z) * k)
                    }
                }
                let elbowDepth = 0.6 * (max(0, upperArm * upperArm - simd_distance_squared(s, e))).squareRoot()
                let wristDepth = elbowDepth + (max(0, forearm * forearm - simd_distance_squared(e, w))).squareRoot()
                shoulders.append(SIMD3(s.x, s.y, 0))
                elbows.append(SIMD3(e.x, e.y, elbowDepth))
                wrists.append(SIMD3(w.x, w.y, wristDepth))
            }
            shoulders = Self.smooth(shoulders)
            elbows = Self.smooth(elbows)
            wrists = Self.smooth(wrists)
            let hands = Self.fillAndSmooth(offsets, palm: known?.palm)
            let curls = hands.map { Self.curls($0.plain, palmTowardMinusZ: side == 0) }
            arms[side] = (0..<count).map { n in
                AvatarFrame.Arm(shoulder: shoulders[n], elbow: elbows[n], wrist: wrists[n],
                                hand: hands.map { $0.turned[n].map { $0 + wrists[n] } } ?? [],
                                shape: hands.map { $0.plain[n] } ?? [], curl: curls.map { $0[n] } ?? [])
            }
        }

        var face = [SIMD3<Float>](repeating: SIMD3(), count: count), faceWidth = [Float](repeating: 0, count: count)
        for (n, i) in window.enumerated() {
            let frame = all[i]
            guard let a = point(frame, pose + 7).map(world), let b = point(frame, pose + 8).map(world) else {
                if n > 0 { head[n] = head[n - 1]; roll[n] = roll[n - 1]; yaw[n] = yaw[n - 1]; face[n] = face[n - 1]; faceWidth[n] = faceWidth[n - 1] }
                continue
            }
            let (low, high) = a.x < b.x ? (a, b) : (b, a)
            let center = (a + b) / 2
            head[n] = SIMD3(center.x, center.y, 0.03)
            face[n] = SIMD3(center.x, center.y, 0)
            faceWidth[n] = simd_distance(a, b)
            roll[n] = atan2(high.y - low.y, high.x - low.x)
            if let nose = point(frame, pose).map(world) {
                let half = max(0.02, simd_distance(a, b) / 2)
                yaw[n] = asin(((nose.x - center.x) / half * 0.8).clamped(-0.9, 0.9))
            }
        }
        // 머리 높이: 인형의 머리 크기에 맞게 어깨 위 일정한 높이에 두고, 좌표에서는 움직임(끄덕임, 기울임)만 가져온다
        let lift = Self.neckHeight - (Self.percentile(head.map(\.y), 0.5) ?? Self.neckHeight)
        head = Self.smooth(head.map { SIMD3($0.x, $0.y + lift, $0.z) })
        roll = Self.smooth(roll.map { SIMD3($0, 0, 0) }).map(\.x)
        yaw = Self.smooth(yaw.map { SIMD3($0, 0, 0) }).map(\.x)

        face = Self.smooth(face)
        faceWidth = Self.smooth(faceWidth.map { SIMD3($0, 0, 0) }).map(\.x)
        frames = (0..<count).map { n in
            AvatarFrame(right: arms[0][n], left: arms[1][n], head: head[n], headRoll: roll[n], headYaw: yaw[n],
                        face: face[n], faceWidth: faceWidth[n])
        }
    }

    /// 손이 안 잡힌 프레임을 앞뒤에서 이어 채우고, 손바닥 길이가 유지되게 깊이를 맞춘 뒤 다듬는다.
    /// 반환: 프레임마다 손목 기준 21점. 한 번도 안 잡혔으면 nil
    static func fillAndSmooth(_ raw: [[SIMD3<Float>]?], palm knownPalm: Float? = nil) -> (turned: [[SIMD3<Float>]], plain: [[SIMD3<Float>]])? {
        let seen = raw.indices.filter { raw[$0] != nil }
        guard !seen.isEmpty else { return nil }
        // 손바닥(손목 → 가운뎃손가락 뿌리)이 화면과 나란했을 때의 길이
        let palms = seen.map { simd_length(SIMD2(raw[$0]![9].x, raw[$0]![9].y)) }
        let palm = max(knownPalm ?? percentile(palms, 0.9) ?? 0.08, 0.05)

        var filled = [[SIMD3<Float>]](repeating: [], count: raw.count)
        var gains = [Float](repeating: 1, count: raw.count)
        for n in raw.indices {
            let before = seen.last { $0 <= n }, after = seen.first { $0 >= n }
            switch (before, after) {
            case let (b?, a?) where a != b:
                let t = Float(n - b) / Float(a - b)
                filled[n] = zip(raw[b]!, raw[a]!).map { simd_mix($0, $1, SIMD3(repeating: t)) }
            case let (b?, _):
                filled[n] = raw[b]!
            case let (_, a?):
                filled[n] = raw[a]!
            default:
                break
            }
            // 화면에서 짧아 보이는 만큼 깊이 쪽으로 누운 것으로 보고, MediaPipe 깊이의 크기를 거기에 맞춘다
            let seenLength = simd_length(SIMD2(filled[n][9].x, filled[n][9].y))
            let need = (max(0, palm * palm - seenLength * seenLength)).squareRoot()
            gains[n] = (need / max(abs(filled[n][9].z), 0.004)).clamped(1, 3)
        }
        gains = smooth(gains.map { SIMD3($0, 0, 0) }).map(\.x)
        // 점마다 시간 방향으로 다듬는다
        func smoothed(_ frames: [[SIMD3<Float>]]) -> [[SIMD3<Float>]] {
            var result = frames
            for j in 0..<SignSpec.handPoints {
                let track = smooth(frames.map { $0[j] })
                for n in result.indices { result[n][j] = track[n] }
            }
            return result
        }
        let plain = smoothed(filled)
        for n in filled.indices {
            filled[n] = filled[n].map { SIMD3($0.x, $0.y, $0.z * gains[n]) }
        }
        return (smoothed(filled), plain)
    }

    /// 네 손가락이 굽은 각도를 프레임마다 잰다. 반환: [프레임][손가락 4개] (뿌리, 가운데, 끝)
    ///
    /// MediaPipe가 주는 손의 깊이는 흔들림이 커서, 깊이로 각도를 재면 편 손가락도 굽은 것으로 나온다.
    /// 그래서 화면 위의 모양(x, y)만 쓴다. 곧은 손가락은 어느 쪽에서 봐도 화면에서 곧게 보인다는 점을 이용한다
    /// - 가운데·끝 마디: 화면에서 앞뒤 마디가 꺾인 각도
    /// - 뿌리 마디: 손등 뼈 방향에서 꺾인 각도(손가락을 벌린 만큼은 뺀다)와, 첫 마디가 짧게 보이는 정도(주먹을 정면에서 볼 때) 가운데 큰 쪽
    static func curls(_ shapes: [[SIMD3<Float>]], palmTowardMinusZ: Bool) -> [[SIMD3<Float>]] {
        func flat(_ v: SIMD3<Float>) -> SIMD2<Float> { SIMD2(v.x, v.y) }
        func angle(_ u: SIMD2<Float>, _ v: SIMD2<Float>) -> Float {
            let a = simd_length(u), b = simd_length(v)
            guard a > 0.0005, b > 0.0005 else { return 0 }
            return acos((simd_dot(u, v) / (a * b)).clamped(-1, 1))
        }
        var result = [[SIMD3<Float>]](repeating: [SIMD3<Float>](repeating: SIMD3(), count: 4), count: shapes.count)
        // 손바닥이 화면을 얼마나 마주 보는지 (0~1). 손이 카메라에 가까워지면 크게 보이므로 길이가 아니라 손바닥 면의 방향으로 잰다
        let facingOf: [Float] = shapes.map { p in
            guard p.count == SignSpec.handPoints else { return 0 }
            let normal = simd_cross(p[5] - p[0], p[17] - p[0])
            let length = simd_length(normal)
            return length > 0.00001 ? abs(normal.z) / length : 0
        }
        for finger in 0..<4 {
            let a = 5 + finger * 4
            let usable = shapes.indices.filter { shapes[$0].count == SignSpec.handPoints }
            // 손등 뼈와 첫 마디가 가장 길게 보인 길이: 손바닥이 화면과 나란하고 손가락을 폈을 때다
            let ratios = usable.compactMap { n -> Float? in
                let meta = simd_length(flat(shapes[n][a] - shapes[n][0]))
                return meta > 0.001 && facingOf[n] > 0.8 ? simd_length(flat(shapes[n][a + 1] - shapes[n][a])) / meta : nil
            }
            let ratio = (percentile(ratios, 0.9) ?? 0.45).clamped(0.3, 0.6)
            // 손가락을 다 폈을 때 뿌리에서 끝까지의 길이(손등 뼈 길이에 대한 비)
            let spans = usable.compactMap { n -> Float? in
                let meta = simd_length(flat(shapes[n][a] - shapes[n][0]))
                return meta > 0.001 && facingOf[n] > 0.8 ? simd_length(flat(shapes[n][a + 3] - shapes[n][a])) / meta : nil
            }
            let span = (percentile(spans, 0.9) ?? 0.9).clamped(0.6, 1.2)

            var values = [SIMD3<Float>?](repeating: nil, count: shapes.count)
            var seen = [Float](repeating: 0, count: shapes.count)
            for n in usable {
                let p = shapes[n]
                let meta = flat(p[a] - p[0]), one = flat(p[a + 1] - p[a]), two = flat(p[a + 2] - p[a + 1]), three = flat(p[a + 3] - p[a + 2])
                let metaLength = simd_length(meta)
                guard metaLength > 0.001 else { continue }
                let byAngle = max(0, angle(meta, one) - 0.4)
                // 손바닥이 화면과 나란할 때만 '짧게 보이는 정도'를 믿는다
                let facing = ((facingOf[n] - 0.55) / 0.3).clamped(0, 1)
                let byLength = max(0, acos((simd_length(one) / (ratio * metaLength)).clamped(0, 1)) - 0.5) * facing
                // 주먹: 손바닥은 화면과 나란한데 손가락 뿌리에서 끝까지가 아주 짧게 보이면 말아 쥔 것이다
                let reach = simd_length(flat(p[a + 3] - p[a])) / max(span * metaLength, 0.001)
                let fist = ((0.8 - reach) / 0.5).clamped(0, 1) * facing
                values[n] = SIMD3(max(byAngle, byLength, fist * 1.45), max(angle(one, two), fist * 1.7), max(angle(two, three), fist * 1.1))
                // 주먹으로 본 프레임은 마디가 짧게 보여도 믿는다
                seen[n] = fist > 0.5 ? .greatestFiniteMagnitude : simd_length(two) + simd_length(three)
            }
            // 가운데·끝 마디가 너무 짧게 보이는 프레임(손가락 끝이 카메라를 향함)은 방향을 믿을 수 없어서 앞뒤 값으로 잇는다
            let longest = percentile(seen.filter { $0 > 0 && $0 < 1000 }, 0.9) ?? 0
            let good = values.indices.filter { values[$0] != nil && seen[$0] >= longest * 0.35 }
            var track = [SIMD3<Float>](repeating: SIMD3(0.1, 0.1, 0.1), count: shapes.count)
            for n in track.indices {
                let before = good.last { $0 <= n }, after = good.first { $0 >= n }
                switch (before, after) {
                case let (b?, a?) where a != b:
                    track[n] = simd_mix(values[b]!, values[a]!, SIMD3(repeating: Float(n - b) / Float(a - b)))
                case let (b?, _): track[n] = values[b]!
                case let (_, a?): track[n] = values[a]!
                default: break
                }
            }
            track = smooth(track)
            for n in track.indices { result[n][finger] = track[n] }
        }
        return result
    }

    /// 시간 방향으로 다듬기 (1, 2, 3, 2, 1). 본보기를 매끄럽게 보여 주려는 것이다
    private static func smooth(_ values: [SIMD3<Float>]) -> [SIMD3<Float>] {
        guard values.count > 2 else { return values }
        let weights: [Float] = [1, 2, 3, 2, 1]
        return values.indices.map { i in
            var sum = SIMD3<Float>(), total: Float = 0
            for (k, weight) in weights.enumerated() {
                let j = (i + k - 2).clamped(0, values.count - 1)
                sum += values[j] * weight
                total += weight
            }
            return sum / total
        }
    }

    fileprivate static func percentile(_ values: [Float], _ p: Float) -> Float? {
        guard !values.isEmpty else { return nil }
        let sorted = values.sorted()
        return sorted[min(sorted.count - 1, Int(Float(sorted.count) * p))]
    }
}
