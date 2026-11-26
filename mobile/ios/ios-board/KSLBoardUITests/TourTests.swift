import XCTest

/// 시뮬레이터에서 앱을 한 바퀴 눌러 보며 화면을 찍는다.
/// 시뮬레이터에는 카메라가 없어서 앱이 본보기 좌표('감사')를 카메라 대신 흘려보낸다.
/// 실행할 때 TEST_RUNNER_SNAPSHOT_DIR(그림을 둘 폴더), TEST_RUNNER_CONTENT_SIZE(글자 크기 이름)를 줄 수 있다.
/// 어두운 화면은 실행 전에 `xcrun simctl ui <기기> appearance dark`로 바꾼다
final class TourTests: XCTestCase {
    private var app: XCUIApplication!
    private var shots = 0
    private let environment = ProcessInfo.processInfo.environment

    override func setUp() {
        continueAfterFailure = true
        app = XCUIApplication()
        if let size = environment["CONTENT_SIZE"] {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", size]
        }
        // 처음 켤 때의 안내는 본 것으로 두고, 기록은 쌓지 않는다
        app.launchArguments += ["-noSync"]
        app.launch()
    }

    private func shoot(_ name: String) {
        shots += 1
        let label = String(format: "%02d_%@", shots, name)
        let png = XCUIScreen.main.screenshot().pngRepresentation
        if let folder = environment["SNAPSHOT_DIR"] {
            try? png.write(to: URL(fileURLWithPath: folder).appendingPathComponent(label + ".png"))
        }
        let attachment = XCTAttachment(data: png, uniformTypeIdentifier: "public.png")
        attachment.name = label
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func wait(_ seconds: Double) {
        Thread.sleep(forTimeInterval: seconds)
    }

    func testTour() {
        // ── 번역 ──────────────────────────────────────
        let start = app.buttons["읽기 시작"]
        XCTAssertTrue(start.waitForExistence(timeout: 20), "읽기 단추가 보여야 한다")
        wait(2)
        shoot("번역_처음")

        // 3초가 되면 저절로 끝나므로 그 전에 넉넉히 끝낸다
        start.tap()
        wait(0.9)
        shoot("번역_읽는중")
        wait(0.4)
        app.buttons["읽기 끝내기"].tap()
        wait(1)
        shoot("번역_읽음")
        let word = app.buttons["감사"].firstMatch
        XCTAssertTrue(word.waitForExistence(timeout: 3), "본보기 좌표를 '감사'로 읽어야 한다")

        word.tap()
        wait(1.2)
        shoot("번역_자세히")
        let done = app.buttons["완료"]
        XCTAssertTrue(done.waitForExistence(timeout: 3), "자세히 시트에 완료 단추가 있어야 한다")
        done.tap()
        wait(1)

        // 0.5초가 되기 전에 끝내면 버린다
        app.buttons["읽기 시작"].tap()
        wait(0.15)
        app.buttons["읽기 끝내기"].tap()
        wait(0.8)
        shoot("번역_너무짧음")

        // 다시 누르지 않아도 3초가 되면 저절로 끝난다
        app.buttons["읽기 시작"].tap()
        wait(4)
        XCTAssertTrue(app.buttons["읽기 시작"].exists, "3초가 지나면 읽기가 저절로 끝나야 한다")
        shoot("번역_3초_저절로끝")

        // ── 학습 ──────────────────────────────────────
        app.tabBars.buttons["학습"].tap()
        wait(1.2)
        shoot("학습_목록")

        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "감사")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 3), "목록에 '감사'가 있어야 한다")
        row.tap()
        wait(1.6)
        shoot("낱말_본보기")
        wait(0.9)
        shoot("낱말_본보기_이어서")

        // 인형을 끌어서 돌린다
        let stage = app.coordinate(withNormalizedOffset: CGVector(dx: 0.3, dy: 0.28))
        stage.press(forDuration: 0.1, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.7, dy: 0.28)))
        wait(0.8)
        shoot("낱말_인형_돌림")
        if app.buttons["정면"].exists { app.buttons["정면"].tap() }
        app.buttons["거울로 보기"].tap()
        app.buttons["느리게"].tap()
        wait(1.2)
        shoot("낱말_거울_느리게")
        app.buttons["거울로 보기"].tap()
        app.buttons["느리게"].tap()

        // ── 따라 하기 ──────────────────────────────────
        app.buttons["따라 하기"].tap()
        wait(1.5)
        shoot("따라하기_준비")
        app.buttons["시작"].tap()
        wait(1.3)
        shoot("따라하기_셋세기")
        wait(2.6)
        shoot("따라하기_읽는중")
        let finish = app.buttons["마치기"]
        XCTAssertTrue(finish.waitForExistence(timeout: 12), "따라 하기가 끝나면 마치기 단추가 나와야 한다")
        wait(0.8)
        shoot("따라하기_결과")
        finish.tap()
        wait(1.2)
        shoot("낱말_돌아옴")

        // 본보기가 없는 낱말
        app.navigationBars.buttons.firstMatch.tap()
        wait(1)
        let other = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "커피")).firstMatch
        if other.waitForExistence(timeout: 2) {
            other.tap()
            wait(1.2)
            shoot("낱말_본보기없음")
            app.navigationBars.buttons.firstMatch.tap()
            wait(0.8)
        }
        shoot("학습_목록_돌아옴")
        app.tabBars.buttons["번역"].tap()
        wait(1.5)
        shoot("번역_돌아옴")
    }
}
