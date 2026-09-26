import { parseNativeProcessFence, type NativeProcessFence } from "./native-process-fence.js";
import { spawn } from "node:child_process";
import type { ChildProcessByStdio } from "node:child_process";
import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, realpath } from "node:fs/promises";
import { dirname, isAbsolute } from "node:path";
import type { Readable, Writable } from "node:stream";
import type { DesktopPCMDriver, DesktopPCMDriverSession, DesktopPCMFailure,
  DesktopPCMStart, DesktopPCMCompletion } from "./native-pcm-driver.js";
import { parseDesktopPCMStart, parseDesktopPCMCompletion } from "./pcm-capture-source.js";
import { NativeProcessDecoder, nativeCommand, nativeMetadata, exactKeys } from "./native-process-wire.js";
import type { CaptureSourceExtension } from "../../capture/src/configured/capture";
import { continuousOwner, continuousPermit, type DesktopContinuousAuthority,
  type DesktopContinuousOwner, type DesktopContinuousPermit } from "./continuous-capture";

export interface AuthorizedDesktopSelection {
  readonly application: "com.google.Chrome" | "us.zoom.xos";
  readonly processID: number;
  readonly windowID: number;
  readonly captureAuthorizedUntil: number;
}
export interface NativeProcessDriverOptions {
  /** Existing companion enablement; false/omitted never executes a helper. */
  readonly enabled?: boolean;
  readonly helperPath: string;
  readonly helperSha256: string;
  /** Observed native workstation state, supplied by the trusted host. */
  readonly isSessionActive: () => boolean;
  /** Fresh existing capability/consent/lease/indicator authority. No credentials
   * or renderer-supplied authority fields are passed through the pipe. */
  readonly authorizeSelectedWindow: () => Promise<AuthorizedDesktopSelection>;
  /** Required for actual capture-v2 starts; supplied only by the native backend. */
  readonly getProcessFence?: () => NativeProcessFence;
  readonly continuation?: DesktopContinuousAuthority;
}
type Child = ChildProcessByStdio<Writable, Readable, null>;
type Sink = Parameters<DesktopPCMDriver["start"]>[1];
const DEADLINE_MS = 15_000;
const MAX_FRAMES = 1_382_400_000;
const CODES: readonly DesktopPCMFailure[] = ["permission_required", "device_changed", "session_locked",
  "clock_discontinuity", "overflow", "failed"];

/** Main process only. The packaged helper path/hash are release inputs, never an
 * IPC argument. This source preparation does not establish signing acceptance. */
export class NativeProcessPCMDriver implements DesktopPCMDriver {
  private readonly options: NativeProcessDriverOptions;
  constructor(options: NativeProcessDriverOptions) { requireMain(); this.options = Object.freeze({ ...options }); }
  async getAvailability(): Promise<boolean> {
    requireMain();
    try {
      if (!this.options.enabled || !this.options.isSessionActive()) return false;
      await verifyNativeHelper(this.options);
      if (!this.options.isSessionActive()) return false;
      return await probe(this.options.helperPath) && this.options.isSessionActive();
    } catch { return false; }
  }
  requestPermissions(signal?: AbortSignal): Promise<boolean> {
    return nativeHelperPermissions(this.options, true, signal);
  }
  async supportsContinuousCapture(): Promise<boolean> { return !!this.options.continuation; }
  start(configuration: Parameters<DesktopPCMDriver["start"]>[0], sink: Sink): DesktopPCMDriverSession {
    requireMain();
    if (!this.options.enabled || !this.options.isSessionActive() || configuration.sampleRateHz !== 16_000
      || !integer(configuration.maximumOutputFrames, 1, MAX_FRAMES)) throw failure();
    if (this.options.continuation && (configuration.targetFramesPerChunk !== 160_000
      || configuration.maximumOutputFrames % 160_000 !== 0)) throw failure();
    return new ProcessSession(this.options, configuration.maximumOutputFrames, sink);
  }
}

