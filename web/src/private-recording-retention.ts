/** Pure 48-hour private-recording AUDIO retention. Default off; audio only. */

export const AUDIO_RETENTION_HOURS = 48;
export const AUDIO_RETENTION_WARN_HOURS = 36;
export const AUDIO_RETENTION_MS = AUDIO_RETENTION_HOURS * 60 * 60 * 1000;
export const AUDIO_RETENTION_WARN_MS = AUDIO_RETENTION_WARN_HOURS * 60 * 60 * 1000;
export const AUDIO_RETENTION_CLOCK_SKEW_MS = 5 * 60 * 1000;

export const AUDIO_TOMBSTONE_CONTRACT = 'cosmabot.private-recording-audio-tombstone.v1';
export const AUDIO_DELETED_STUB_CONTRACT = 'cosmabot.private-recording-audio-deleted.v1';
export const AUDIO_RETENTION_ARMED_CONTRACT = 'cosmabot.private-recording-audio-retention-armed.v1';
export const AUDIO_RETENTION_ARMED_KEY = 'audio-retention-armed';
/** Exact user-facing copy when device audio was removed; transcript/notes remain. */
export const AUDIO_DELETED_USER_MESSAGE = 'Audio deleted on this device; transcript and notes kept.';

export type AudioRetentionClock = () => number;
export type AudioRetentionPolicy = {
  enabled: boolean;
  hours?: number;
  warnHours?: number;
  enabledAt?: string | null;
  serverNow?: string | null;
  /** Device Date.now() when serverNow was fetched; used for stable clock offset. */
  fetchedAtDeviceMs?: number | null;
  /** First time this device armed retention (local stamp). */
  deviceArmedAt?: string | null;
};

/** Stable switches-off policy for parents that do not yet hold a live retention bag. */
export const AUDIO_RETENTION_OFF: AudioRetentionPolicy = {enabled: false};

export type AudioRetentionManifestLike = {
  recordingId: string;
  phase: string;
  endedAt?: string | null;
  updatedAt: string;
  chunks: {sequence: number}[];
};

export type AudioRetentionStore = {
  keys(): Promise<string[]>;
  read(key: string): Promise<unknown | null>;
  write(key: string, expected: unknown | null, value: unknown): Promise<void>;
  delete(key: string): Promise<void>;
};

export type AudioRetentionAnchor = {
  deadlineMs: number;
  warnMs: number;
  remainingMs: number;
  warn: boolean;
  expired: boolean;
};

export type AudioTombstone = {
  contract: typeof AUDIO_TOMBSTONE_CONTRACT;
  recordingId: string;
  deletedAt: string;
  outcome: 'deleted' | 'failed';
};

export type AudioDeletedStub = {
  contract: typeof AUDIO_DELETED_STUB_CONTRACT;
  recordingId: string;
  scope: string;
  phase: 'audio_deleted';
  updatedAt: string;
};

export type AudioRetentionArmed = {
  contract: typeof AUDIO_RETENTION_ARMED_CONTRACT;
  armedAt: string;
};

const ACTIVE = new Set(['starting', 'recording', 'pausing', 'stopping']);

function parseIsoMs(value: unknown): number | null {
  if (typeof value !== 'string' || value.length === 0) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

function optionalFiniteHours(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return undefined;
  return value;
}

function optionalIso(value: unknown): string | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  if (typeof value !== 'string') return null;
  return value;
}

/**
 * Map camelCase or snake_case policy payloads. Absent/invalid raw → null.
 * Non-true `enabled` → `{enabled: false}` (off).
 * When enabled from server, hours are pinned to 48 and `fetchedAtDeviceMs` is stamped.
 */
export function normalizeAudioRetentionPolicy(
  raw: unknown,
  nowMs: number = Date.now(),
): AudioRetentionPolicy | null {
  if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  if (o.enabled !== true) return {enabled: false};
  const warnHours = optionalFiniteHours(o.warnHours ?? o.warn_hours);
  const enabledAt = optionalIso(o.enabledAt ?? o.enabled_at);
  const serverNow = optionalIso(o.serverNow ?? o.server_now);
  const deviceArmedAt = optionalIso(o.deviceArmedAt ?? o.device_armed_at);
  const policy: AudioRetentionPolicy = {
    enabled: true,
    hours: AUDIO_RETENTION_HOURS,
    fetchedAtDeviceMs: nowMs,
  };
  if (warnHours !== undefined) policy.warnHours = warnHours;
  if (enabledAt !== undefined) policy.enabledAt = enabledAt;
  if (serverNow !== undefined) policy.serverNow = serverNow;
  if (deviceArmedAt !== undefined) policy.deviceArmedAt = deviceArmedAt;
  return policy;
}

