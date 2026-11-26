import Foundation

/// 좌표를 좌우로 뒤집는다: 왼손으로 한 동작을 오른손으로 한 것처럼 만든다.
/// 모델은 오른손잡이의 수어만 배웠다. 왼손잡이는 손을 바꿔서 수어하고, 본보기를 거울처럼 따라 하는 사람도
/// 반대쪽 손을 쓰게 된다. 그래서 읽을 때 뒤집은 것도 함께 판정한다 (BoardModel.finish)
enum HandMirror {
    /// 몸의 왼쪽·오른쪽 짝 (Pose 0~16)
    private static let pairs = [(1, 4), (2, 5), (3, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16)]

    static func frames(_ frames: [[Float]]) -> [[Float]] {
        frames.map { frame in
            guard frame.count == SignSpec.numValues else { return frame }
            var out = frame
            func copy(_ from: Int, to: Int) {
                let x = frame[from * 3]
                out[to * 3] = x.isNaN ? .nan : 1 - x
                out[to * 3 + 1] = frame[from * 3 + 1]
                out[to * 3 + 2] = frame[from * 3 + 2]
            }
            // 두 손 자리를 맞바꾼다
            for j in 0..<SignSpec.handPoints {
                copy(SignSpec.leftLabelStart + j, to: SignSpec.rightLabelStart + j)
                copy(SignSpec.rightLabelStart + j, to: SignSpec.leftLabelStart + j)
            }
            // 몸: 가운데 점(코)은 자리만 뒤집고, 짝이 있는 점은 서로 바꾼다
            for k in 0..<SignSpec.posePoints { copy(SignSpec.poseStart + k, to: SignSpec.poseStart + k) }
            for (a, b) in pairs {
                copy(SignSpec.poseStart + a, to: SignSpec.poseStart + b)
                copy(SignSpec.poseStart + b, to: SignSpec.poseStart + a)
            }
            return out
        }
    }
}
