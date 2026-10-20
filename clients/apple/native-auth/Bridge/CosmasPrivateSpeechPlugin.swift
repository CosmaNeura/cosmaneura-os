#if os(iOS)
@preconcurrency import Capacitor
@preconcurrency import Speech
@preconcurrency import AVFoundation
import UIKit
import CryptoKit
import Foundation
import CosmasNativeAuth

/// A saved PCM stream reaches only Apple's mandatory on-device recognizer.
/// No URL request, temporary audio file, microphone or patient/visit admission exists here.
@objc(CosmasPrivateSpeechPlugin)
public final class CosmasPrivateSpeechPlugin: CAPPlugin, CAPBridgedPlugin, @unchecked Sendable {
    public let identifier = "CosmasPrivateSpeechPlugin"
    public let jsName = "CosmasPrivateSpeech"
    public let pluginMethods: [CAPPluginMethod] = ["begin", "append", "finish", "cancel"].map {
        CAPPluginMethod(name: $0, returnType: CAPPluginReturnPromise)
    }
    @MainActor private final class Run {
        let id = UUID().uuidString.lowercased(), recording: String, manifest: String
        let permit: NativePrivateSavedReadPermit, expectedChunks: Int, expectedFrames: Int
        let request: SFSpeechAudioBufferRecognitionRequest
        var task: SFSpeechRecognitionTask?, deadline: Task<Void, Never>?, finishCall: CAPPluginCall?
        var buffers: [AVAudioPCMBuffer] = [], chunks = 0, frames = 0, ended = false
        var result: String?, failure: String?
        init(recording: String, manifest: String, permit: NativePrivateSavedReadPermit, chunks: Int, frames: Int) {
            self.recording = recording; self.manifest = manifest; self.permit = permit
            expectedChunks = chunks; expectedFrames = frames
            request = SFSpeechAudioBufferRecognitionRequest()
            request.requiresOnDeviceRecognition = true; request.shouldReportPartialResults = false
        }
        func clear() {
            deadline?.cancel(); deadline = nil; task?.cancel(); task = nil
            for buffer in buffers { if let samples = buffer.floatChannelData?[0] { samples.update(repeating: 0, count: Int(buffer.frameLength)) } }
            buffers.removeAll()
        }
    }
    @MainActor private var active: Run?, preparing = false, fenced = false
    private var inactive: NSObjectProtocol?
    public override func load() {
        inactive = NotificationCenter.default.addObserver(forName: UIApplication.willResignActiveNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.fail("private_speech_inactive") }
        }
    }
    deinit { if let inactive { NotificationCenter.default.removeObserver(inactive) } }
    @MainActor public func fenceForRendererLoss() { fenced = true; fail("private_speech_changed") }
    @MainActor private func current(_ run: Run) -> Bool {
        !fenced && active === run && UIApplication.shared.applicationState == .active && NativePrivateRecordingGate.savedCurrent(run.permit)
    }
    private static func uuid(_ s: String) -> Bool { UUID(uuidString: s)?.uuidString.lowercased() == s }
    private static func hash(_ s: String) -> Bool { s.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil }
    private static func reject(_ call: CAPPluginCall, _ code: String) { call.reject("Private on-device transcription unavailable", code) }
    @MainActor private func fail(_ code: String) {
        guard let run = active else { return }; run.failure = code; run.clear()
        if let call = run.finishCall { run.finishCall = nil; Self.reject(call, code) }
    }
    @objc public func begin(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard !self.fenced, !self.preparing, self.active == nil, UIApplication.shared.applicationState == .active,
                  Set(call.options.keys) == ["scope", "revision", "recordingId", "audioSHA256", "chunks", "frames", "language", "intent"],
                  let scope = call.getString("scope"), Self.hash(scope), let revision = call.getString("revision"), !revision.isEmpty,
                  let recording = call.getString("recordingId"), Self.uuid(recording), let manifest = call.getString("audioSHA256"), Self.hash(manifest),
                  let intent = call.getString("intent"), Self.uuid(intent), let chunks = call.getInt("chunks"), chunks > 0,
                  let frames = call.getInt("frames"), frames > 0 else { Self.reject(call, "private_speech_changed"); return }
            guard call.getString("language") == "en-US" else { Self.reject(call, "private_speech_language_unsupported"); return }
            // Retained float buffers are bounded to ten minutes; longer original audio remains encrypted and usable.
            guard chunks <= 60, frames <= 9_600_000, frames <= chunks * 160_000 else { Self.reject(call, "private_speech_too_long"); return }
            guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")), recognizer.supportsOnDeviceRecognition else { Self.reject(call, "private_speech_unavailable"); return }
            self.preparing = true; defer { self.preparing = false }
            do {
                let permit = try await NativePrivateRecordingGate.authorizeSaved(scope: scope, revision: revision)
                guard !self.fenced, UIApplication.shared.applicationState == .active else { Self.reject(call, "private_speech_inactive"); return }
                let status: SFSpeechRecognizerAuthorizationStatus
                if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
                    // This method is reached only by the explicit Transcribe action.
                    status = await withCheckedContinuation { continuation in SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) } }
                } else { status = SFSpeechRecognizer.authorizationStatus() }
                guard NativePrivateRecordingGate.savedCurrent(permit), !self.fenced, UIApplication.shared.applicationState == .active else { Self.reject(call, "private_speech_changed"); return }
                guard status == .authorized else { Self.reject(call, status == .restricted ? "private_speech_permission_restricted" : "private_speech_permission_denied"); return }
                guard recognizer.isAvailable else { Self.reject(call, "private_speech_unavailable"); return }
                let run = Run(recording: recording, manifest: manifest, permit: permit, chunks: chunks, frames: frames); self.active = run
                run.task = recognizer.recognitionTask(with: run.request) { [weak self, weak run] result, error in
                    Task { @MainActor in
                        guard let self, let run, self.active === run, run.result == nil, run.failure == nil else { return }
                        guard self.current(run) else { self.fail("private_speech_changed"); return }
                        if let error { _ = error; self.fail("private_speech_unavailable"); return }
                        if let result, result.isFinal {
                            guard run.ended, run.frames == run.expectedFrames, run.chunks == run.expectedChunks else { self.fail("private_speech_incomplete"); return }
                            let text = result.bestTranscription.formattedString
                            guard text.utf16.count <= 32000, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { self.fail("private_speech_empty"); return }
                            run.result = text; run.clear(); self.resolve(run)
                        }
                    }
                }
                run.deadline = Task { @MainActor [weak self, weak run] in
                    try? await Task.sleep(for: .seconds(180))
                    guard !Task.isCancelled, let self, let run, self.active === run else { return }; self.fail("private_speech_timeout")
                }
                call.resolve(["runId": run.id])
            } catch { Self.reject(call, "private_speech_changed") }
        }
    }
    @objc public func append(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard Set(call.options.keys) == ["runId", "sequence", "sha256", "wavBase64"], let id = call.getString("runId"), let run = self.active,
                  run.id == id, self.current(run), !run.ended, run.failure == nil, let sequence = call.getInt("sequence"), sequence == run.chunks,
                  run.chunks < run.expectedChunks, let digest = call.getString("sha256"), Self.hash(digest), let encoded = call.getString("wavBase64"), encoded.utf8.count <= 426728,
                  var data = Data(base64Encoded: encoded), data.count >= 46, data.count <= 320044, data.base64EncodedString() == encoded else { Self.reject(call, "private_speech_changed"); return }
            defer { data.resetBytes(in: 0..<data.count) }
            func u16(_ o: Int) -> UInt16 { UInt16(data[o]) | UInt16(data[o+1]) << 8 }
            func u32(_ o: Int) -> UInt32 { UInt32(data[o]) | UInt32(data[o+1]) << 8 | UInt32(data[o+2]) << 16 | UInt32(data[o+3]) << 24 }
            func ascii(_ o: Int, _ n: Int) -> String { String(data: data.subdata(in: o..<o+n), encoding: .ascii) ?? "" }
            let count = (data.count-44)/2
            guard SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == digest,
                  ascii(0,4) == "RIFF", u32(4) == data.count-8, ascii(8,4) == "WAVE", ascii(12,4) == "fmt ", u32(16) == 16,
                  u16(20) == 1, u16(22) == 1, u32(24) == 16000, u32(28) == 32000, u16(32) == 2, u16(34) == 16,
                  ascii(36,4) == "data", u32(40) == data.count-44, (data.count-44)%2 == 0, run.frames + count <= run.expectedFrames,
                  let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
                  let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(count)), let samples = buffer.floatChannelData?[0] else {
                self.fail("private_speech_changed"); Self.reject(call, "private_speech_changed"); return
            }
            buffer.frameLength = AVAudioFrameCount(count)
            for i in 0..<count { samples[i] = Float(Int16(bitPattern: u16(44+i*2))) / 32768 }
            run.buffers.append(buffer); run.request.append(buffer); run.frames += count; run.chunks += 1
            call.resolve(["sequence": sequence])
        }
    }
    @MainActor private func resolve(_ run: Run) {
        guard let call = run.finishCall, let text = run.result, current(run) else { return }; run.finishCall = nil
        call.resolve(["runId": run.id, "recordingId": run.recording, "audioSHA256": run.manifest, "frames": run.frames,
                      "text": text, "engine": "ios-speech-on-device-v1", "language": "en-US"])
    }
    @objc public func finish(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard Set(call.options.keys) == ["runId"], let id = call.getString("runId"), let run = self.active, run.id == id, self.current(run), run.finishCall == nil else { Self.reject(call, "private_speech_changed"); return }
            if let failure = run.failure { Self.reject(call, failure); return }
            guard run.chunks == run.expectedChunks, run.frames == run.expectedFrames else { self.fail("private_speech_changed"); Self.reject(call, "private_speech_changed"); return }
            run.finishCall = call; run.ended = true; run.request.endAudio(); self.resolve(run)
        }
    }
    @objc public func cancel(_ call: CAPPluginCall) {
        Task { @MainActor in
            guard Set(call.options.keys) == ["runId"], let id = call.getString("runId") else { Self.reject(call, "private_speech_changed"); return }
            if let run = self.active, run.id == id { self.fail("private_speech_inactive"); self.active = nil }
            call.resolve()
        }
    }
}
#endif
