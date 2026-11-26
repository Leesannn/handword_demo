import Foundation

/// model_bundle/preprocess.py를 그대로 옮긴 것. 여기를 바꾸면 모델과 맞지 않는다.
/// 계산 순서(float32 연산, 평균의 나눗셈은 float64)까지 numpy와 같게 맞췄다.
enum Preprocess {
    private static let F = SignSpec.numFrames
    private static let P = SignSpec.numPoints
    private static let V = SignSpec.numValues

    /// np.linspace(0, n - 1, 30).astype(int)
    static func resampleIndices(count n: Int) -> [Int] {
        let step = Double(n - 1) / Double(F - 1)
        return (0..<F).map { i in i == F - 1 ? n - 1 : Int(Double(i) * step) }
    }

    /// (프레임 수, 177)을 30프레임으로 맞추고 어깨 중심·너비로 정규화한다. 미검출(NaN)은 0이 된다.
    /// aspect는 좌표를 뽑은 화면의 너비 / 높이다. 반환: 30 × 177 (행 우선)
    static func run(_ seq: [[Float]], aspect: Double) -> [Float] {
        var points = [Float](repeating: 0, count: F * V)
        for (f, i) in resampleIndices(count: seq.count).enumerated() {
            for v in 0..<V { points[f * V + v] = seq[i][v] }
        }
        // x와 z는 화면 너비 단위, y는 화면 높이 단위라서 높이 단위로 맞춘다
        let a = Float(aspect)
        for f in 0..<F {
            for p in 0..<P {
                points[f * V + p * 3] *= a
                points[f * V + p * 3 + 2] *= a
            }
        }
        let l = (SignSpec.poseStart + SignSpec.leftShoulder) * 3
        let r = (SignSpec.poseStart + SignSpec.rightShoulder) * 3
        var center = [[Float]](repeating: [0, 0, 0], count: F)
        var width = [Float](repeating: 0, count: F)
        for f in 0..<F {
            let base = f * V
            for c in 0..<3 { center[f][c] = (points[base + l + c] + points[base + r + c]) / 2 }
            let dx = points[base + l] - points[base + r]
            let dy = points[base + l + 1] - points[base + r + 1]
            width[f] = (dx * dx + dy * dy).squareRoot()
        }

        // 어깨가 안 잡힌 프레임은 같은 시퀀스의 평균값을 쓴다
        let minWidth = Float(1e-6 as Double)
        let valid = width.map { !$0.isNaN && $0 > minWidth }
        let count = valid.filter { $0 }.count
        if count > 0 {
            var sum: [Float] = [0, 0, 0]
            for f in 0..<F where valid[f] {
                for c in 0..<3 { sum[c] += center[f][c] }
            }
            let meanCenter = sum.map { Float(Double($0) / Double(count)) }
            let validWidths = (0..<F).filter { valid[$0] }.map { width[$0] }
            let meanWidth = Float(Double(numpySum(validWidths[...])) / Double(count))
            for f in 0..<F where !valid[f] {
                center[f] = meanCenter
                width[f] = meanWidth
            }
        } else {
            center = [[Float]](repeating: [0, 0, 0], count: F)
            width = [Float](repeating: 1, count: F)
        }

        var out = [Float](repeating: 0, count: F * V)
        for f in 0..<F {
            for p in 0..<P {
                for c in 0..<3 {
                    // 손의 z는 손목 기준이라 포즈의 어깨 깊이를 빼지 않는다
                    let offset: Float = (c == 2 && p < SignSpec.poseStart) ? 0 : center[f][c]
                    let i = f * V + p * 3 + c
                    out[i] = nanToNum((points[i] - offset) / width[f])
                }
            }
        }
        return out
    }

    /// preprocess.py의 main_hand_missing_ratio: 더 많이 잡힌 손을 동작에 쓴 손으로 보고, 그 손이 안 잡힌 프레임 비율
    static func mainHandMissingRatio(_ seq: [[Float]]) -> Double {
        func missing(_ start: Int) -> Double {
            let n = seq.filter { $0[(start * 3)..<((start + SignSpec.handPoints) * 3)].contains { $0.isNaN } }.count
            return Double(n) / Double(seq.count)
        }
        return min(missing(SignSpec.rightLabelStart), missing(SignSpec.leftLabelStart))
    }

    /// np.nan_to_num: NaN → 0, ±inf → float32 최댓값
    private static func nanToNum(_ v: Float) -> Float {
        if v.isNaN { return 0 }
        if v.isInfinite { return v > 0 ? .greatestFiniteMagnitude : -.greatestFiniteMagnitude }
        return v
    }

    /// numpy가 float32 1차원 합에 쓰는 pairwise 합
    static func numpySum(_ a: ArraySlice<Float>) -> Float {
        let n = a.count, s = a.startIndex
        if n < 8 { return a.reduce(0, +) }
        if n <= 128 {
            var r = (0..<8).map { a[s + $0] }
            var i = 8
            while i < n - n % 8 {
                for j in 0..<8 { r[j] += a[s + i + j] }
                i += 8
            }
            var res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]))
            while i < n {
                res += a[s + i]
                i += 1
            }
            return res
        }
        var n2 = n / 2
        n2 -= n2 % 8
        return numpySum(a[s..<(s + n2)]) + numpySum(a[(s + n2)...])
    }
}