class ProcessSession implements DesktopPCMDriverSession {
  private readonly readiness = deferred<DesktopPCMStart>();
  readonly ready = this.readiness.promise;
  private readonly exited = deferred<void>();
  private child?: Child;
  private readonly decoder = new NativeProcessDecoder();
  private startValue?: DesktopPCMStart;
  private completion: DesktopPCMCompletion | null = null;
  private active = false;
  private cancelled = false;
  private failed = false;
  private receivedFrames = 0;
  private receiving = false;
  private packetWork = Promise.resolve();
  private exitObserved = false;
  private closingInput = false;
  private confirmed = false;
  private stopping = false;
  private continuous?: DesktopContinuousOwner;
  private captureDeadline = 0;
  private maximumChunks = 0;
  private extension?: { request: number; permit: DesktopContinuousPermit; response: ReturnType<typeof deferred<void>> };
  private extending = false;
  private request = 0;
  private heartbeat?: ReturnType<typeof setInterval>;
  private startupTimer?: ReturnType<typeof setTimeout>;
  private captureTimer?: ReturnType<typeof setTimeout>;
  private readonly stops = new Map<number, { readonly mode: "drain" | "discard";
    readonly response: ReturnType<typeof deferred<DesktopPCMCompletion | null>> }>();

  constructor(private readonly options: NativeProcessDriverOptions, private maximumFrames: number, private readonly sink: Sink) {
    // The handle exists before the first asynchronous authorization/file read.
    void this.ready.catch(() => undefined);
    this.startupTimer = setTimeout(() => { this.fail("failed"); }, DEADLINE_MS);
    void this.prepare().catch(() => { this.fail("failed"); });
  }
  private async prepare(): Promise<void> {
    const selection = Object.freeze({ ...await this.options.authorizeSelectedWindow() });
    if (this.cancelled) return;
    await verifyNativeHelper(this.options);
    if (this.cancelled) return;
    const duration = Math.floor((selection.captureAuthorizedUntil - Date.now()) / 1000);
    if (!this.options.isSessionActive() || !exactKeys({ ...selection },
      ["application", "processID", "windowID", "captureAuthorizedUntil"])
      || !["com.google.Chrome", "us.zoom.xos"].includes(selection.application)
      || !integer(selection.processID, 1, 2_147_483_647) || !integer(selection.windowID, 1, 4_294_967_295)
      || !Number.isSafeInteger(selection.captureAuthorizedUntil) || !integer(duration, 1, 86_400)) throw failure();
    this.maximumFrames = Math.min(this.maximumFrames, duration * 16_000);
    const processFence = parseNativeProcessFence(this.options.getProcessFence?.());
    if (this.options.continuation) {
      this.continuous = continuousOwner(this.options.continuation.getOwner());
      this.maximumChunks = Math.ceil(this.maximumFrames / 160_000);
      if (this.maximumChunks > this.continuous.hardMaximumChunks) throw failure();
    }
    this.captureDeadline = selection.captureAuthorizedUntil;
    const child = launch(this.options.helperPath, "--capture-v2");
    this.child = child;
    child.stdout.on("data", (bytes: Buffer) => {
      try { this.decoder.push(bytes, (kind, payload) => { this.receive(kind, payload); }); }
      catch { this.breakTransport(); }
    });
    child.stdin.on("error", () => { this.breakTransport(); });
    child.on("error", () => { this.fail("failed"); });
    child.once("close", () => {
      this.exitObserved = true; clearInterval(this.heartbeat); clearTimeout(this.startupTimer); clearTimeout(this.captureTimer);
      try { this.decoder.finish(); } catch { this.fail("failed"); }
      if (!this.confirmed) this.fail("failed");
      this.readiness.reject(failure());
      this.extension?.response.reject(failure());
      for (const stop of this.stops.values()) stop.response.reject(failure());
      this.stops.clear(); this.exited.resolve();
    });
    this.send({ type: "start", application: selection.application, processID: selection.processID,
      windowID: selection.windowID, maximumDurationSeconds: duration, maximumOutputFrames: this.maximumFrames, processFence,
      ...(this.continuous ? {continuation: {...this.continuous, maximumChunks: this.maximumChunks,
        captureAuthorizedUntil: this.captureDeadline}} : {}) });
    this.captureTimer = setTimeout(() => { this.fail("failed"); }, Math.max(0, selection.captureAuthorizedUntil - Date.now()));
    this.heartbeat = setInterval(() => {
      if (this.closingInput) return;
      try {
        if (!this.options.isSessionActive()) this.fail("session_locked");
        else this.send({ type: "heartbeat" });
      } catch { this.fail("failed"); }
    }, 5_000);
  }
  activate(): void {
    if (!this.startValue || this.active || this.cancelled || this.closingInput || this.exitObserved) throw failure();
    if (!this.options.isSessionActive()) { this.fail("session_locked"); throw failure(); }
    this.active = true; this.send({ type: "activate" });
  }
  async extend(value: CaptureSourceExtension): Promise<void> {
    const live = () => this.active && !this.stopping && !this.cancelled && !this.failed
      && !this.closingInput && !this.exitObserved && this.options.isSessionActive() && this.captureDeadline > Date.now();
    if (!live() || this.extending || !this.continuous || !this.options.continuation) throw failure();
    this.extending = true;
    try {
      const raw = await this.options.continuation.authorize(value);
      if (!live()) throw failure();
      const permit = continuousPermit(raw, this.continuous, this.continuous.generation,
        this.captureDeadline, this.maximumChunks, value);
      if (this.request >= 32) throw failure();
      const request = ++this.request, response = deferred<void>();
      this.extension = {request, permit, response};
      // Native authorization precedes this widening. Delivery can arrive before
      // the private acknowledgment; the old deadline still stops an uncertain run.
      this.maximumFrames = permit.maximumChunks * 160_000;
      this.send({type: "extend", request, permit});
      await deadline(response.promise);
    } finally { this.extending = false; }
  }
  stop(options: { readonly mode: "drain" | "discard" }): Promise<DesktopPCMCompletion | null> {
    this.stopping = true;
    this.extension?.response.reject(failure());
    if (options.mode === "discard" || !this.active) {
      this.cancelled = true; this.readiness.reject(failure());
    }
    // Cancellation before spawn is definitive: prepare checks it after every await.
    if (!this.child) { this.cancelled = true; clearTimeout(this.startupTimer); return Promise.resolve(null); }
    if (this.exitObserved || this.closingInput) return deadline(this.finishStop(this.cancelled ? null : this.completion));
    if (this.stops.size >= 4 || this.request >= 32) return Promise.reject(failure());
    const request = ++this.request;
    const response = deferred<DesktopPCMCompletion | null>();
    const mode = this.cancelled ? "discard" : "drain";
    this.stops.set(request, { mode, response });
    this.send({ type: "stop", request, mode });
    // Timeout rejects this caller, but retains the request/child for reconciliation.
    // It never kills/restarts recording or pretends that an OS stop was confirmed.
    return deadline(response.promise.then(value => this.finishStop(value)));
  }
  private async finishStop(value: DesktopPCMCompletion | null): Promise<DesktopPCMCompletion | null> {
    await this.exited.promise;
    await this.packetWork;
    if (!this.cancelled && !this.confirmed) throw failure();
    return this.cancelled ? null : value;
  }
  private receive(kind: number, payload: Buffer): void {
    if (kind === 2) {
      if (this.cancelled) return;
      const firstFrame = payload.readUInt32BE(0), frames = (payload.length - 4) / 2;
      if (!this.active || this.receiving || this.confirmed || firstFrame !== this.receivedFrames
        || this.receivedFrames + frames > this.maximumFrames) throw failure();
      const bytes = new Uint8Array(payload.length - 4); bytes.set(payload.subarray(4));
      this.receivedFrames += frames; this.receiving = true;
      this.packetWork = Promise.resolve().then(async () => {
        try {
          if (!this.cancelled) await this.sink.onPcmPacket({ firstFrame, pcmBytes: bytes });
          if (!this.cancelled) this.send({ type: "ack", firstFrame });
        } catch { this.fail("failed"); }
        finally { bytes.fill(0); this.receiving = false; }
      });
      return;
    }
    const value = nativeMetadata(payload);
    switch (value.type) {
      case "ready":
        if (!exactKeys(value, ["type", "start"]) || this.startValue || this.confirmed) throw failure();
        if (this.cancelled) return;
        this.startValue = parseDesktopPCMStart(value.start); clearTimeout(this.startupTimer);
        this.readiness.resolve(this.startValue); return;
      case "failure":
        if (!exactKeys(value, ["type", "code"]) || !CODES.includes(value.code as DesktopPCMFailure)) throw failure();
        this.fail(value.code as DesktopPCMFailure); return;
      case "extended":
      case "extensionFailed": {
        if (!exactKeys(value, value.type === "extended" ? ["type", "request", "permit"] : ["type", "request"])
          || !this.extension || value.request !== this.extension.request) throw failure();
        const extension = this.extension;
        if (value.type === "extensionFailed") { extension.response.reject(failure()); return; }
        const received = value.permit as Record<string, unknown> | undefined;
        if (!received || !exactKeys(received, Object.keys(extension.permit))
          || Object.entries(extension.permit).some(([key, item]) => received[key] !== item)) throw failure();
        if (this.stopping) { extension.response.reject(failure()); return; }
        if (!this.continuous || Date.now() >= this.captureDeadline || Date.now() >= extension.permit.expiresAt) {
          extension.response.reject(failure()); this.fail("failed"); return;
        }
        this.continuous = {...this.continuous, generation: extension.permit.generation};
        this.maximumChunks = extension.permit.maximumChunks;
        this.captureDeadline = extension.permit.captureAuthorizedUntil;
        clearTimeout(this.captureTimer);
        this.captureTimer = setTimeout(() => this.fail("failed"), Math.max(0, this.captureDeadline - Date.now()));
        extension.response.resolve(); return;
      }
      case "stopped":
      case "stopFailed": {
        if (!exactKeys(value, value.type === "stopped" ? ["type", "request", "completion"] : ["type", "request"])
          || !integer(value.request, 1, 32)) throw failure();
        const stop = this.stops.get(value.request);
        if (!stop) throw failure();
        if (value.type === "stopFailed") {
          this.stops.delete(value.request); stop.response.reject(failure()); return;
        }
        if (!this.cancelled) {
          if (!this.startValue || value.completion === null || this.receiving) throw failure();
          this.completion = parseDesktopPCMCompletion(value.completion, this.startValue, this.receivedFrames);
        } else if (value.completion !== null) {
          // A drain receipt may already be in the pipe when discard is requested.
          const completion = value.completion as Partial<DesktopPCMCompletion> | undefined;
          if (stop.mode !== "drain" || !this.startValue || !integer(completion?.outputFrames, 1, this.maximumFrames)) throw failure();
          parseDesktopPCMCompletion(value.completion, this.startValue, completion.outputFrames);
        }
        this.stops.delete(value.request);
        this.confirmed = true; stop.response.resolve(this.cancelled ? null : this.completion);
        if (this.stops.size === 0) {
          this.closingInput = true; clearInterval(this.heartbeat); clearTimeout(this.startupTimer); clearTimeout(this.captureTimer);
          this.child?.stdin.end();
        }
        return;
      }
      default: throw failure();
    }
  }
  private send(value: Readonly<Record<string, unknown>>): void {
    if (!this.child || this.closingInput || this.exitObserved) return;
    try { this.child.stdin.write(nativeCommand(value)); }
    catch { this.fail("failed"); }
  }
  private fail(code: DesktopPCMFailure): void {
    if (this.failed) return;
    this.failed = true; this.readiness.reject(failure());
    // Begin cleanup before notifying the existing capture controller.
    void this.stop({ mode: "discard" }).catch(() => undefined);
    try { this.sink.onFailure(code); } catch { /* Cleanup remains owned here. */ }
  }
  private breakTransport(): void {
    this.fail("failed"); this.decoder.clear();
    // A corrupted pipe cannot carry a trustworthy stop receipt. EOF makes the
    // dedicated helper stop or exit at its bounded parent-loss deadline.
    this.closingInput = true; clearInterval(this.heartbeat); clearTimeout(this.startupTimer); clearTimeout(this.captureTimer);
    for (const stop of this.stops.values()) stop.response.reject(failure());
    this.extension?.response.reject(failure());
    this.stops.clear(); this.child?.stdin.end();
  }
}

