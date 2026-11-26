import AVFoundation
import CoreGraphics
import Observation
import VideoToolbox

struct Prediction: Identifiable {
    let word: String
    let probability: Float
    var id: String { word }
}

/// 번역 한 번의 결과. 사용자가 '맞아요'를 누르거나 맞는 단어를 넣으면 label이 생기고 샘플로 저장된다
struct Translation: Identifiable {
    let id = UUID()
    let created = Date()
    let clip: Clip
    let aspect: Double
    let mode: Segmenter.Mode
    let camera: String          // "front" / "back 1×" 등
    let probabilities: [Float]
    let ranking: [Prediction]   // 확률 높은 순
    let handMissing: Double     // 동작 손이 안 잡힌 프레임 비율
    var label: String?

    var top: Prediction { ranking[0] }
    var corrected: Bool { label != nil && label != top.word }
}

/// 카메라 → MediaPipe → 177개 값 → 구간 자르기 → 전처리 → Core ML → 번역 목록.
/// 번역은 틀릴 수 있어서, 사용자가 확인했거나 맞는 단어를 넣은 것만 학습 형식 샘플로 폰에 저장한다
@Observable
@MainActor
final class TranslatorModel {
    private(set) var preview: CGImage?             // MediaPipe가 본 화면 (세로·좌우 반전)
    private(set) var frame: FrameResult?
    private(set) var guide: GuideStatus = .noPerson
    private(set) var imageWidth = 720
    private(set) var imageHeight = 1280
    private(set) var isRecording = false
    private(set) var elapsed = 0.0
    private(set) var translations: [Translation] = []   // 최신이 앞
    var selectedID: UUID?
    private(set) var message: String?
    private(set) var setupError: String?
    private(set) var savedCount = SampleStore.count()
    private(set) var cameraPosition: AVCaptureDevice.Position =
        UserDefaults.standard.string(forKey: "camera") == "back" ? .back : .front
    private(set) var zoomLabels: [String] = []      // 후면 0.5× / 1×
    private(set) var zoomIndex = 0

    var mode: Segmenter.Mode {
        get { currentMode }
        set {
            currentMode = newValue
            segmenter.mode = newValue
            isRecording = false
            message = nil
        }
    }

    /// 수어하는 사람 이름. 샘플에 함께 저장한다
    var person: String {
        get { personName }
        set {
            personName = newValue
            UserDefaults.standard.set(newValue, forKey: "person")
        }
    }

    var aspect: Double { Double(imageWidth) / Double(imageHeight) }
    var classes: [String] { classifier?.classes ?? [] }
    var selected: Translation? { translations.first { $0.id == selectedID } ?? translations.first }

    let camera = CameraController()
    private var currentMode = Segmenter.Mode.auto
    private var personName = UserDefaults.standard.string(forKey: "person") ?? ""
    private var classifier: SignClassifier?
    private let segmenter = Segmenter(mode: .auto)
    private var settingUp = false

    func setUp() async {
        if classifier != nil {
            camera.start()
            return
        }
        guard !settingUp else { return }
        settingUp = true
        defer { settingUp = false }
        guard await AVCaptureDevice.requestAccess(for: .video) else {
            setupError = "카메라 권한이 필요합니다. 설정 > 수어 인식에서 카메라를 켜 주세요."
            return
        }
        do {
            classifier = try SignClassifier()
            let detector = try LandmarkDetector()
            let orienter = FrameOrienter()
            camera.onFrame = { [weak self] raw, time, turns in
                guard let pixelBuffer = orienter.selfie(from: raw, turns: turns) else { return }
                let width = CVPixelBufferGetWidth(pixelBuffer), height = CVPixelBufferGetHeight(pixelBuffer)
                let detected: (hands: [HandDetection], poses: [PoseDetection])?
                do {
                    detected = try detector.detect(pixelBuffer, timestampMs: Int((time * 1000).rounded()))
                } catch {
                    print("MediaPipe 오류:", error)
                    return
                }
                guard let detected else { return }
                let result = FrameBuilder.build(hands: detected.hands, poses: detected.poses, width: width, height: height)
                var cgImage: CGImage?
                VTCreateCGImageFromCVPixelBuffer(pixelBuffer, options: nil, imageOut: &cgImage)
                let image = cgImage
                Task { @MainActor in self?.receive(result, image: image, time: time, width: width, height: height) }
            }
            try camera.configure(position: cameraPosition)
            syncCamera()
            camera.start()
        } catch {
            setupError = error.localizedDescription
        }
    }

