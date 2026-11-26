import Foundation
import simd

/// 깊이까지 잰 3D 관절 좌표(AIHub '수어 영상'의 keypoint)로 만드는 동작.
/// 177값 좌표와 달리 앞뒤 거리가 실제 값이라, 어림하지 않고 그대로 옮긴다
extension AvatarMotion {
    /// 한 프레임의 관절. 마주 본 모습 기준(x는 보는 사람의 오른쪽, y는 위, z는 보는 사람 쪽), 단위는 미터. 못 잰 점은 null
    struct Joints: Decodable {
        let rs, re, rw, ls, le, lw, nose, rear, lear: [Float]?
        let rh, lh: [[Float]?]
    }

    /// - Parameter screen: 카메라 한 대의 영상에서 어림한 3D(MediaPipe)일 때 함께 주는 화면 좌표(177값).
    ///   그런 3D는 손의 앞뒤 값이 부정확해서, 그걸로 손가락 굽힘을 재면 손등은 카메라 쪽으로 눕고 손가락만 꺾인
    ///   이상한 손이 된다(손가락이 길어 보인다). 그래서 굽힘은 화면 위의 모양으로 잰다. 여러 각도로 잰 3D(AIHub)면 nil
    init?(joints all: [Joints], window: Range<Int>, screen: (values: [[Float]], aspect: Float)? = nil) {
        guard !window.isEmpty, window.upperBound <= all.count else { return nil }
        let count = window.count
        func vector(_ v: [Float]?) -> SIMD3<Float>? { v.flatMap { $0.count == 3 ? SIMD3($0[0], $0[1], $0[2]) : nil } }
        /// 못 잰 프레임은 앞뒤에서 가까운 값으로 채운다. 한 번도 못 쟀으면 nil
        func track(_ pick: (Joints) -> [Float]?) -> [SIMD3<Float>]? {
            let raw = window.map { vector(pick(all[$0])) }
            guard raw.contains(where: { $0 != nil }) else { return nil }
            var filled = [SIMD3<Float>](repeating: SIMD3(), count: count)
            var last: SIMD3<Float>?
            for n in 0..<count { if let v = raw[n] { last = v }; if let last { filled[n] = last } }
            if let first = raw.firstIndex(where: { $0 != nil }) { for n in 0..<first { filled[n] = raw[first]! } }
            return filled
        }
        guard let rs = track(\.rs), let ls = track(\.ls), let re = track(\.re), let le = track(\.le),
              let rw = track(\.rw), let lw = track(\.lw) else { return nil }

        // 크기와 원점: 어깨 폭과 어깨 중심의 가운데값
        let spans = (0..<count).map { simd_distance(rs[$0], ls[$0]) }
        guard let span = Self.median(spans), span > 0.05 else { return nil }
        let k = Self.shoulderSpan / span
        let mids = (0..<count).map { (rs[$0] + ls[$0]) / 2 }
        let origin = SIMD3(Self.median(mids.map(\.x)) ?? 0, Self.median(mids.map(\.y)) ?? 0, Self.median(mids.map(\.z)) ?? 0)
        func world(_ points: [SIMD3<Float>]) -> [SIMD3<Float>] { Self.smoothed(points.map { ($0 - origin) * k }) }

        func arm(_ shoulder: [SIMD3<Float>], _ elbow: [SIMD3<Float>], _ wrist: [SIMD3<Float>],
                 _ hand: (Joints) -> [[Float]?], right: Bool) -> [AvatarFrame.Arm] {
            let s = world(shoulder), e = world(elbow), w = world(wrist)
            // 손 21점: 점마다 따로 채우고 다듬은 뒤, 손목을 팔의 손목 자리에 맞춘다
            var points: [[SIMD3<Float>]] = []
            for j in 0..<SignSpec.handPoints {
                guard let one = track({ let h = hand($0); return j < h.count ? h[j] : nil }) else { points = []; break }
                points.append(world(one))
            }
            let seen = points.count == SignSpec.handPoints
            var shapes: [[SIMD3<Float>]] = seen ? (0..<count).map { n in points.map { $0[n] - points[0][n] } } : []
            var curls = seen ? Self.curls3D(shapes, palmTowardMinusZ: right) : []
            var trusted = [Bool](repeating: true, count: count)
            if seen, let screen, screen.values.count == all.count {
                // 화면 좌표의 손 21점을 손목 기준으로 모은다 (좌우 반전을 되돌린다). 오른손은 "Left" 라벨 슬롯이다
                let slot = right ? SignSpec.leftLabelStart : SignSpec.rightLabelStart
                let offsets: [[SIMD3<Float>]?] = window.map { i in
                    let frame = screen.values[i]
                    guard !frame[slot * 3].isNaN else { return nil }
                    let root = SIMD3(frame[slot * 3] * screen.aspect, frame[slot * 3 + 1], frame[slot * 3 + 2] * screen.aspect)
                    return (0..<SignSpec.handPoints).map { j in
                        let p = SIMD3(frame[(slot + j) * 3] * screen.aspect, frame[(slot + j) * 3 + 1], frame[(slot + j) * 3 + 2] * screen.aspect)
                        return p.x.isNaN ? SIMD3() : SIMD3(-(p.x - root.x), -(p.y - root.y), -(p.z - root.z))
                    }
                }
                if let flat = Self.fillAndSmooth(offsets) {
                    curls = Self.curls(flat.plain, palmTowardMinusZ: right)
                }
                // 믿을 수 있는 프레임: 손이 잡혔고, 손등(손목 → 가운뎃손가락 뿌리)이 화면에서 평소 길이의 55% 넘게 보인다.
                // 그보다 짧게 보이면 손이 카메라를 똑바로 가리킨다는 뜻인데, 실제로는 대개 흐릿해서 잘못 잡힌 것이다
                let palms: [Float?] = offsets.map { $0.map { simd_length(SIMD2($0[9].x, $0[9].y)) } }
                let usual = Self.median(palms.compactMap { $0 }.sorted().suffix(max(1, palms.compactMap { $0 }.count / 3)).map { $0 }) ?? 0
                let raw = palms.map { ($0 ?? 0) > usual * 0.55 }
                // 한두 프레임씩 왔다 갔다 하면 손이 떨리므로, 앞뒤 다섯 프레임의 다수를 따른다
                trusted = raw.indices.map { i in
                    let near = (max(0, i - 2)...min(raw.count - 1, i + 2)).map { raw[$0] }
                    return near.filter { $0 }.count * 2 > near.count
                }
                // 믿을 수 없는 프레임은 가장 가까운 믿을 만한 프레임의 손 모양을 그대로 쓴다. 아래팔이 돌아간 만큼 같이 돌려서,
                // 손이 팔에 붙은 채로 움직이게 한다 (주먹을 쥐고 흔들면 흐릿한 동안에도 주먹인 채로 있다)
                let good = trusted.indices.filter { trusted[$0] }
                for n in trusted.indices where !trusted[n] {
                    guard let from = good.last(where: { $0 < n }) ?? good.first(where: { $0 > n }) else { continue }
                    let before = w[from] - e[from], now = w[n] - e[n]
                    guard simd_length(before) > 0.001, simd_length(now) > 0.001 else { continue }
                    let a = simd_normalize(before), b = simd_normalize(now)
                    let turn = simd_dot(a, b) < -0.999 ? simd_quatf(angle: 0, axis: SIMD3(0, 1, 0)) : simd_quatf(from: a, to: b)
                    shapes[n] = shapes[from].map { turn.act($0) }
                    if curls.count == count { curls[n] = curls[from] }
                    trusted[n] = true
                }
            }
            return (0..<count).map { n in
                AvatarFrame.Arm(shoulder: s[n], elbow: e[n], wrist: w[n],
                                hand: seen ? shapes[n].map { $0 + w[n] } : [], shape: seen ? shapes[n] : [], curl: seen ? curls[n] : [],
                                handOK: trusted[n])
            }
        }
        let right = arm(rs, re, rw, \.rh, right: true), left = arm(ls, le, lw, \.lh, right: false)

        // 머리: 두 귀의 가운데와 기울기, 코로 좌우 돌림
        let rightEar = track(\.rear).map(world), leftEar = track(\.lear).map(world), nose = track(\.nose).map(world)
        frames = (0..<count).map { n in
            var frame = AvatarFrame(right: right[n], left: left[n])
            if let rightEar, let leftEar {
                let a = rightEar[n], b = leftEar[n]
                let center = (a + b) / 2
                frame.face = center
                frame.faceWidth = simd_distance(a, b)
                frame.head = center
                frame.headRoll = atan2(b.y - a.y, b.x - a.x)
                if let nose {
                    frame.headYaw = asin(((nose[n].x - center.x) / max(0.02, frame.faceWidth / 2) * 0.8).clamped(-0.9, 0.9))
                }
            }
            return frame
        }
    }

