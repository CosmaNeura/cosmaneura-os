from lab.capture_checks import swift_counts


def test_counts_both_swift_frameworks_without_counting_nested_suites_twice():
    output = """Executed 19 tests, with 0 failures
    Executed 6 tests, with 0 failures
    Executed 25 tests, with 0 failures
    Executed 25 tests, with 0 failures
    Test run with 7 tests in 2 suites passed after 228.646 seconds."""
    assert swift_counts(output) == (32, 0)


def test_failed_or_empty_swift_output_cannot_look_like_a_passing_suite():
    assert swift_counts("Executed 2 tests, with 1 failure") == (2, 1)
    assert swift_counts("Build failed") == (0, 0)
