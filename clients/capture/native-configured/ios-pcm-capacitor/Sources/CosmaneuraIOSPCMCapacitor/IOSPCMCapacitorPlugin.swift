#if os(iOS)
  @preconcurrency import Capacitor
  import CosmaneuraIOSPCMBridgeCore
  import CosmaneuraIOSPCMCapacitorTransport
  import CosmaneuraIOSPCMCore
  import CoreFoundation
  import Foundation
  import AVFAudio
  import CosmasNativeAuth

  @objc(IOSPCMCapacitorPlugin)
  public final class IOSPCMCapacitorPlugin: CAPPlugin, CAPBridgedPlugin,
    IOSPCMCapacitorEventEmitting, @unchecked Sendable
  {
    public let identifier = "IOSPCMCapacitorPlugin"
    public let jsName = "IOSPCM"
    public let pluginMethods: [CAPPluginMethod] = [
      CAPPluginMethod(name: "getAppState", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "confirmCaptureIdle", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "getCaptureCapabilities", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "extend", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "preparePrivate", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "startPrivate", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "privateInputSignal", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "ready", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "heartbeat", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "acknowledge", returnType: CAPPluginReturnPromise),
      CAPPluginMethod(name: "replayPendingPacket", returnType: CAPPluginReturnPromise),
    ]

    private var transport: IOSPCMCapacitorTransport?
    private let privateSignal = PCMSignalMonitor()
    private let recoveryLock = NSLock()
    private var rendererLost = false
    @MainActor private var providerOwner: (token: String, owner: UUID)?
    @MainActor private var privateOwner: (token: String, permit: NativePrivateRecordingPermit)?
    @MainActor private var privateTokens: [String: NativePrivateRecordingPermit] = [:]

    public override func load() {
      let native = recoveryLock.withLock { () -> IOSPCMCapacitorTransport? in
        guard !rendererLost, transport == nil else { return nil }
        let publisher = IOSPCMCapacitorEventPublisher(emitter: self)
        let native = IOSPCMCapacitorTransport(bridge: IOSPCMBridgeCore(events: publisher, signalMonitor: privateSignal,
          lifecycle: .foregroundPrivate))
        transport = native
        return native
      }
      guard let native else { return }
      Task { @MainActor in
        NativeCaptureStartGate.registerIdleProbe { native.confirmCaptureIdle() }
      }
    }

    /// Native UI only. This is deliberately absent from pluginMethods.
    /// An old plugin stays fenced even if failure precedes its first load.
    @nonobjc public func fenceAndStopForRendererLoss() async throws {
      let retained = recoveryLock.withLock {
        rendererLost = true
        return transport
      }
      try await retained?.fenceAndStopForRendererLoss()
      try await MainActor.run {
        if let selected = privateOwner { try NativePrivateRecordingGate.finish(selected.permit); privateOwner = nil }
      }
    }

    /// Includes pending permission and failed closure in every bridge instance.
    @nonobjc public static func confirmProcessCaptureIdle() -> Bool {
      IOSPCMBridgeCore.confirmProcessCaptureIdle()
    }

    @objc public func getAppState(_ call: CAPPluginCall) {
      perform(call) { transport in
        ["state": await transport.getAppState()]
      }
    }

    @objc public func confirmCaptureIdle(_ call: CAPPluginCall) {
      guard let transport else {
        reject(call, error: IOSPCMCapacitorErrorCode.captureFailed)
        return
      }
      call.resolve(["version": 1, "idle": transport.confirmCaptureIdle()])
    }

    @objc public func getCaptureCapabilities(_ call: CAPPluginCall) {
      guard transport != nil else {
        reject(call, error: IOSPCMCapacitorErrorCode.captureFailed)
        return
      }
      call.resolve(["version": 1, "renewableAuthority": false, "configuredRenewal": true])
    }

    @objc public func start(_ call: CAPPluginCall) {
      guard let transport,
        let encoding = call.getString("encoding"),
        let channels = call.getInt("channels"),
        let sampleRateHz = call.getInt("sampleRateHz"),
        let targetFramesPerChunk = call.getInt("targetFramesPerChunk"),
        let maximumChunks = call.getInt("maximumChunks")
      else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments)
        return
      }
      Task { @MainActor in
       do {
        _ = try IOSPCMCapacitorConfiguration(encoding: encoding, channels: channels,
          sampleRateHz: sampleRateHz, targetFramesPerChunk: targetFramesPerChunk,
          maximumChunks: maximumChunks, authority: nil)
        let ticket = try NativeCaptureStartGate.startTicket()
        guard Bundle.main.bundleIdentifier == "com.cosmasos.beta.ios",
              !call.options.keys.contains("authority"),
              await AVAudioApplication.requestRecordPermission() else {
          throw IOSPCMCapacitorErrorCode.captureFailed
        }
        let token = try await NativeCaptureStartGate.consume(owner: ticket) { permit in
        let authority = try PCMSourceAuthority(runID: permit.runID, generation: permit.generation,
          expiresAtMilliseconds: Int64(permit.captureExpiresAt.timeIntervalSince1970 * 1000),
          hardMaximumChunks: permit.hardMaximumChunks)

        let configuration = try IOSPCMCapacitorConfiguration(
          encoding: encoding,
          channels: channels,
          sampleRateHz: sampleRateHz,
          targetFramesPerChunk: targetFramesPerChunk,
          maximumChunks: maximumChunks,
          authority: authority
        )
        guard permit.startExpiresAt > Date() else { throw IOSPCMCapacitorErrorCode.captureFailed }
        return try transport.start(configuration: configuration)
        }
        providerOwner = (token, ticket)
        call.resolve(["sessionToken": token])
      } catch {
        reject(call, error: error)
       }
      }
    }

    @objc public func preparePrivate(_ call: CAPPluginCall) {
      guard Set(call.options.keys) == ["scope", "revision"], let scope = call.getString("scope"), let revision = call.getString("revision") else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments); return
      }
      Task { @MainActor in
        do {
          guard Bundle.main.bundleIdentifier == "com.cosmasos.beta.ios", let transport,
                await transport.getAppState() == "foreground" else { throw IOSPCMCapacitorErrorCode.captureFailed }
          let proof = try await NativePrivateRecordingGate.prepare(scope: scope, revision: revision)
          let format = ISO8601DateFormatter(); format.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
          call.resolve(["receiptId": proof.id.uuidString.lowercased(), "revision": proof.revision, "expiresAt": format.string(from: proof.expiresAt)])
        } catch { reject(call, error: error) }
      }
    }

    @objc public func startPrivate(_ call: CAPPluginCall) {
      guard Set(call.options.keys) == ["receiptId", "scope", "revision", "recordingId", "startIntent", "consent", "encoding", "channels", "sampleRateHz", "targetFramesPerChunk", "maximumChunks"],
            let receipt = call.getString("receiptId"), let receiptID = UUID(uuidString: receipt), receiptID.uuidString.lowercased() == receipt,
            let recording = call.getString("recordingId"), let recordingID = UUID(uuidString: recording), recordingID.uuidString.lowercased() == recording,
            let intent = call.getString("startIntent"), let intentID = UUID(uuidString: intent), intentID.uuidString.lowercased() == intent,
            let scope = call.getString("scope"), let revision = call.getString("revision"), let consent = call.getObject("consent"),
            call.getString("encoding") == "pcm_s16le", Self.exactInteger(call.options["channels"]) == 1,
            Self.exactInteger(call.options["sampleRateHz"]) == 16000, Self.exactInteger(call.options["targetFramesPerChunk"]) == 160000,
            let maximum = Self.exactInteger(call.options["maximumChunks"]), (1...90).contains(maximum) else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments); return
      }
      Task { @MainActor in
        var permit: NativePrivateRecordingPermit?
        do {
          guard Bundle.main.bundleIdentifier == "com.cosmasos.beta.ios", let transport,
                privateOwner == nil, privateTokens.count < 10000, await transport.getAppState() == "foreground" else { throw IOSPCMCapacitorErrorCode.captureFailed }
          let checked = try NativePrivateRecordingConsent(consent)
          let selected = try NativePrivateRecordingGate.begin(proofID: receiptID, scope: scope, revision: revision,
              recordingID: recordingID, intent: intentID, consent: checked, maximumChunks: maximum)
          permit = selected
          // The owned Core handle requests permission. Return its token before
          // the modal awaits, so Stop can cancel this exact pending Start.
          let foreground = await transport.getAppState() == "foreground"
          let token = try NativePrivateRecordingGate.consume(selected, foreground: foreground) {
            let authority = try PCMSourceAuthority(runID: selected.runID.uuidString.lowercased(), generation: 1,
                expiresAtMilliseconds: Int64(selected.captureExpiresAt.timeIntervalSince1970 * 1000), hardMaximumChunks: selected.maximumChunks)
            privateSignal.reset()
            return try transport.start(configuration: IOSPCMCapacitorConfiguration(encoding: "pcm_s16le", channels: 1,
                sampleRateHz: 16000, targetFramesPerChunk: 160000, maximumChunks: maximum, authority: authority))
          }
          privateOwner = (token, selected)
          privateTokens[token] = selected
          try NativePrivateRecordingGate.retainStop(selected) { [weak self] in
            _ = try await transport.stop(sessionToken: token, mode: .discard)
            if self?.privateOwner?.token == token { self?.privateOwner = nil }
          }
          call.resolve(["sessionToken": token])
        } catch {
          if let permit { try? NativePrivateRecordingGate.finish(permit) }
          reject(call, error: error)
        }
      }
    }

    @objc public func privateInputSignal(_ call: CAPPluginCall) {
      guard call.options.isEmpty else { reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments); return }
      Task { @MainActor in
        guard let owner = privateOwner, NativePrivateRecordingGate.current(owner.permit) else {
          call.resolve(["version": 2, "signal": NSNull()]); return
        }
        let s = privateSignal.snapshot()
        call.resolve(["version": 2, "signal": [
          "inputBuffers": s.inputBuffers, "convertedBuffers": s.convertedBuffers,
          "inputEverNonzero": s.inputEverNonzero, "convertedEverNonzero": s.convertedEverNonzero,
          "inputLevel": s.inputLevel, "convertedLevel": s.convertedLevel,
          "inputAgeMs": s.inputAgeMs as Any? ?? NSNull(), "convertedAgeMs": s.convertedAgeMs as Any? ?? NSNull(),
          "zeroInputMs": s.zeroInputMs, "route": s.route.rawValue, "inputMuted": AVAudioApplication.shared.isInputMuted
        ]])
      }
    }

    @objc public func extend(_ call: CAPPluginCall) {
      if Bundle.main.bundleIdentifier == "com.cosmasos.beta.ios" {
        extendConfigured(call)
        return
      }
      guard let token = call.getString("sessionToken"),
        let value = call.getObject("extension"),
        Set(value.keys) == Set(["runId", "generation", "expiresAtMs", "maximumChunks"]),
        let runID = value["runId"] as? String,
        let generation = Self.exactInteger(value["generation"]),
        let expires = Self.exactInteger(value["expiresAtMs"]),
        let maximum = Self.exactInteger(value["maximumChunks"])
      else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments)
        return
      }
      let extensionValue = PCMSourceExtension(runID: runID, generation: generation,
        expiresAtMilliseconds: Int64(expires), maximumChunks: maximum)
      perform(call) { transport in
        try await transport.extend(sessionToken: token, value: extensionValue)
        return ["sessionToken": token, "runId": runID, "generation": generation,
          "expiresAtMs": expires, "maximumChunks": maximum]
      }
    }

    private func extendConfigured(_ call: CAPPluginCall) {
      guard let token = call.getString("sessionToken"), let value = call.getObject("extension"),
        Set(call.options.keys) == ["sessionToken", "extension"],
        Set(value.keys) == ["leaseReceiptId", "leaseGeneration", "captureAuthorizedUntil", "reservationBatchId",
          "firstSequenceNumber", "reservationCount"],
        let receipt = value["leaseReceiptId"] as? String, let receiptID = UUID(uuidString: receipt),
        receiptID.uuidString.lowercased() == receipt,
        let generation = Self.exactInteger(value["leaseGeneration"]),
        let until = value["captureAuthorizedUntil"] as? String,
        let batch = value["reservationBatchId"] as? String, let batchID = UUID(uuidString: batch),
        batchID.uuidString.lowercased() == batch,
        let first = Self.exactInteger(value["firstSequenceNumber"]),
        let count = Self.exactInteger(value["reservationCount"]) else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments); return
      }
      Task { @MainActor in
        do {
          guard let transport, let providerOwner, providerOwner.token == token else {
            throw IOSPCMCapacitorErrorCode.captureFailed
          }
          let request = try NativeCaptureExtensionRequest(leaseReceiptID: receiptID, leaseGeneration: generation,
            captureAuthorizedUntil: until, reservationBatchID: batchID, firstSequenceNumber: first, reservationCount: count)
          let maximum = try await NativeCaptureStartGate.extend(owner: providerOwner.owner, request: request) { permit in
            let extensionValue = PCMSourceExtension(runID: permit.runID, generation: permit.generation,
              expiresAtMilliseconds: Int64(permit.captureExpiresAt.timeIntervalSince1970 * 1000),
              maximumChunks: permit.maximumChunks,
              authorizationExpiresAtMilliseconds: Int64(permit.expiresAt.timeIntervalSince1970 * 1000))
            try await transport.extend(sessionToken: token, value: extensionValue)
            return permit.maximumChunks
          }
          call.resolve(["sessionToken": token, "leaseGeneration": generation,
            "captureAuthorizedUntil": until, "maximumChunks": maximum])
        } catch { reject(call, error: error) }
      }
    }

    private static func exactInteger(_ value: Any?) -> Int? {
      guard let number = value as? NSNumber,
        CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue.isFinite,
        abs(number.doubleValue) <= 9_007_199_254_740_991,
        number.doubleValue.rounded(.towardZero) == number.doubleValue else { return nil }
      return number.intValue
    }

    @objc public func ready(_ call: CAPPluginCall) {
      guard let sessionToken = call.getString("sessionToken") else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments)
        return
      }
      perform(call) { transport in
        try await transport.ready(sessionToken: sessionToken)
        return [:]
      }
    }

    @objc public func heartbeat(_ call: CAPPluginCall) {
      guard let sessionToken = call.getString("sessionToken") else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments)
        return
      }
      perform(call) { transport in
        try await transport.heartbeat(sessionToken: sessionToken)
        return [:]
      }
    }

    @objc public func stop(_ call: CAPPluginCall) {
      guard let sessionToken = call.getString("sessionToken"),
        let rawMode = call.getString("mode")
      else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments)
        return
      }
      let mode: IOSPCMBridgeStopMode
      switch rawMode {
      case "drain": mode = .drain
      case "discard": mode = .discard
      default:
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments)
        return
      }
      Task { @MainActor in
       do {
        guard let transport else { throw IOSPCMCapacitorErrorCode.stopFailed }
        let privateSelected = privateOwner?.token == sessionToken ? privateOwner : nil
        let privatePermit = privateTokens[sessionToken]
        let allowFinal = privatePermit.map { NativePrivateRecordingGate.accountCurrent($0) } ?? true
        let result = try await transport.stop(sessionToken: sessionToken, mode: mode)
        if let privateSelected { try NativePrivateRecordingGate.finish(privateSelected.permit); privateOwner = nil }
        let stillCurrent = privatePermit.map { NativePrivateRecordingGate.accountCurrent($0) } ?? true
        call.resolve(["finalPcmPacket": allowFinal && stillCurrent ? result.finalPcmPacket.map(Self.packetObject) ?? NSNull() : NSNull()])
       } catch { reject(call, error: error) }
      }
    }

    @objc public func acknowledge(_ call: CAPPluginCall) {
      guard let sessionToken = call.getString("sessionToken"),
        let sequenceNumber = call.getInt("sequenceNumber"), let transport
      else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments)
        return
      }
      do {
        let result = try transport.acknowledge(
          sessionToken: sessionToken,
          sequenceNumber: sequenceNumber
        )
        call.resolve(["result": result.rawValue])
      } catch {
        reject(call, error: error)
      }
    }

    @objc public func replayPendingPacket(_ call: CAPPluginCall) {
      guard let sessionToken = call.getString("sessionToken"),
        let sequenceNumber = call.getInt("sequenceNumber"), let transport
      else {
        reject(call, error: IOSPCMCapacitorErrorCode.invalidArguments)
        return
      }
      do {
        let result = try transport.replayPendingPacket(
          sessionToken: sessionToken,
          sequenceNumber: sequenceNumber
        )
        call.resolve(["result": result.rawValue])
      } catch {
        reject(call, error: error)
      }
    }

    public func emit(_ event: IOSPCMCapacitorEvent) throws {
      Task { @MainActor [weak self] in
        guard let self else { return }
        let token: String
        switch event {
        case .packet(let packet): token = packet.sessionToken
        case .interruption(let sessionToken, _), .terminal(let sessionToken, _), .windowClosed(let sessionToken, _): token = sessionToken
        }
        if let permit = privateTokens[token], !NativePrivateRecordingGate.accountCurrent(permit) {
          NativePrivateRecordingGate.retire(); return
        }
        notifyListeners("iosNativePcmEvent", data: Self.eventObject(event))
      }
    }

    private func perform(
      _ call: CAPPluginCall,
      operation: @escaping @Sendable (IOSPCMCapacitorTransport) async throws -> JSObject
    ) {
      guard let transport else {
        reject(call, error: IOSPCMCapacitorErrorCode.captureFailed)
        return
      }
      Task { @MainActor [weak self] in
        do {
          call.resolve(try await operation(transport))
        } catch {
          self?.reject(call, error: error)
        }
      }
    }

    private func reject(_ call: CAPPluginCall, error: Error) {
      let code =
        (error as? IOSPCMCapacitorErrorCode)?.rawValue
        ?? IOSPCMCapacitorErrorCode.captureFailed.rawValue
      call.reject(code, code)
    }

    private static func packetObject(_ packet: IOSPCMCapacitorPacket) -> JSObject {
      [
        "sessionToken": packet.sessionToken,
        "sequenceNumber": packet.sequenceNumber,
        "pcmBase64": packet.pcmBase64,
      ]
    }

    private static func eventObject(_ event: IOSPCMCapacitorEvent) -> JSObject {
      switch event {
      case .windowClosed(let sessionToken, let reason):
        return ["kind": "window_closed", "sessionToken": sessionToken, "reason": reason]
      case .packet(let packet):
        return ["kind": "packet", "packet": packetObject(packet)]
      case .interruption(let sessionToken, let code):
        return ["kind": "interruption", "sessionToken": sessionToken, "code": code]
      case .terminal(let sessionToken, let code):
        return ["kind": "terminal", "sessionToken": sessionToken, "code": code]
      }
    }
  }
#endif