function launch(path: string, mode: string): Child {
  return spawn(path, [mode], { stdio: ["pipe", "pipe", "ignore"], env: {}, cwd: dirname(path), windowsHide: true });
}
export async function verifyNativeHelper(options: Pick<NativeProcessDriverOptions, "helperPath" | "helperSha256">): Promise<void> {
  if (!isAbsolute(options.helperPath) || !/^[a-f0-9]{64}$/u.test(options.helperSha256)
    || await realpath(options.helperPath) !== options.helperPath) throw failure();
  const file = await open(options.helperPath, constants.O_RDONLY | constants.O_NOFOLLOW);
  const bytes = Buffer.alloc(65_536);
  try {
    const before = await file.stat();
    if (!before.isFile() || before.size < 1 || before.size > 134_217_728
      || (before.mode & 0o022) !== 0 || (before.mode & 0o111) === 0) throw failure();
    const hash = createHash("sha256");
    let length = 0;
    for (;;) {
      const { bytesRead } = await file.read(bytes, 0, bytes.length, null);
      if (!bytesRead) break;
      length += bytesRead;
      if (length > before.size) throw failure();
      hash.update(bytes.subarray(0, bytesRead)); bytes.fill(0);
    }
    const after = await lstat(options.helperPath);
    if (!after.isFile() || after.dev !== before.dev || after.ino !== before.ino || after.size !== before.size
      || after.mtimeMs !== before.mtimeMs || length !== before.size || hash.digest("hex") !== options.helperSha256) throw failure();
  } finally { bytes.fill(0); await file.close(); }
}
/** These two fixed helper modes never open an audio source. Only the explicit
 * permissions command may prompt. Cancellation terminates only that probe. */
