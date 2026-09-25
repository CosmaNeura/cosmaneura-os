import AppKit
import Darwin
import CoreGraphics
import ScribeDesktopAudio

@main
@MainActor
struct ScribeProviderPresentationHelper {
    static func main() {
        let arguments = Array(CommandLine.arguments.dropFirst())
        guard [["--presentation-v1"], ["--availability-v1"], ["--request-permissions-v1"]].contains(arguments) else { _exit(64) }
        signal(SIGPIPE, SIG_IGN)
        let application = NSApplication.shared
        application.setActivationPolicy(.accessory)
        Task { @MainActor in
            if arguments != ["--presentation-v1"] {
                if arguments == ["--request-permissions-v1"], !CGPreflightScreenCaptureAccess() {
                    _ = CGRequestScreenCaptureAccess()
                }
                await DesktopAudioProcess.writeAvailability(CGPreflightScreenCaptureAccess())
                _exit(0)
            }
            let result = await ProviderPresentationProcess.run(surface: MacProviderPresentationSurface())
            _exit(result)
        }
        application.run()
    }
}
