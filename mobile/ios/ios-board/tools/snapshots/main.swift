import AppKit
import SwiftUI

// Mac에서 앱 화면을 그림으로 뽑는다 (tools/snapshots.sh가 컴파일해서 돌린다).
// 아이폰의 상태 막대·탭 막대·홈 막대는 자리만 흉내 낸 것이고, 목록과 시트 같은 시스템 부품은 Mac 모양으로 그려진다.
// 그래서 이 그림은 배치와 색, 사람 도식, 글을 확인하는 용도이고 기기 화면을 대신하지 않는다.

let out = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "snapshots")
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
_ = NSApplication.shared

@MainActor func spin(_ seconds: Double = 0.05) {
    RunLoop.current.run(until: Date().addingTimeInterval(seconds))
}

/// 아이폰의 안전 영역과 시스템 막대를 흉내 낸 틀 (390×844, 위 59, 아래 34 또는 탭 막대까지 83)
struct Phone<Content: View>: View {
    var tab: Int?
    @ViewBuilder var content: Content

    var body: some View {
        content
            .safeAreaPadding(EdgeInsets(top: 59, leading: 0, bottom: tab == nil ? 34 : 83, trailing: 0))
            .overlay(alignment: .top) {
                Capsule().fill(.black).frame(width: 124, height: 36).padding(.top, 11)
            }
            .overlay(alignment: .bottom) {
                VStack(spacing: 8) {
                    if let tab {
                        HStack(spacing: 2) {
                            item("번역", selected: tab == 0) {
                                BracketPair().stroke(style: StrokeStyle(lineWidth: 2, lineCap: .square)).frame(width: 20, height: 18)
                            }
                            item("학습", selected: tab == 1) { Image(systemName: "book").font(.system(size: 19)) }
                        }
                        .padding(4)
                        .background(.regularMaterial, in: Capsule())
                        .overlay(Capsule().strokeBorder(Theme.sep, lineWidth: 0.5))
                    }
                    Capsule().fill(Theme.ink).frame(width: 134, height: 5)
                }
                .padding(.bottom, 8)
            }
    }

    private func item<Icon: View>(_ title: String, selected: Bool, @ViewBuilder icon: () -> Icon) -> some View {
        VStack(spacing: 2) {
            icon().frame(height: 24)
            Text(title).font(.system(size: 10, weight: .semibold))
        }
        .foregroundStyle(selected ? Theme.tint : Theme.ink2)
        .frame(width: 96, height: 50)
        .background(selected ? Theme.tint.opacity(0.12) : .clear, in: Capsule())
    }
}

@MainActor var shots: [(name: String, image: NSImage)] = []

@MainActor func shoot<V: View>(_ name: String, dark: Bool = false, size: CGSize = CGSize(width: 390, height: 844), @ViewBuilder _ view: () -> V) {
    let root = view()
        .environment(\.still, true)
        .frame(width: size.width, height: size.height)
        .background(Theme.bg)
    let host = NSHostingView(rootView: root)
    host.frame = CGRect(origin: .zero, size: size)
    let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
    window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
    window.contentView = host
    host.layoutSubtreeIfNeeded()
    spin(0.7)
    let scale = 2
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width) * scale, pixelsHigh: Int(size.height) * scale,
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = size
    host.cacheDisplay(in: host.bounds, to: rep)
    try! rep.representation(using: .png, properties: [:])!.write(to: out.appendingPathComponent(name + ".png"))
    let image = NSImage(size: size)
    image.addRepresentation(rep)
    shots.append((name, image))
    window.contentView = nil
    print("그림:", name)
}

/// 뽑은 그림을 한 장에 모은다
@MainActor func contactSheet(_ name: String, columns: Int = 6, cell: CGSize = CGSize(width: 234, height: 506)) {
    let rows = (shots.count + columns - 1) / columns
    let gap: CGFloat = 20, label: CGFloat = 26
    let size = CGSize(width: CGFloat(columns) * (cell.width + gap) + gap, height: CGFloat(rows) * (cell.height + label + gap) + gap)
    let sheet = NSImage(size: size)
    sheet.lockFocus()
    NSColor(calibratedWhite: 0.9, alpha: 1).setFill()
    NSRect(origin: .zero, size: size).fill()
    for (i, shot) in shots.enumerated() {
        let x = gap + CGFloat(i % columns) * (cell.width + gap)
        let y = size.height - gap - CGFloat(i / columns + 1) * (cell.height + label + gap) + gap
        let height = cell.width * shot.image.size.height / shot.image.size.width
        shot.image.draw(in: NSRect(x: x, y: y + label + (cell.height - min(height, cell.height)), width: cell.width, height: min(height, cell.height)))
        (shot.name as NSString).draw(at: NSPoint(x: x, y: y + 4), withAttributes: [.font: NSFont.systemFont(ofSize: 13), .foregroundColor: NSColor.black])
    }
    sheet.unlockFocus()
    if let tiff = sheet.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff) {
        try? rep.representation(using: .png, properties: [:])?.write(to: out.appendingPathComponent(name + ".png"))
    }
    shots = []
}

