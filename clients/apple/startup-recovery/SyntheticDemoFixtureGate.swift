/// Compile-time gate for the Debug synthetic Simulator demo surface.
/// Release builds compile `isCompiledIntoThisBinary` to `false` so TestFlight
/// and production profiles cannot present invented rows through this path.
public enum SyntheticDemoFixtureGate {
    public static var isCompiledIntoThisBinary: Bool {
        #if DEBUG
        true
        #else
        false
        #endif
    }

    /// Debug synthetic Simulator only. Never true in Release.
    public static func shouldPresent(bundleIdentifier: String?) -> Bool {
        #if DEBUG
        bundleIdentifier == "com.cosmasos.synthetic"
        #else
        false
        #endif
    }
}
