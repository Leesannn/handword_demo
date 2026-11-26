import AVFoundation
import os

enum CameraError: LocalizedError {
    case noCamera, cannotConfigure

    var errorDescription: String? {
        switch self {
        case .noCamera: "카메라를 찾지 못했습니다 (시뮬레이터에서는 카메라가 없습니다)"
        case .cannotConfigure: "카메라를 설정하지 못했습니다"
        }
    }
}

/// 전면 또는 후면 카메라 원본 화면을 약 15fps로 넘긴다. 똑바로 세우고 좌우 반전하는 일은 FrameOrienter가 한다.
/// - 전면: 폰을 들고 팔 길이에서 찍어도 상체와 손이 들어오게 가장 넓게 찍는다 (widen 참고)
/// - 후면: 초광각(0.5×)과 광각(1×)을 오갈 수 있는 장치를 쓰고 1×로 시작한다 (다른 사람이 들고 찍는 경우)
final class CameraController: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    struct Zoom {
        let label: String
        let factor: CGFloat
    }

    let session = AVCaptureSession()
    /// 카메라 큐에서 불린다: (카메라 원본 BGRA 화면, 초 단위 시각, 원본을 세우려면 시계 방향으로 돌릴 90도 횟수)
    var onFrame: ((CVPixelBuffer, Double, Int) -> Void)?
    private(set) var position = AVCaptureDevice.Position.front
    /// 지금 카메라의 세로 기준 회전 (카메라 큐에서도 읽는다)
    private let portraitTurns = OSAllocatedUnfairLock(initialState: 0)
    private(set) var zooms: [Zoom] = []
    private(set) var zoomIndex = 0
    private var device: AVCaptureDevice?
    private let output = AVCaptureVideoDataOutput()
    private let sessionQueue = DispatchQueue(label: "camera.session")
    private let frameQueue = DispatchQueue(label: "camera.frames")
    private var lastTime = -Double.infinity
    private var outputAdded = false

    /// 처음 설정과 카메라 바꾸기에 함께 쓴다
    func configure(position: AVCaptureDevice.Position) throws {
        guard let device = Self.camera(at: position) else { throw CameraError.noCamera }
        let input = try AVCaptureDeviceInput(device: device)
        session.beginConfiguration()
        defer { session.commitConfiguration() }
        if !outputAdded {
            // 포맷은 widen에서 직접 고른다
            if session.canSetSessionPreset(.inputPriority) { session.sessionPreset = .inputPriority }
            // MediaPipe iOS는 BGRA 화면을 받는다
            output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
            output.alwaysDiscardsLateVideoFrames = true
            output.setSampleBufferDelegate(self, queue: frameQueue)
            guard session.canAddOutput(output) else { throw CameraError.cannotConfigure }
            session.addOutput(output)
            outputAdded = true
            let turns = [AVCaptureDevice.Position.front, .back].map { p in Self.camera(at: p).map { Self.turnsForPortrait($0) * 90 } }
            print("[카메라] 세로 기준 회전: 전면 \(turns[0].map(String.init) ?? "-")도, 후면 \(turns[1].map(String.init) ?? "-")도")
        }
        session.inputs.forEach(session.removeInput)
        guard session.canAddInput(input) else { throw CameraError.cannotConfigure }
        session.addInput(input)
        if let connection = output.connection(with: .video) {
            // 연결에서는 돌리거나 뒤집지 않고 원본(회전 0, 반전 없음)을 받는다
            if connection.isVideoRotationAngleSupported(0) { connection.videoRotationAngle = 0 }
            if connection.isVideoMirroringSupported {
                connection.automaticallyAdjustsVideoMirroring = false
                connection.isVideoMirrored = false
            }
        }
        self.device = device
        self.position = position
        zooms = Self.zooms(of: device)
        zoomIndex = position == .back ? zooms.count - 1 : 0
        widen(device)
        let turns = Self.turnsForPortrait(device)
        portraitTurns.withLock { $0 = turns }
        print("[카메라] 세로로 들었을 때 원본을 시계 방향 \(turns * 90)도 돌림")
    }

    /// 세로로 들었을 때 원본을 똑바로 세우려면 시계 방향으로 90도를 몇 번 돌려야 하는지. 카메라마다 다르다
    /// (iPhone 18 Pro Max: 전면 초광각은 원본이 이미 세로라 0, 후면은 90도). 앱이 세로 고정이라 기기 기울기와 상관없이 고정값을 쓴다
    private static func turnsForPortrait(_ device: AVCaptureDevice) -> Int {
        let coordinator = AVCaptureDevice.RotationCoordinator(device: device, previewLayer: nil)
        var angle = coordinator.videoRotationAngleForHorizonLevelCapture
        if #available(iOS 27.0, *) { angle = coordinator.videoRotationAngleRelative(toDeviceOrientation: .portrait) }
        return (Int((angle / 90).rounded()) % 4 + 4) % 4
    }

    /// 후면 0.5× / 1× 바꾸기
    func setZoom(_ index: Int) {
        guard let device, zooms.indices.contains(index), (try? device.lockForConfiguration()) != nil else { return }
        device.videoZoomFactor = zooms[index].factor
        device.unlockForConfiguration()
        zoomIndex = index
    }

    /// 화면 시각(onFrame의 초)과 같은 시계로 잰 지금 시각
    var now: Double {
        CMClockGetTime(session.synchronizationClock ?? CMClockGetHostTimeClock()).seconds
    }

    func start() {
        sessionQueue.async { if !self.session.isRunning { self.session.startRunning() } }
    }

    func stop() {
        sessionQueue.async { if self.session.isRunning { self.session.stopRunning() } }
    }

    /// 전면: 세로로 들었을 때 가로 화각이 가장 넓은 장치 (새 기종은 전면 초광각이 따로 있다).
    /// 후면: 초광각과 광각을 오갈 수 있는 가상 장치가 있으면 그것, 없으면 가로 화각이 가장 넓은 장치
    private static func camera(at position: AVCaptureDevice.Position) -> AVCaptureDevice? {
        if position == .back, let virtual = AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInTripleCamera, .builtInDualWideCamera], mediaType: .video, position: .back).devices.first {
            return virtual
        }
        return AVCaptureDevice.DiscoverySession(
            deviceTypes: [.builtInUltraWideCamera, .builtInWideAngleCamera, .builtInTrueDepthCamera],
            mediaType: .video, position: position).devices
            .max { ($0.formats.map(portraitFieldOfView).max() ?? 0) < ($1.formats.map(portraitFieldOfView).max() ?? 0) }
    }

    /// 가상 장치면 가장 넓은 줌(초광각)과 광각으로 바뀌는 줌 두 가지. 표시는 0.5×, 1×처럼 사진 앱과 같게
    private static func zooms(of device: AVCaptureDevice) -> [Zoom] {
        guard device.isVirtualDevice, let wide = device.virtualDeviceSwitchOverVideoZoomFactors.first.map({ CGFloat($0.doubleValue) }) else {
            return []
        }
        var multiplier = 1 / wide
        if #available(iOS 18.0, *) { multiplier = device.displayVideoZoomFactorMultiplier }
        return [device.minAvailableVideoZoomFactor, wide].map { factor in
            Zoom(label: String(format: "%g×", (factor * multiplier * 10).rounded() / 10), factor: factor)
        }
    }

    /// 세로로 들었을 때의 가로 화각(도). 가로로 긴 포맷은 짧은 변 쪽 화각으로 바꾼다.
    /// 화면비를 바꿀 수 있는 포맷(정사각 센서)은 정사각 화각을 쓴다
    private static func portraitFieldOfView(_ format: AVCaptureDevice.Format) -> Float {
        let d = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
        var fov = format.videoFieldOfView
        if supportsSquare(format), #available(iOS 26.0, *) {
            fov = format.videoFieldOfView(for: .ratio1x1, geometricDistortionCorrected: false)
        }
        guard d.width > d.height else { return fov }
        let half = Float(tan(Double(fov) * .pi / 360)) * Float(d.height) / Float(d.width)
        return atan(half) * 360 / .pi
    }

    /// 정사각(센서 전체) 화면비를 낼 수 있는 포맷인지. 세로로 들었을 때 가로가 가장 넓다
    private static func supportsSquare(_ format: AVCaptureDevice.Format) -> Bool {
        if #available(iOS 26.0, *) { return format.supportedDynamicAspectRatios.contains(.ratio1x1) }
        return false
    }

    /// 해상도 선호: 긴 변이 1280에 가까울수록 좋다 (MediaPipe에 충분하고 처리가 가볍다. 1080 미만은 뒤로)
    private static func resolutionScore(_ format: AVCaptureDevice.Format) -> Int {
        let d = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
        let side = Int(max(d.width, d.height))
        return side < 1080 ? -10000 + side : -abs(side - 1280)
    }

    /// 15fps를 내는 포맷 중 8비트(BGRA 변환이 가벼움) > 세로로 들었을 때 가로 화각 > 해상도(긴 변 1280 근처) 순으로 고르고,
    /// 정사각 화면비가 되면 정사각으로, 얼굴 따라 확대하는 Center Stage는 끈다.
    /// iPhone 18 Pro Max 전면: 초광각(Front Ultra Wide) 1280x1280, 1:1, 화각 84° (일반 전면 카메라는 최대 73°)
    private func widen(_ device: AVCaptureDevice) {
        let fps = SignSpec.targetFPS
        let eightBit: Set<FourCharCode> = [kCVPixelFormatType_420YpCbCr8BiPlanarFullRange, kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange]
        func rank(_ f: AVCaptureDevice.Format) -> (Int, Float, Int) {
            (eightBit.contains(CMFormatDescriptionGetMediaSubType(f.formatDescription)) ? 1 : 0,
             (Self.portraitFieldOfView(f) * 2).rounded(), Self.resolutionScore(f))
        }
        let best = device.formats
            .filter { f in f.videoSupportedFrameRateRanges.contains { $0.minFrameRate <= fps && fps <= $0.maxFrameRate } }
            .max { rank($0) < rank($1) }

        if AVCaptureDevice.centerStageControlMode != .app { AVCaptureDevice.centerStageControlMode = .app }
        AVCaptureDevice.isCenterStageEnabled = false
        do {
            try device.lockForConfiguration()
            defer { device.unlockForConfiguration() }
            if let best { device.activeFormat = best }
            if device.activeFormat.videoSupportedFrameRateRanges.contains(where: { $0.minFrameRate <= fps && fps <= $0.maxFrameRate }) {
                device.activeVideoMinFrameDuration = CMTime(value: 1, timescale: CMTimeScale(fps))
                device.activeVideoMaxFrameDuration = CMTime(value: 1, timescale: CMTimeScale(fps))
            }
            device.videoZoomFactor = zooms.indices.contains(zoomIndex) ? zooms[zoomIndex].factor : device.minAvailableVideoZoomFactor
            if Self.supportsSquare(device.activeFormat), #available(iOS 26.0, *) {
                device.setDynamicAspectRatio(.ratio1x1, completionHandler: nil)
            }
            let d = CMVideoFormatDescriptionGetDimensions(device.activeFormat.formatDescription)
            print("[카메라] \(device.localizedName): \(d.width)x\(d.height), 세로 기준 가로 화각 "
                  + String(format: "%.1f°", Self.portraitFieldOfView(device.activeFormat))
                  + ", 정사각 \(Self.supportsSquare(device.activeFormat)), 줌 \(device.videoZoomFactor) \(zooms.map(\.label))")
        } catch {
            print("[카메라] 설정 실패:", error)
        }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let time = CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds
        // 약 15fps: 카메라가 30fps로 오면 한 장씩 걸러 쓴다
        guard time - lastTime >= 1 / SignSpec.targetFPS - 0.01,
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastTime = time
        onFrame?(pixelBuffer, time, portraitTurns.withLock { $0 })
    }
}