    /// 네 손가락이 굽은 각도를 3D 손 모양에서 잰다. 반환: [프레임][손가락 4개] (뿌리, 가운데, 끝)
    private static func curls3D(_ shapes: [[SIMD3<Float>]], palmTowardMinusZ: Bool) -> [[SIMD3<Float>]] {
        func angle(_ u: SIMD3<Float>, _ v: SIMD3<Float>) -> Float {
            let a = simd_length(u), b = simd_length(v)
            guard a > 0.0005, b > 0.0005 else { return 0 }
            return acos((simd_dot(u, v) / (a * b)).clamped(-1, 1))
        }
        var result = [[SIMD3<Float>]](repeating: [SIMD3<Float>](repeating: SIMD3(), count: 4), count: shapes.count)
        for finger in 0..<4 {
            let a = 5 + finger * 4
            var values = [SIMD3<Float>](repeating: SIMD3(0.1, 0.1, 0.1), count: shapes.count)
            for (n, p) in shapes.enumerated() {
                // 손바닥 틀: y는 손목 → 가운뎃손가락 뿌리, x는 집게 뿌리 → 새끼 뿌리. 오른손은 -z, 왼손은 +z가 손바닥 쪽이다
                let up = p[9] - p[0]
                var across = p[17] - p[5]
                guard simd_length(up) > 0.001 else { continue }
                let y = simd_normalize(up)
                across -= simd_dot(across, y) * y
                guard simd_length(across) > 0.001 else { continue }
                let z = simd_cross(simd_normalize(across), y)
                let first = p[a + 1] - p[a], second = p[a + 2] - p[a + 1], third = p[a + 3] - p[a + 2]
                let toward = palmTowardMinusZ ? -simd_dot(first, z) : simd_dot(first, z)
                values[n] = SIMD3(atan2(toward, simd_dot(first, y)), angle(first, second), angle(second, third))
            }
            let track = smoothed(values)
            for n in track.indices { result[n][finger] = track[n] }
        }
        return result
    }

    private static func median(_ values: [Float]) -> Float? {
        guard !values.isEmpty else { return nil }
        return values.sorted()[values.count / 2]
    }

    /// 시간 방향으로 가볍게 다듬기 (1, 2, 1)
    private static func smoothed(_ values: [SIMD3<Float>]) -> [SIMD3<Float>] {
        guard values.count > 2 else { return values }
        return values.indices.map { i in
            (values[max(i - 1, 0)] + values[i] * 2 + values[min(i + 1, values.count - 1)]) / 4
        }
    }
}
