/** Pure 48-hour private-recording AUDIO retention. Default off; audio only. */

export const AUDIO_RETENTION_HOURS = 48;
export const AUDIO_RETENTION_WARN_HOURS = 36;
export const AUDIO_RETENTION_MS = AUDIO_RETENTION_HOURS * 60 * 60 * 1000;
export const AUDIO_RETENTION_WARN_MS = AUDIO_RETENTION_WARN_HOURS * 60 * 60 * 1000;
export const AUDIO_RETENTION_CLOCK_SKEW_MS = 5 * 60 * 1000;

export const AUDIO_TOMBSTONE_CONTRACT = 'cosmabot.private-recording-audio-tombstone.v1';
export const AUDIO_DELETED_STUB_CONTRACT = 'cosmabot.private-recording-audio-deleted.v1';

export type AudioRetentionClock = () => number;
export type AudioRetentionPolicy = {
  enabled: boolean;
  hours?: number;
  warnHours?: number;
  enabledAt?: string | null;
  serverNow?: string | null;
};

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
 */
export function normalizeAudioRetentionPolicy(raw: unknown): AudioRetentionPolicy | null {
  if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  if (o.enabled !== true) return {enabled: false};
  const hours = optionalFiniteHours(o.hours);
  const warnHours = optionalFiniteHours(o.warnHours ?? o.warn_hours);
  const enabledAt = optionalIso(o.enabledAt ?? o.enabled_at);
  const serverNow = optionalIso(o.serverNow ?? o.server_now);
  const policy: AudioRetentionPolicy = {enabled: true};
  if (hours !== undefined) policy.hours = hours;
  if (warnHours !== undefined) policy.warnHours = warnHours;
  if (enabledAt !== undefined) policy.enabledAt = enabledAt;
  if (serverNow !== undefined) policy.serverNow = serverNow;
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
 * serverNow present + skew within bound → use server time and allow delete.
 * no serverNow → device now, allow delete.
 * skew over bound → no delete / no expired refuse; labels use device now.
 */
export function resolveAudioRetentionClock(
  policy: AudioRetentionPolicy | null | undefined,
  nowMs: number,
): RetentionClockResolution {
  const serverNowMs = parseIsoMs(policy?.serverNow);
  if (serverNowMs === null) return {effectiveNowMs: nowMs, allowDelete: true};
  if (Math.abs(nowMs - serverNowMs) > AUDIO_RETENTION_CLOCK_SKEW_MS) {
    return {effectiveNowMs: nowMs, allowDelete: false};
  }
  return {effectiveNowMs: serverNowMs, allowDelete: true};
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
  const start = Math.max(anchorMs, enabledAtMs);
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
 */
export async function deletePrivateRecordingAudio(
  store: AudioRetentionStore,
  recordingId: string,
  chunkCountHint?: number,
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
  /** After a successful audio delete — write tombstone + audio-deleted stub. */
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
  const nowMs = options.now();
  const clock = resolveAudioRetentionClock(options.policy, nowMs);
  if (!clock.allowDelete) return {deleted: [], inspected: 0};
  const effectiveNowMs = clock.effectiveNowMs;
  const keys = (await options.store.keys()).filter((key) => key.startsWith('manifest:'));
  const deleted: string[] = [];
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
      await deletePrivateRecordingAudio(options.store, recordingId, manifest.chunks.length);
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
): void {
  const clock = resolveAudioRetentionClock(policy, nowMs);
  if (!clock.allowDelete) return;
  const anchor = audioRetentionAnchor(manifest, clock.effectiveNowMs, policy);
  if (anchor?.expired) {
    throw Object.assign(new Error('Private recording audio expired'), {code: EXPIRED_AUDIO_REFUSED});
  }
}