/// 카메라 권한이 거부된 경우를 흉내 낸다
final class DeniedSource: FrameSource {
    var onFrame: ((FrameResult, Double, Int, Int) -> Void)?
    let now = 0.0, isFront = true, zoomLabels: [String] = [], zoomIndex = 0
    func prepare() async throws { throw SourceError.cameraDenied }
    func start() {}
    func stop() {}
    func useFront(_ front: Bool) throws {}
    func setZoom(_ index: Int) {}
}

@MainActor func ready(_ source: FrameSource) -> BoardModel {
    let model = BoardModel(source: source)
    // 그림을 뽑을 때마다 화면이 사라지며 카메라 요청이 풀리므로, 읽던 구간이 버려지지 않게 요청을 하나 더 잡아 둔다
    model.need(.translate)
    model.need(.practice)
    var waited = 0.0
    while model.setup == .starting, waited < 5 {
        spin()
        waited += 0.05
    }
    return model
}

@MainActor func steps(_ demo: DemoSource, _ count: Int) {
    for _ in 0..<count { demo.step() }
}

@MainActor func run() throws {
    // 지어낸 결과를 만드는 데 쓰는 실제 구간 (본보기 '감사')
    let sample = try ExampleSample.load()
    let sampleFrames = sample.frames.map { $0.map { $0 ?? Float.nan } }
    let clip = Clip(frames: sampleFrames, times: sample.times.map(Double.init), start: Double(sample.start), end: Double(sample.end))
    func made(_ probabilities: [String: Float], clip: Clip = clip) -> Reading {
        Reading(clip: clip, classes: sample.classes, probabilities: sample.classes.map { probabilities[$0] ?? 0.01 })
    }
    var handless = clip
    handless.frames = clip.frames.enumerated().map { i, frame in
        var f = frame
        if i % 5 != 0 { for v in 0..<(SignSpec.poseStart * 3) { f[v] = .nan } }
        return f
    }

    // ── 번역: 실제 흐름 ─────────────────────────────────────────
    let demo = DemoSource(timed: false)
    let model = ready(demo)
    print("준비:", model.setup, "낱말:", model.words)

    steps(demo, 12)
    shoot("번역_01_처음") { Phone(tab: 0) { TranslateView(model: model) } }
    shoot("번역_01_처음_어두운", dark: true) { Phone(tab: 0) { TranslateView(model: model) } }

    steps(demo, 6)
    model.toggleRead()
    steps(demo, 23)
    shoot("번역_02_읽는중") { Phone(tab: 0) { TranslateView(model: model) } }
    steps(demo, 12)
    model.toggleRead()
    if let token = model.tokens.last {
        print("실제 판정:", token.word, token.reading.top.probability, "시간", token.reading.seconds,
              "손 빠짐", token.reading.handMissing, "순위", token.reading.ranking.map { "\($0.word) \($0.probability)" })
    } else {
        print("실제 판정: 낱말 없음", String(describing: model.latest))
    }
    shoot("번역_03_읽음") { Phone(tab: 0) { TranslateView(model: model) } }
    shoot("번역_03_읽음_어두운", dark: true) { Phone(tab: 0) { TranslateView(model: model) } }

    if let token = model.tokens.last {
        shoot("번역_04_자세히", size: CGSize(width: 390, height: 640)) { TokenDetailView(model: model, tokenID: token.id) }
        shoot("번역_04_자세히_어두운", dark: true, size: CGSize(width: 390, height: 640)) { TokenDetailView(model: model, tokenID: token.id) }
    }

    model.debugRecord(made(["감사": 0.52, "자다": 0.31, "커피": 0.09, "기타": 0.05]))
    shoot("번역_05_확실하지않음") { Phone(tab: 0) { TranslateView(model: model) } }
    model.debugRecord(made(["기타": 0.83, "춥다": 0.1]))
    shoot("번역_06_모르는동작") { Phone(tab: 0) { TranslateView(model: model) } }
    model.debugRecord(made(["감사": 0.7], clip: handless))
    shoot("번역_07_손이안보임") { Phone(tab: 0) { TranslateView(model: model) } }

    model.toggleRead()
    steps(demo, 3)
    model.toggleRead()
    shoot("번역_08_너무짧음") { Phone(tab: 0) { TranslateView(model: model) } }

    for i in 0..<20 {
        demo.onFrame?(DemoSource.result([Float](repeating: .nan, count: SignSpec.numValues), width: 1280, height: 720), 100 + Double(i) / 15, 1280, 720)
    }
    shoot("번역_09_사람없음") { Phone(tab: 0) { TranslateView(model: model) } }

    // 실제 기기의 카메라 화면 모양을 흉내 낸다: 본보기의 한 장면을 정사각(전면 초광각)·세로(720×1280) 화면에 옮겨 놓는다
    func framed(_ index: Int, width: Int, height: Int, shoulder: Double, centerY: Double) -> FrameResult {
        let source = sampleFrames[index]
        let from = Double(sample.aspect), to = Double(width) / Double(height)
        let l = (SignSpec.poseStart + SignSpec.leftShoulder) * 3, r = (SignSpec.poseStart + SignSpec.rightShoulder) * 3
        let cx = Double(source[l] + source[r]) / 2, cy = Double(source[l + 1] + source[r + 1]) / 2
        let was = hypot(Double(source[l] - source[r]), Double(source[l + 1] - source[r + 1]) / from)
        var values = source
        for point in 0..<SignSpec.numPoints where !source[point * 3].isNaN {
            values[point * 3] = Float(0.5 + (Double(source[point * 3]) - cx) * shoulder / was)
            values[point * 3 + 1] = Float(centerY + (Double(source[point * 3 + 1]) - cy) * shoulder / was * to / from)
        }
        return DemoSource.result(values, width: width, height: height)
    }
    func feed(_ frame: FrameResult, width: Int, height: Int) {
        for i in 0..<8 { demo.onFrame?(frame, 200 + Double(i) / 15, width, height) }
    }
    feed(framed(40, width: 1280, height: 1280, shoulder: 0.22, centerY: 0.5), width: 1280, height: 1280)
    shoot("번역_11_정사각_카메라") { Phone(tab: 0) { TranslateView(model: model) } }
    feed(framed(40, width: 720, height: 1280, shoulder: 0.24, centerY: 0.36), width: 720, height: 1280)
    shoot("번역_12_세로_카메라") { Phone(tab: 0) { TranslateView(model: model) } }
    feed(framed(40, width: 1280, height: 1280, shoulder: 0.1, centerY: 0.5), width: 1280, height: 1280)
    shoot("번역_13_멀리_있음") { Phone(tab: 0) { TranslateView(model: model) } }
    feed(framed(40, width: 720, height: 1280, shoulder: 0.42, centerY: 0.42), width: 720, height: 1280)
    shoot("번역_14_너무_가까움") { Phone(tab: 0) { TranslateView(model: model) } }

    let denied = ready(DeniedSource())
    shoot("번역_10_카메라꺼짐") { Phone(tab: 0) { TranslateView(model: denied) } }
    contactSheet("모아보기_번역")

    // ── 학습 ───────────────────────────────────────────────────
    let learnDemo = DemoSource(timed: false)
    let learnModel = ready(learnDemo)
    let progress = ProgressStore(marks: ["감사": 2, "우유": 3])
    if let motion = Demo.library["감사"]?.motion {
        // 인형만 크게: 동작의 네 장면과 돌려 본 모습
        for (name, frame, yaw) in [("인형_1", 4, 0.0), ("인형_2", 14, 0.0), ("인형_3", 20, 0.0), ("인형_4", 28, 0.0), ("인형_돌림_왼쪽", 20, -50.0), ("인형_돌림_오른쪽", 20, 50.0), ("인형_08", 8, 0.0), ("인형_10", 10, 0.0), ("인형_12", 12, 0.0), ("인형_16", 16, 0.0), ("인형_18", 18, 0.0), ("인형_22", 22, 0.0), ("인형_24", 24, 0.0), ("인형_26", 26, 0.0)] {
            shoot(name, size: CGSize(width: 390, height: 420)) {
                ZStack {
                    Theme.board
                    AvatarStill(motion: motion, frame: frame, yaw: yaw, size: CGSize(width: 390, height: 420))
                }
            }
        }
        shoot("인형_거울", size: CGSize(width: 390, height: 420)) {
            ZStack {
                Theme.board
                AvatarStill(motion: motion, frame: 20, mirror: true, size: CGSize(width: 390, height: 420))
            }
        }
        shoot("인형_어두운", dark: true, size: CGSize(width: 390, height: 420)) {
            ZStack {
                Theme.board
                AvatarStill(motion: motion, frame: 14, size: CGSize(width: 390, height: 420))
            }
        }
        contactSheet("모아보기_인형", columns: 4, cell: CGSize(width: 390, height: 420))
    }
    // 다른 낱말의 본보기: 동작을 여섯 장면으로
    for word in ["커피", "춥다", "우유", "감사", "자다"] {
        guard let motion = Demo.library[word]?.motion else { print("본보기 없음:", word); continue }
        let count = motion.frames.count
        for step in 0..<6 {
            let frame = min(count - 1, Int(Double(count - 1) * (0.08 + 0.168 * Double(step))))
            shoot("\(word)_\(step + 1)", size: CGSize(width: 390, height: 420)) {
                ZStack {
                    Theme.board
                    AvatarStill(motion: motion, frame: frame, size: CGSize(width: 390, height: 420))
                }
            }
        }
    }
    contactSheet("모아보기_다른낱말", columns: 6, cell: CGSize(width: 390, height: 420))
    // 동작을 영상으로 만들 장면들 (KSL_VIDEO=1): 낱말마다 모든 프레임을 차례로 뽑는다. tools/avatar_video.sh가 이어 붙인다
    if ProcessInfo.processInfo.environment["KSL_VIDEO"] != nil {
        for (n, word) in ["커피", "춥다", "우유", "감사", "자다"].enumerated() {
            guard let motion = Demo.library[word]?.motion else { continue }
            for frame in motion.frames.indices {
                shoot(String(format: "video_%d_%03d", n, frame), size: CGSize(width: 540, height: 600)) {
                    ZStack(alignment: .topLeading) {
                        Theme.board
                        AvatarStill(motion: motion, frame: frame, size: CGSize(width: 540, height: 600))
                        // KSL_VIDEO=plain이면 낱말을 적지 않는다 (다른 앱에 본보기 영상으로 넣을 때)
                        if ProcessInfo.processInfo.environment["KSL_VIDEO"] != "plain" { Gloss(word).colorScheme(.dark).padding(20) }
                    }
                }
            }
        }
        shots = []
    }
    // 손을 크게 보기 (KSL_BIG=낱말)
    if let word = ProcessInfo.processInfo.environment["KSL_BIG"], let motion = Demo.library[word]?.motion {
        let count = motion.frames.count
        for step in 0..<8 {
            let frame = min(count - 1, Int(Double(count - 1) * (0.05 + 0.125 * Double(step))))
            shoot("큰_\(word)_\(step + 1)_f\(frame)", size: CGSize(width: 900, height: 970)) {
                ZStack {
                    Theme.board
                    AvatarStill(motion: motion, frame: frame, size: CGSize(width: 900, height: 970))
                }
            }
        }
        shots = []
    }
    shoot("학습_01_목록") { Phone(tab: 1) { LearnView(model: learnModel, progress: progress) } }
    shoot("학습_02_낱말") { Phone(tab: 1) { LessonView(model: learnModel, progress: progress, word: "감사", startFrame: 14) } }
    shoot("학습_02_낱말_어두운", dark: true) { Phone(tab: 1) { LessonView(model: learnModel, progress: progress, word: "감사", startFrame: 24) } }
    shoot("학습_03_본보기없음") { Phone(tab: 1) { LessonView(model: learnModel, progress: progress, word: "커피") } }

    // ── 따라 하기 ───────────────────────────────────────────────
    steps(learnDemo, 14)
    shoot("따라하기_01_준비") { Phone { PracticeView(model: learnModel, progress: progress, word: "감사") } }
    shoot("따라하기_02_셋세기") { Phone { PracticeView(model: learnModel, progress: progress, word: "감사", initial: .counting(2)) } }
    learnModel.armAuto()
    steps(learnDemo, 24)
    print("따라 하기 자동 시작:", learnModel.isReading, "경과", learnModel.elapsed)
    shoot("따라하기_03_읽는중") { Phone { PracticeView(model: learnModel, progress: progress, word: "감사", initial: .armed) } }
    learnModel.disarm()
    shoot("따라하기_04_알아봄") {
        Phone { PracticeView(model: learnModel, progress: ProgressStore(marks: ["감사": 3]), word: "감사", initial: .success(made(["감사": 0.93]))) }
    }
    shoot("따라하기_05_다르게읽음") {
        Phone { PracticeView(model: learnModel, progress: progress, word: "감사", initial: .failure(.other("자다"), made(["자다": 0.71, "감사": 0.2]))) }
    }
    shoot("따라하기_06_손이안보임") {
        Phone { PracticeView(model: learnModel, progress: progress, word: "감사", initial: .failure(.handsUnseen, made(["감사": 0.7], clip: handless))) }
    }
    shoot("따라하기_07_확실하지않음") {
        Phone { PracticeView(model: learnModel, progress: progress, word: "감사", initial: .failure(.unsure, made(["감사": 0.48, "자다": 0.4]))) }
    }
    contactSheet("모아보기_학습")
    print("끝:", out.path)
}

try MainActor.assumeIsolated { try run() }
