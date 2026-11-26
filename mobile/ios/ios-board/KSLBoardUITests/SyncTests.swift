import XCTest

/// 앱이 만든 기록이 서버까지 가는지 본다. 흉내 서버(tools/mock_server.py)를 먼저 켜 두고 돌린다.
/// 시뮬레이터에서는 카메라 대신 '감사' 본보기 좌표가 흐르므로, 감사를 따라 하면 알아본다
final class SyncTests: XCTestCase {
    func testRecordsReachServer() {
        let url = ProcessInfo.processInfo.environment["SERVER_URL"] ?? "http://127.0.0.1:8787"
        run(["-serverURL", url, "-serverKey", "test-key", "-sync.agreed", "YES"])
    }

    /// Server.plist에 적힌 실제 서버로 보낸다 (주소와 키를 덮어쓰지 않는다). 좌표는 SamplesPath가 있을 때만 간다.
    func testRealServer() {
        run(["-sync.agreed", "YES"], showStatus: true)
    }

    private func run(_ arguments: [String], showStatus: Bool = false) {
        let app = XCUIApplication()
        app.launchArguments += arguments
        app.launch()
        func wait(_ seconds: Double) { Thread.sleep(forTimeInterval: seconds) }

        // 번역: 한 번 읽고, 읽은 낱말을 자세히 열어 다른 낱말로 고친다 (인식 결과 + 정답 선택)
        XCTAssertTrue(app.buttons["읽기 시작"].waitForExistence(timeout: 8))
        wait(1.5)
        app.buttons["읽기 시작"].tap()
        wait(1.3)
        app.buttons["읽기 끝내기"].tap()
        wait(1.2)
        let read = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "감사")).firstMatch
        if read.waitForExistence(timeout: 3) {
            read.tap()
            wait(1)
            let other = app.buttons["자다"]
            if other.waitForExistence(timeout: 2) { other.tap() }
            wait(0.5)
            if app.buttons["완료"].exists { app.buttons["완료"].tap() }
            wait(1)
        }

        // 학습: 감사를 두 번 따라 한다 (학습 시작, 연습 시도, 인식 결과 ×2, 닫기)
        app.tabBars.buttons["학습"].tap()
        wait(1.2)
        let row = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "감사")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 3))
        row.tap()
        wait(1.5)
        app.buttons["따라 하기"].tap()
        wait(1.5)
        app.buttons["시작"].tap()
        let finish = app.buttons["마치기"]
        XCTAssertTrue(finish.waitForExistence(timeout: 14))
        wait(1)
        for title in ["한 번 더", "다시 하기"] where app.buttons[title].exists {
            app.buttons[title].tap()
            break
        }
        wait(4)
        XCTAssertTrue(finish.waitForExistence(timeout: 14))
        wait(1)
        finish.tap()
        // 보내기를 기다린다 (조금 모았다가 보낸다)
        wait(6)
        // 보내기 화면은 없다. 결과는 서버(또는 흉내 서버의 /stats)와 앱 저장소에서 확인한다
        _ = showStatus
    }
}
