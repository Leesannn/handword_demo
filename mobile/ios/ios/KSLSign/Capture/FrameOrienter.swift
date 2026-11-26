import Accelerate
import CoreVideo

/// 카메라 원본 화면을 똑바로 세우고 좌우 반전해, 학습 때처럼 셀카 미리보기와 같은 화면을 만든다.
/// 돌리는 양은 카메라가 알려준 세로 기준 회전(CameraController.turnsForPortrait)을 쓴다.
/// 사람의 머리 방향으로 맞추던 방식은 가까운 사람이나 기울어진 폰에 속아 화면을 잘못 돌려서 뺐다.
/// 후면 카메라도 학습 규격대로 좌우 반전한다 (웹캠 원본도 후면처럼 실제 모습이었고 학습 때 뒤집었다).
final class FrameOrienter {
    private var source = (turns: -1, width: 0, height: 0)
    private var pool: CVPixelBufferPool?
    private var rotated = vImage_Buffer()
    private var size = (width: 0, height: 0)

    deinit { free(rotated.data) }

    /// 원본을 시계 방향으로 turns×90도 돌리고 좌우 반전한 BGRA 화면. 실패하면 nil
    func selfie(from source: CVPixelBuffer, turns: Int) -> CVPixelBuffer? {
        let w = CVPixelBufferGetWidth(source), h = CVPixelBufferGetHeight(source)
        if self.source.turns != turns || self.source.width != w || self.source.height != h {
            self.source = (turns, w, h)
            print("[화면] 카메라 원본 \(w)x\(h) → 시계 방향 \(turns * 90)도 돌리고 좌우 반전")
        }
        let outW = turns % 2 == 1 ? h : w, outH = turns % 2 == 1 ? w : h
        guard prepare(width: outW, height: outH), let pool else { return nil }
        var made: CVPixelBuffer?
        guard CVPixelBufferPoolCreatePixelBuffer(nil, pool, &made) == kCVReturnSuccess, let output = made else { return nil }
        CVPixelBufferLockBaseAddress(source, .readOnly)
        CVPixelBufferLockBaseAddress(output, [])
        defer {
            CVPixelBufferUnlockBaseAddress(output, [])
            CVPixelBufferUnlockBaseAddress(source, .readOnly)
        }
        var src = vImage_Buffer(data: CVPixelBufferGetBaseAddress(source), height: vImagePixelCount(h),
                                width: vImagePixelCount(w), rowBytes: CVPixelBufferGetBytesPerRow(source))
        var dst = vImage_Buffer(data: CVPixelBufferGetBaseAddress(output), height: vImagePixelCount(outH),
                                width: vImagePixelCount(outW), rowBytes: CVPixelBufferGetBytesPerRow(output))
        let rotation = [kRotate0DegreesClockwise, kRotate90DegreesClockwise, kRotate180DegreesClockwise, kRotate270DegreesClockwise][turns]
        var black: [UInt8] = [0, 0, 0, 255]
        guard vImageRotate90_ARGB8888(&src, &rotated, UInt8(rotation), &black, vImage_Flags(kvImageNoFlags)) == kvImageNoError,
              vImageHorizontalReflect_ARGB8888(&rotated, &dst, vImage_Flags(kvImageNoFlags)) == kvImageNoError else { return nil }
        return output
    }

    private func prepare(width: Int, height: Int) -> Bool {
        if size.width == width && size.height == height { return true }
        free(rotated.data)
        rotated = vImage_Buffer()
        guard vImageBuffer_Init(&rotated, vImagePixelCount(height), vImagePixelCount(width), 32, vImage_Flags(kvImageNoFlags)) == kvImageNoError else {
            return false
        }
        let attributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height,
            kCVPixelBufferIOSurfacePropertiesKey as String: [String: Any](),
        ]
        var newPool: CVPixelBufferPool?
        guard CVPixelBufferPoolCreate(nil, nil, attributes as CFDictionary, &newPool) == kCVReturnSuccess else { return false }
        pool = newPool
        size = (width, height)
        return true
    }
}