/** Absent, unknown, or disabled policy means no deletion and no label. */
export function audioRetentionEffective(policy: AudioRetentionPolicy | null | undefined): boolean {
  return policy?.enabled === true;
}

/** Fail closed: enabled without a usable enabledAt is off for delete/label/refuse. */
export function audioRetentionEnabledAtMs(policy: AudioRetentionPolicy | null | undefined): number | null {
  if (!audioRetentionEffective(policy)) return null;
  return parseIsoMs(policy?.enabledAt);
}

type RetentionClockResolution = {
  effectiveNowMs: number;
  allowDelete: boolean;
};

/**
 * Missing serverNow or fetchedAtDeviceMs → no delete / no expired refuse; labels use device now.
 * Skew at fetch (|serverNow − fetchedAtDeviceMs| > 5 min) → same refuse.
 * Otherwise effectiveNow = nowMs + (serverNowMs − fetchedAtDeviceMs) so the clock tracks after fetch.
 */
export function resolveAudioRetentionClock(
  policy: AudioRetentionPolicy | null | undefined,
  nowMs: number,
): RetentionClockResolution {
  const serverNowMs = parseIsoMs(policy?.serverNow);
  if (serverNowMs === null) return {effectiveNowMs: nowMs, allowDelete: false};
  const fetchedAt = policy?.fetchedAtDeviceMs;
  if (typeof fetchedAt !== 'number' || !Number.isFinite(fetchedAt)) {
    return {effectiveNowMs: nowMs, allowDelete: false};
  }
  const offsetMs = serverNowMs - fetchedAt;
  if (Math.abs(offsetMs) > AUDIO_RETENTION_CLOCK_SKEW_MS) {
    return {effectiveNowMs: nowMs, allowDelete: false};
  }
  return {effectiveNowMs: nowMs + offsetMs, allowDelete: true};
}

/** Read a valid armedAt from the store, or null when missing/malformed. */
export async function readDeviceArmedAt(store: AudioRetentionStore): Promise<string | null> {
  const prior = await store.read(AUDIO_RETENTION_ARMED_KEY);
  if (prior && typeof prior === 'object' && !Array.isArray(prior)) {
    const o = prior as Record<string, unknown>;
    if (
      o.contract === AUDIO_RETENTION_ARMED_CONTRACT
      && typeof o.armedAt === 'string'
      && parseIsoMs(o.armedAt) !== null
    ) {
      return o.armedAt;
    }
  }
  return null;
}

/** Clear the device armed stamp (kill-switch / policy-off rollback). */
export async function clearDeviceArmedAt(store: AudioRetentionStore): Promise<void> {
  try {
    await store.delete(AUDIO_RETENTION_ARMED_KEY);
  } catch {
    /* best-effort clear */
  }
}

/**
 * Read existing device armed stamp, or write once. Never moves armedAt later.
 * Caller must pass effectiveNowMs and only invoke when allowDelete is true.
 * Key `audio-retention-armed` holds `{contract, armedAt}` only (no title).
 */
export async function readOrStampDeviceArmedAt(
  store: AudioRetentionStore,
  effectiveNowMs: number,
): Promise<string> {
  const existing = await readDeviceArmedAt(store);
  if (existing !== null) return existing;
  const prior = await store.read(AUDIO_RETENTION_ARMED_KEY);
  const armedAt = new Date(effectiveNowMs).toISOString();
  const next: AudioRetentionArmed = {contract: AUDIO_RETENTION_ARMED_CONTRACT, armedAt};
  await store.write(AUDIO_RETENTION_ARMED_KEY, prior, next);
  return armedAt;
}

/**
 * Resolve armed policy once per store so label, refuse, and sweep agree.
 * Not effective (null/undefined/off/missing enabledAt) → return policy unchanged;
 * no store read or delete (identical to main with switches off).
 * On-path: stamp only when allowDelete using effectiveNowMs; restamp when the
 * stored armedAt is older than policy.enabledAt so re-enable gets a fresh grace.
 */
export async function resolveArmedAudioRetentionPolicy(
  store: AudioRetentionStore,
  policy: AudioRetentionPolicy | null | undefined,
  nowMs: number,
): Promise<AudioRetentionPolicy | null | undefined> {
  // Switches off / unknown — identical to main: touch nothing.
  if (!audioRetentionEffective(policy) || !policy) return policy;
  const enabledAtMs = audioRetentionEnabledAtMs(policy);
  if (enabledAtMs === null) return policy;
  const clock = resolveAudioRetentionClock(policy, nowMs);
  if (!clock.allowDelete) {
    const existing = await readDeviceArmedAt(store);
    return existing ? {...policy, deviceArmedAt: existing} : policy;
  }
  const existing = await readDeviceArmedAt(store);
  const existingMs = existing ? parseIsoMs(existing) : null;
  // Re-enable after a later enabledAt: discard stale armedAt and stamp fresh.
  // Only when enabledAt is not in the future — never move armedAt later on a future enabledAt.
  if (existing !== null && existingMs !== null && existingMs < enabledAtMs) {
    if (enabledAtMs > clock.effectiveNowMs) {
      return {...policy, deviceArmedAt: existing};
    }
    await clearDeviceArmedAt(store);
  } else if (existing !== null && existingMs !== null && existingMs >= enabledAtMs) {
    return {...policy, deviceArmedAt: existing};
  }
  const deviceArmedAt = await readOrStampDeviceArmedAt(store, clock.effectiveNowMs);
  return {...policy, deviceArmedAt};
}