export async function nativeHelperPermissions(options: Pick<NativeProcessDriverOptions,
  'enabled'|'helperPath'|'helperSha256'|'isSessionActive'>, request: boolean, signal?: AbortSignal): Promise<boolean> {
  requireMain();
  if (!options.enabled || signal?.aborted || !options.isSessionActive()) return false;
  await verifyNativeHelper(options);
  if (signal?.aborted || !options.isSessionActive()) return false;
  return await probe(options.helperPath, request, signal) && !signal?.aborted && options.isSessionActive();
}
async function probe(path: string, request = false, signal?: AbortSignal): Promise<boolean> {
  return await new Promise<boolean>(resolve => {
    const child = launch(path, request ? "--request-permissions-v1" : "--availability-v1"), decoder = new NativeProcessDecoder();
    let available: boolean | undefined;
    const cancel = (): void => { available = false; child.kill("SIGKILL"); };
    const timer = setTimeout(cancel, request ? 120_000 : DEADLINE_MS); // These modes never record.
    signal?.addEventListener('abort',cancel,{once:true});if(signal?.aborted)cancel();
    child.stdout.on("data", (bytes: Buffer) => {
      try {
        decoder.push(bytes, (kind, payload) => {
          const value = nativeMetadata(payload);
          if (kind !== 1 || available !== undefined || !exactKeys(value, ["type", "available"])
            || value.type !== "availability" || typeof value.available !== "boolean") throw failure();
          available = value.available;
        });
      } catch { available = false; child.kill("SIGKILL"); }
    });
    child.stdin.on("error", () => undefined);
    child.on("error", () => { available = false; });
    child.once("close", code => {
      clearTimeout(timer);
      signal?.removeEventListener('abort',cancel);
      try { decoder.finish(); } catch { available = false; }
      resolve(code === 0 && available === true);
    });
    child.stdin.end();
  });
}
function integer(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max;
}
function requireMain(): void {
  if (typeof process === "undefined" || !process.versions.node || typeof window !== "undefined"
    || "type" in process && process.type === "renderer") throw failure();
}
function failure(): Error { return new Error("desktop_native_process_failed"); }
function deferred<T>(): { promise: Promise<T>; resolve: (value: T | PromiseLike<T>) => void; reject: (error: Error) => void } {
  let resolve!: (value: T | PromiseLike<T>) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function deadline<T>(work: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try { return await Promise.race([work, new Promise<T>((_, reject) => { timer = setTimeout(() => { reject(failure()); }, DEADLINE_MS); })]); }
  finally { clearTimeout(timer); }
}
