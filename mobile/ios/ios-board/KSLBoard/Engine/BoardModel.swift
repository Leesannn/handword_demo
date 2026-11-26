import CoreGraphics
import Foundation
import Observation

/// 프레임 → 구간 자르기 → 전처리 → Core ML → 화면에 적을 낱말.
/// 카메라·MediaPipe·판정은 KSLSign의 Core/Capture 코드를 그대로 쓰고, 여기서는 화면에 필요한 상태만 만든다
@Observable
@MainActor
final class BoardModel {
    enum Setup: Equatable {
        case starting, ready, cameraDenied
        case failed(String)
    }

    /// 카메라가 필요한 화면
    enum Need: Hashable { case translate, practice }

    /// 번역 화면에서 가장 최근에 읽은 것
    enum Latest: Equatable {
        case token(UUID)
        case unread(Reading.Outcome, seconds: Double)
    }

    // 카메라에서 온 것
    private(set) var setup = Setup.starting
    private(set) var pose: Pose2D?
    private(set) var guide = GuideStatus.noPerson
    /// 사람이 1초 넘게 안 보인다
    private(set) var nobody = false
    private(set) var rightVisible = false
    private(set) var leftVisible = false
    private(set) var aspect: CGFloat = 9.0 / 16.0
    private(set) var isFront = true
    private(set) var zoomLabels: [String] = []
    private(set) var zoomIndex = 0

    // 읽기
    private(set) var isReading = false
    private(set) var elapsed = 0.0
    private(set) var trail = Trail()

    // 번역
    private(set) var tokens: [Token] = []   // 오래된 것부터
    private(set) var latest: Latest?
    private(set) var tooShort = false

    /// 모델이 읽을 수 있는 낱말 ('기타' 제외, 모델의 라벨 순서)
    private(set) var words: [String] = []

    /// 따라 하기 화면이 떠 있는 동안에는 결과를 번역 기록에 적지 않고 그쪽으로 보낸다
    @ObservationIgnored var onReading: ((Reading) -> Void)?

    let source: FrameSource
    @ObservationIgnored private var classifier: SignClassifier?
    @ObservationIgnored private let segmenter = Segmenter(mode: .button)
    @ObservationIgnored private var needs: Set<Need> = []
    @ObservationIgnored private var sceneActive = true
    @ObservationIgnored private var settingUp = false
    @ObservationIgnored private var lostFrames = 0
    @ObservationIgnored private var rightGone = 0
    @ObservationIgnored private var leftGone = 0
    @ObservationIgnored private var backBeforePractice = false
    @ObservationIgnored private var frameSize = (width: 720, height: 1280)
    /// 3초가 되어 읽기가 저절로 끝난 때
    @ObservationIgnored private var autoEndedAt = Date.distantPast

    init(source: FrameSource) {
        self.source = source
        do {
            let loaded = try SignClassifier()
            classifier = loaded
            words = loaded.classes.filter { $0 != Reading.other }
            SyncCenter.shared.modelVersion = loaded.run
            SyncCenter.shared.preprocessVersion = loaded.preprocessVersion
            SyncCenter.shared.classes = loaded.classes
        } catch {
            setup = .failed(error.localizedDescription)
        }
        source.onFrame = { [weak self] result, time, width, height in
            self?.receive(result, time: time, width: width, height: height)
        }
    }

    // MARK: 카메라 켜고 끄기

    func need(_ need: Need) {
        needs.insert(need)
        if need == .practice { useFrontForPractice() }
        sync()
    }

    func release(_ need: Need) {
        needs.remove(need)
        if need == .practice, backBeforePractice {
            backBeforePractice = false
            try? source.useFront(false)
            syncCamera()
        }
        sync()
    }

    func setSceneActive(_ active: Bool) {
        sceneActive = active
        sync()
    }

    private var wanted: Bool { sceneActive && !needs.isEmpty }

    private func sync() {
        if wanted {
            Task { await activate() }
        } else {
            source.stop()
            cancelRead()
        }
    }

    private func activate() async {
        guard classifier != nil else { return }
        if setup == .ready {
            source.start()
            return
        }
        guard !settingUp else { return }
        settingUp = true
        defer { settingUp = false }
        do {
            try await source.prepare()
            setup = .ready
            if needs.contains(.practice) { useFrontForPractice() }
            syncCamera()
            if wanted { source.start() }
        } catch SourceError.cameraDenied {
            setup = .cameraDenied
        } catch {
            setup = .failed(error.localizedDescription)
        }
    }