/** Sweepable only with usable enabledAt and a stamped deviceArmedAt (device grace). */
export function audioRetentionSweepable(policy: AudioRetentionPolicy | null | undefined): boolean {
  return audioRetentionEnabledAtMs(policy) !== null && parseIsoMs(policy?.deviceArmedAt) !== null;
}

export function audioRetentionAnchor(
  manifest: AudioRetentionManifestLike,
  nowMs: number,
  policy: AudioRetentionPolicy | null | undefined = {enabled: true},
): AudioRetentionAnchor | null {
  if (!audioRetentionEffective(policy)) return null;
  const enabledAtMs = audioRetentionEnabledAtMs(policy);
  if (enabledAtMs === null) return null;
  const hours = policy?.hours ?? AUDIO_RETENTION_HOURS;
  const warnHours = policy?.warnHours ?? AUDIO_RETENTION_WARN_HOURS;
  const retentionMs = hours * 60 * 60 * 1000;
  const warnAfterMs = warnHours * 60 * 60 * 1000;
  const raw = typeof manifest.endedAt === 'string' && manifest.endedAt.length > 0
    ? manifest.endedAt
    : manifest.updatedAt;
  const anchorMs = Date.parse(raw);
  if (!Number.isFinite(anchorMs)) return null;
  const deviceArmedAtMs = parseIsoMs(policy?.deviceArmedAt);
  const start = Math.max(anchorMs, enabledAtMs, deviceArmedAtMs ?? enabledAtMs);
  const deadlineMs = start + retentionMs;
  const remainingMs = deadlineMs - nowMs;
  return {
    deadlineMs,
    warnMs: start + warnAfterMs,
    remainingMs,
    warn: remainingMs > 0 && remainingMs <= (retentionMs - warnAfterMs),
    expired: remainingMs <= 0,
  };
}

/** Human countdown. Only when retention is effective and enabledAt is usable. */
export function audioRetentionLabel(
  manifest: AudioRetentionManifestLike,
  nowMs: number,
  policy: AudioRetentionPolicy | null | undefined,
): {text: string; warn: boolean} | null {
  const clock = resolveAudioRetentionClock(policy, nowMs);
  const anchor = audioRetentionAnchor(manifest, clock.effectiveNowMs, policy);
  if (!anchor || anchor.expired) return null;
  const hours = Math.max(1, Math.ceil(anchor.remainingMs / (60 * 60 * 1000)));
  return {
    text: `Audio is removed from this device about ${hours} h from now; transcript and notes are kept.`,
    warn: anchor.warn,
  };
}

export function isActiveRecordingPhase(phase: string): boolean {
  return ACTIVE.has(phase);
}

export function buildAudioTombstone(
  recordingId: string,
  deletedAtIso: string,
  outcome: 'deleted' | 'failed',
): AudioTombstone {
  return {
    contract: AUDIO_TOMBSTONE_CONTRACT,
    recordingId,
    deletedAt: deletedAtIso,
    outcome,
  };
}

export function buildAudioDeletedStub(
  recordingId: string,
  scope: string,
  updatedAtIso: string,
): AudioDeletedStub {
  return {
    contract: AUDIO_DELETED_STUB_CONTRACT,
    recordingId,
    scope,
    phase: 'audio_deleted',
    updatedAt: updatedAtIso,
  };
}

/**
 * Delete audio chunks then the audio manifest. Never touches ledger, transcript,
 * visit-binding, transfer, or display-title keys. Crash mid-delete then retry
 * finishes without resurrecting chunks.
 * When `scope` is provided, writes the audio-deleted stub before removing the manifest.
 */
