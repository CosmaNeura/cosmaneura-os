#if DEBUG
import Foundation
#endif

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
    /// `-COSMAS_SKIP_SYNTHETIC_DEMO` forces the real Capacitor / native plugin path.
    public static func shouldPresent(bundleIdentifier: String?) -> Bool {
        #if DEBUG
        bundleIdentifier == "com.cosmasos.synthetic"
            && !ProcessInfo.processInfo.arguments.contains("-COSMAS_SKIP_SYNTHETIC_DEMO")
        #else
        false
        #endif
    }
}