    /// 따라 하기는 자기 모습을 보며 하므로 전면 카메라를 쓴다. 끝나면 쓰던 카메라로 돌린다
    private func useFrontForPractice() {
        guard setup == .ready, !source.isFront else { return }
        if (try? source.useFront(true)) != nil {
            backBeforePractice = true
            pose = nil
            syncCamera()
        }
    }

    /// 전면 ↔ 후면. 읽던 구간은 버린다
    func switchCamera() {
        guard setup == .ready else { return }
        cancelRead()
        if (try? source.useFront(!source.isFront)) != nil {
            UserDefaults.standard.set(source.isFront ? "front" : "back", forKey: "camera")
            pose = nil
        }
        syncCamera()
    }

    func setZoom(_ index: Int) {
        source.setZoom(index)
        syncCamera()
    }

    private func syncCamera() {
        isFront = source.isFront
        zoomLabels = source.zoomLabels
        zoomIndex = source.zoomIndex
    }

    // MARK: 읽기

    /// 번역의 읽기 단추: 누르면 시작하고 다시 누르면 끝난다. 3초가 되면 저절로 끝난다
    func toggleRead() {
        guard setup == .ready else { return }
        if segmenter.isRecording {
            handle(segmenter.stop(at: source.now))
        } else {
            // 3초에서 저절로 끝나는 바로 그 순간에 끝내려고 누르면, 그 누름이 새 읽기를 시작해 버린다.
            // 저절로 끝난 직후의 누름은 넘긴다
            guard Date().timeIntervalSince(autoEndedAt) > 0.6 else { return }
            source.readingWillStart()
            segmenter.start(at: source.now)
            if segmenter.isRecording { began() }
        }
        isReading = segmenter.isRecording
    }

    /// 따라 하기: 손이 보이면 저절로 시작하고, 손을 내리면(또는 3초가 되면) 끝난다
    func armAuto() {
        segmenter.mode = .auto
        isReading = false
        elapsed = 0
        trail = Trail()
    }

    /// 단추로 읽는 방식으로 되돌린다
    func disarm() {
        segmenter.mode = .button
        isReading = false
    }

    private func cancelRead() {
        segmenter.reset()
        isReading = false
        elapsed = 0
    }

    private func began() {
        isReading = true
        elapsed = 0
        trail = Trail()
        tooShort = false
    }

    private func receive(_ result: FrameResult, time: Double, width: Int, height: Int) {
        frameSize = (width, height)
        aspect = CGFloat(width) / CGFloat(height)
        let seen = result.person == nil ? nil : Pose2D(values: result.values)
        pose = seen
        guide = PositionGuide.status(for: result, width: width, height: height)
        // 한두 프레임 놓친 것으로 화면이 깜빡이지 않게 조금 기다렸다가 '안 보임'으로 바꾼다
        lostFrames = seen == nil ? lostFrames + 1 : 0
        nobody = lostFrames >= 15
        rightGone = seen?.right == nil ? rightGone + 1 : 0
        leftGone = seen?.left == nil ? leftGone + 1 : 0
        rightVisible = rightGone < 6
        leftVisible = leftGone < 6

        let event = segmenter.add(time: time, values: result.values, hasHand: !result.hands.isEmpty)
        if case .clip = event, segmenter.mode == .button { autoEndedAt = Date() }
        handle(event)
        isReading = segmenter.isRecording
        if isReading {
            elapsed = min(SignSpec.maxDuration, max(0, time - segmenter.startTime))
            if let seen { trail.add(seen) }
        }
    }

    private func handle(_ event: Segmenter.Event?) {
        switch event {
        case .started:
            began()
        case .tooShort:
            // 자동에서는 손이 잠깐 잡힌 것이라 조용히 버린다
            if segmenter.mode == .button {
                tooShort = true
                SyncCenter.shared.log(.recognitionResult) {
                    $0.source = "translate"
                    $0.outcome = "too_short"
                }
            }
        case .clip(let clip):
            finish(clip)
        case nil:
            break
        }
    }

