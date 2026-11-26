#if os(iOS)
import AVFoundation
import CoreVideo

/// 카메라 → 세로로 세우고 좌우 반전 → MediaPipe → 177개 값.
/// KSLSign의 TranslatorModel.setUp과 같은 순서로 같은 부품(CameraController, FrameOrienter, LandmarkDetector, FrameBuilder)을 쓴다.
/// 화면에는 영상을 그리지 않으므로 미리보기 그림은 만들지 않는다
@MainActor
final class CameraSource: FrameSource {
    var onFrame: ((FrameResult, Double, Int, Int) -> Void)?
    private let camera = CameraController()
    private var prepared = false

    var now: Double { camera.now }
    var isFront: Bool { camera.position == .front }
    var zoomLabels: [String] { camera.zooms.map(\.label) }
    var zoomIndex: Int { camera.zoomIndex }

    func prepare() async throws {
        guard !prepared else { return }
        guard await AVCaptureDevice.requestAccess(for: .video) else { throw SourceError.cameraDenied }
        let detector = try LandmarkDetector()
        let orienter = FrameOrienter()
        camera.onFrame = { [weak self] raw, time, turns in
            guard let buffer = orienter.selfie(from: raw, turns: turns) else { return }
            let width = CVPixelBufferGetWidth(buffer), height = CVPixelBufferGetHeight(buffer)
            let found: (hands: [HandDetection], poses: [PoseDetection])?
            do {
                found = try detector.detect(buffer, timestampMs: Int((time * 1000).rounded()))
            } catch {
                print("MediaPipe 오류:", error)
                return
            }
            guard let found else { return }
            let result = FrameBuilder.build(hands: found.hands, poses: found.poses, width: width, height: height)
            Task { @MainActor in self?.onFrame?(result, time, width, height) }
        }
        try camera.configure(position: UserDefaults.standard.string(forKey: "camera") == "back" ? .back : .front)
        prepared = true
    }

    func start() { camera.start() }
    func stop() { camera.stop() }

    func useFront(_ front: Bool) throws {
        try camera.configure(position: front ? .front : .back)
    }

    func setZoom(_ index: Int) { camera.setZoom(index) }
}
#endif
