import XCTest

/// Drives the synthetic simulator app (`com.cosmasos.synthetic`) with
/// `-COSMAS_UI_TEST_FIXTURES`. Invented engagements only; no PHI.
final class VisitTimerAndChiefIconUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication(bundleIdentifier: "com.cosmasos.synthetic")
        app.launchArguments = ["-COSMAS_UI_TEST_FIXTURES"]
        app.launch()
        XCTAssertTrue(
            app.otherElements["cosmas.uiTest.surface"].waitForExistence(timeout: 10),
            "Synthetic UI fixtures surface should appear for the synthetic bundle"
        )
    }

    override func tearDownWithError() throws {
        app?.terminate()
        app = nil
    }


    private func elapsedText(_ element: XCUIElement) -> String {
        if let value = element.value as? String, value.contains(":") { return value }
        let label = element.label
        if label.contains(":") { return label }
        return label
    }

    func testVisitTimerAdvancesThenStops() throws {
        let elapsed = app.staticTexts["cosmas.visit.timer.elapsed"]
        let start = app.buttons["cosmas.visit.timer.start"]
        let stop = app.buttons["cosmas.visit.timer.stop"]
        XCTAssertTrue(elapsed.exists)
        XCTAssertTrue(start.exists)
        XCTAssertEqual(elapsedText(elapsed), "0:00")

        start.tap()
        XCTAssertFalse(start.isEnabled)
        XCTAssertTrue(stop.isEnabled)

        // Elapsed time must advance while the visit timer is running.
        var advanced = false
        let deadline = Date().addingTimeInterval(3)
        while Date() < deadline {
            let value = elapsedText(elapsed)
            if value != "0:00" {
                advanced = true
                break
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        XCTAssertTrue(advanced, "Visit timer elapsed label should advance after start; last=\(elapsedText(elapsed))")
        let runningValue = elapsedText(elapsed)

        stop.tap()
        XCTAssertTrue(start.isEnabled)
        XCTAssertFalse(stop.isEnabled)
        let stoppedValue = elapsedText(elapsed)
        XCTAssertEqual(stoppedValue, runningValue, "Elapsed time should freeze when the visit timer stops")

        RunLoop.current.run(until: Date().addingTimeInterval(0.6))
        XCTAssertEqual(elapsedText(elapsed), stoppedValue, "Elapsed time must remain stopped after stop")
    }

    func testExactlyOneChiefIconPerRow() throws {
        let rows = app.otherElements.matching(identifier: "cosmas.messages.chief.row")
        XCTAssertGreaterThanOrEqual(rows.count, 2, "Chief group should list invented patient-chat engagements")

        for index in 0..<rows.count {
            let row = rows.element(boundBy: index)
            XCTAssertTrue(row.exists)
            let icons = row.images.matching(identifier: "cosmas.messages.chief.icon")
            // Prefer images; fall back to any element with the icon identifier.
            let iconCount = icons.count > 0
                ? icons.count
                : row.descendants(matching: .any).matching(identifier: "cosmas.messages.chief.icon").count
            XCTAssertEqual(
                iconCount, 1,
                "Row \(index) must show exactly one Chief icon (found \(iconCount))"
            )
        }
    }
}