export async function deletePrivateRecordingAudio(
  store: AudioRetentionStore,
  recordingId: string,
  chunkCountHint?: number,
  options?: {scope?: string; deletedAtIso?: string},
): Promise<void> {
  const prefix = `chunk:${recordingId}:`;
  const keys = (await store.keys()).filter((key) => key === `manifest:${recordingId}` || key.startsWith(prefix));
  const chunks = keys
    .filter((key) => key.startsWith(prefix))
    .sort((a, b) => Number(a.slice(prefix.length)) - Number(b.slice(prefix.length)));
  const known = Number.isSafeInteger(chunkCountHint) ? Math.max(0, chunkCountHint!) : 0;
  for (let sequence = 0; sequence < known; sequence++) {
    const key = prefix + sequence;
    if (!chunks.includes(key)) continue;
    await store.delete(key);
  }
  for (const key of chunks) await store.delete(key);
  if (options?.scope) {
    const stubKey = `audio-deleted:${recordingId}`;
    const prior = await store.read(stubKey);
    const iso = options.deletedAtIso ?? new Date().toISOString();
    await store.write(stubKey, prior, buildAudioDeletedStub(recordingId, options.scope, iso));
  }
  if (keys.includes(`manifest:${recordingId}`) || (await store.read(`manifest:${recordingId}`)) !== null) {
    await store.delete(`manifest:${recordingId}`);
  }
}

export type SweepPrivateRecordingAudioOptions = {
  store: AudioRetentionStore;
  scope: string;
  policy: AudioRetentionPolicy | null | undefined;
  now: AudioRetentionClock;
  /** Stop and seal an in-progress recording that hit its deadline before delete. */
  sealInProgress?: (recordingId: string) => Promise<AudioRetentionManifestLike | null>;
  parseManifest: (value: unknown, recordingId: string) => AudioRetentionManifestLike;
  /** Skip a recording (e.g. already tombstoned). */
  shouldSkipRecording?: (recordingId: string, manifest: AudioRetentionManifestLike) => boolean;
  /** Per-recording failure hook; one poison row must not abort the sweep. */
  recordFailure?: (recordingId: string, error: unknown) => void;
  /** After a successful audio delete — write tombstone (stub is written before manifest delete). */
  onDeleted?: (recordingId: string) => void | Promise<void>;
};

export type SweepPrivateRecordingAudioResult = {
  deleted: string[];
  inspected: number;
};

/** Idempotent sweep for one store/scope. No-op when policy is off. */
export async function sweepPrivateRecordingAudio(
  options: SweepPrivateRecordingAudioOptions,
): Promise<SweepPrivateRecordingAudioResult> {
  if (!audioRetentionEffective(options.policy)) return {deleted: [], inspected: 0};
  if (audioRetentionEnabledAtMs(options.policy) === null) return {deleted: [], inspected: 0};
  // Enabled without deviceArmedAt is not sweepable (no device grace) — list/sweep agree.
  if (!audioRetentionSweepable(options.policy)) return {deleted: [], inspected: 0};
  const nowMs = options.now();
  const clock = resolveAudioRetentionClock(options.policy, nowMs);
  if (!clock.allowDelete) return {deleted: [], inspected: 0};
  const effectiveNowMs = clock.effectiveNowMs;
  const keys = (await options.store.keys()).filter((key) => key.startsWith('manifest:'));
  const deleted: string[] = [];
  const deletedAtIso = new Date(nowMs).toISOString();
  for (const key of keys) {
    const recordingId = key.slice('manifest:'.length);
    try {
      let raw = await options.store.read(key);
      if (raw === null) continue;
      let manifest = options.parseManifest(raw, recordingId);
      if (manifest.recordingId !== recordingId) continue;
      if (options.shouldSkipRecording?.(recordingId, manifest)) continue;
      let anchor = audioRetentionAnchor(manifest, effectiveNowMs, options.policy);
      if (!anchor?.expired) continue;
      if (isActiveRecordingPhase(manifest.phase)) {
        const sealed = options.sealInProgress ? await options.sealInProgress(recordingId) : null;
        if (!sealed) continue;
        manifest = sealed;
        anchor = audioRetentionAnchor(manifest, effectiveNowMs, options.policy);
        if (!anchor?.expired) continue;
      }
      await deletePrivateRecordingAudio(options.store, recordingId, manifest.chunks.length, {
        scope: options.scope,
        deletedAtIso,
      });
      deleted.push(recordingId);
      await options.onDeleted?.(recordingId);
    } catch (error) {
      options.recordFailure?.(recordingId, error);
    }
  }
  return {deleted, inspected: keys.length};
}

export const EXPIRED_AUDIO_REFUSED = 'private_recording_audio_expired';

export function refuseExpiredAudio(
  manifest: AudioRetentionManifestLike,
  nowMs: number,
  policy: AudioRetentionPolicy | null | undefined,
  options?: {skip?: boolean},
): void {
  if (options?.skip) return;
  const clock = resolveAudioRetentionClock(policy, nowMs);
  if (!clock.allowDelete) return;
  const anchor = audioRetentionAnchor(manifest, clock.effectiveNowMs, policy);
  if (anchor?.expired) {
    throw Object.assign(new Error(AUDIO_DELETED_USER_MESSAGE), {code: EXPIRED_AUDIO_REFUSED});
  }
}