    func pause() { camera.stop() }

    /// 전면 ↔ 후면. 진행 중이던 구간은 버린다
    func switchCamera() {
        let next: AVCaptureDevice.Position = cameraPosition == .front ? .back : .front
        do {
            try camera.configure(position: next)
            UserDefaults.standard.set(next == .back ? "back" : "front", forKey: "camera")
            segmenter.reset()
            isRecording = false
            frame = nil
            message = nil
        } catch {
            message = "카메라를 바꾸지 못했습니다: \(error.localizedDescription)"
        }
        syncCamera()
    }

    func setZoom(_ index: Int) {
        camera.setZoom(index)
        syncCamera()
    }

    private func syncCamera() {
        cameraPosition = camera.position
        zoomLabels = camera.zooms.map(\.label)
        zoomIndex = camera.zoomIndex
    }

    private var cameraDescription: String {
        let name = cameraPosition == .back ? "back" : "front"
        return zoomLabels.indices.contains(zoomIndex) ? "\(name) \(zoomLabels[zoomIndex])" : name
    }

    /// 버튼 방식의 '시작'/'끝'
    func toggleRecording() {
        if segmenter.isRecording {
            handle(segmenter.stop(at: camera.now))
        } else {
            segmenter.start(at: camera.now)
            elapsed = 0
            message = nil
        }
        isRecording = segmenter.isRecording
    }

    /// '맞아요': 앱 판정을 정답으로 저장한다
    func confirm(_ id: UUID) {
        guard let t = translations.first(where: { $0.id == id }) else { return }
        save(id, label: t.top.word)
    }

    /// 맞는 단어를 넣는다. 앱 판정과 같은 단어면 '맞아요'와 같다
    func correct(_ id: UUID, to word: String) {
        save(id, label: word)
    }

    private func receive(_ result: FrameResult, image: CGImage?, time: Double, width: Int, height: Int) {
        preview = image
        frame = result
        imageWidth = width
        imageHeight = height
        guide = PositionGuide.status(for: result, width: width, height: height)
        handle(segmenter.add(time: time, values: result.values, hasHand: !result.hands.isEmpty))
        isRecording = segmenter.isRecording
        if isRecording { elapsed = time - segmenter.startTime }
    }

    private func handle(_ event: Segmenter.Event?) {
        switch event {
        case .started:
            message = nil
        case .clip(let clip):
            translate(clip)
        case .tooShort(let seconds):
            // 자동에서는 손이 잠깐 잡힌 것이라 조용히 버린다
            if mode == .button { message = String(format: "버림: %.1f초로 너무 짧습니다 (0.5초 이상)", seconds) }
        case nil:
            break
        }
    }

    private func translate(_ clip: Clip) {
        guard let classifier else { return }
        do {
            let p = try classifier.predict(frames: clip.frames, times: clip.times, aspect: aspect, start: clip.start, end: clip.end)
            let ranking = zip(classifier.classes, p).map { Prediction(word: $0, probability: $1) }
                .sorted { $0.probability > $1.probability }
            let translation = Translation(clip: clip, aspect: aspect, mode: mode, camera: cameraDescription,
                                          probabilities: p, ranking: ranking,
                                          handMissing: Preprocess.mainHandMissingRatio(clip.window))
            translations.insert(translation, at: 0)
            // 확인하지 않은 오래된 번역은 버린다
            if translations.count > 50 { translations.removeLast() }
            selectedID = translation.id
            message = nil
        } catch {
            message = error.localizedDescription
        }
    }

    private func save(_ id: UUID, label: String) {
        guard let i = translations.firstIndex(where: { $0.id == id }), let classifier else { return }
        let t = translations[i]
        let sample = Sample(
            id: t.id.uuidString, created: ISO8601DateFormatter().string(from: t.created), person: person,
            label: label, feedback: label == t.top.word ? "confirmed" : "corrected", predicted: t.top.word,
            classes: classifier.classes, probabilities: t.probabilities, model: classifier.run,
            preprocessVersion: classifier.preprocessVersion, mode: t.mode.rawValue, camera: t.camera, aspect: t.aspect,
            start: t.clip.start, end: t.clip.end, times: t.clip.times,
            frames: t.clip.frames.map { $0.map { $0.isNaN ? nil : $0 } },
            device: Sample.deviceModel, appVersion: Sample.appVersion)
        do {
            try SampleStore.save(sample)
            translations[i].label = label
            savedCount = SampleStore.count()
        } catch {
            message = "저장하지 못했습니다: \(error.localizedDescription)"
        }
    }
}