    private func finish(_ clip: Clip) {
        guard let classifier else { return }
        do {
            let aspect = Double(frameSize.width) / Double(frameSize.height)
            let straight = try classifier.predict(frames: clip.frames, times: clip.times, aspect: aspect,
                                                  start: clip.start, end: clip.end)
            // 좌우를 뒤집은 것도 판정해서, 낱말을 더 확실하게 읽은 쪽을 쓴다 (왼손으로 한 동작도 받아 준다)
            let flipped = try classifier.predict(frames: HandMirror.frames(clip.frames), times: clip.times, aspect: aspect,
                                                 start: clip.start, end: clip.end)
            let other = classifier.classes.firstIndex(of: Reading.other)
            func best(_ p: [Float]) -> Float { p.enumerated().filter { $0.offset != other }.map(\.element).max() ?? 0 }
            let mirrored = best(flipped) > best(straight)
            let reading = Reading(clip: clip, classes: classifier.classes, probabilities: mirrored ? flipped : straight, mirrored: mirrored)
            SyncCenter.shared.remember(reading, clip: clip, aspect: Double(frameSize.width) / Double(frameSize.height),
                                       mode: segmenter.mode == .auto ? "auto" : "button", camera: isFront ? "front" : "back")
            if let onReading {
                onReading(reading)
            } else {
                record(reading)
            }
        } catch {
            print("판정 오류:", error)
        }
    }

    // MARK: 번역 기록

    private func record(_ reading: Reading) {
        SyncCenter.shared.log(.recognitionResult) {
            $0.source = "translate"
            SyncCenter.shared.fill(&$0, from: reading)
            switch reading.outcome {
            case .word(_, let sure): $0.outcome = sure ? "read" : "unsure"
            case .unknown: $0.outcome = "unknown"
            case .handsUnseen: $0.outcome = "hands_unseen"
            }
        }
        switch reading.outcome {
        case .word(let word, let sure):
            tokens.append(Token(id: reading.id, word: word, sure: sure, reading: reading))
            if tokens.count > 30 { tokens.removeFirst() }
            latest = .token(reading.id)
        case let outcome:
            latest = .unread(outcome, seconds: reading.seconds)
        }
    }

    func token(_ id: UUID) -> Token? {
        tokens.first { $0.id == id }
    }

    /// 맞는 낱말로 고친다. 앱이 읽은 낱말을 그대로 고르면 '맞다'고 확인한 것이다
    func setWord(_ word: String, for id: UUID) {
        guard let i = tokens.firstIndex(where: { $0.id == id }) else { return }
        tokens[i].word = word
        tokens[i].sure = true
        tokens[i].corrected = word != tokens[i].reading.top.word
        // 정답 선택: 사용자가 맞다고 확인했거나 다른 낱말로 고쳤다
        let reading = tokens[i].reading, corrected = tokens[i].corrected
        let sample = SyncCenter.shared.saveSample(for: reading.id, label: word, feedback: corrected ? "corrected" : "confirmed",
                                                  source: "kslboard-translate", outcome: corrected ? "wrong_word" : "correct")
        SyncCenter.shared.log(.answerSelected) {
            $0.source = "translate"
            // 규격서의 항목만 넣는다 (읽기 번호, 모델의 낱말과 확률). 길이·손 빠짐 같은 값은 그 읽기의 인식 결과 기록에 이미 있다
            $0.readingId = reading.id.uuidString.lowercased()
            $0.predictedWord = reading.top.word
            $0.confidence = Double(reading.top.probability)
            $0.probabilities = Dictionary(uniqueKeysWithValues: reading.ranking.map { ($0.word, Double($0.probability)) })
            $0.selectedWord = word
            $0.wasCorrected = corrected
            $0.sampleId = sample
        }
    }

    func remove(_ id: UUID) {
        tokens.removeAll { $0.id == id }
        if latest == .token(id) { latest = nil }
    }

    func clear() {
        tokens = []
        latest = nil
        tooShort = false
    }
}

#if DEBUG
extension BoardModel {
    /// 화면을 뽑아 보거나 미리보기를 만들 때 결과 하나를 번역 기록에 넣는다. 앱이 도는 동안에는 쓰지 않는다
    func debugRecord(_ reading: Reading) {
        record(reading)
    }
}
#endif
