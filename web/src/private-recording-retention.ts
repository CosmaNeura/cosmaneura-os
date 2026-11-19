/** Pure 48-hour private-recording AUDIO retention. Default off; audio only. */

export const AUDIO_RETENTION_HOURS = 48;
export const AUDIO_RETENTION_WARN_HOURS = 36;
export const AUDIO_RETENTION_MS = AUDIO_RETENTION_HOURS * 60 * 60 * 1000;
export const AUDIO_RETENTION_WARN_MS = AUDIO_RETENTION_WARN_HOURS * 60 * 60 * 1000;

export type AudioRetentionClock = () => number;
export type AudioRetentionPolicy = {
  enabled: boolean;
  hours?: number;
  warnHours?: number;
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

const ACTIVE = new Set(['starting', 'recording', 'pausing', 'stopping']);

/** Absent, unknown, or disabled policy means no deletion and no label. */
export function audioRetentionEffective(policy: AudioRetentionPolicy | null | undefined): boolean {
  return policy?.enabled === true;
}

export function audioRetentionAnchor(
  manifest: AudioRetentionManifestLike,
  nowMs: number,
  policy: AudioRetentionPolicy | null | undefined = {enabled: true},
): AudioRetentionAnchor | null {
  if (!audioRetentionEffective(policy)) return null;
  const hours = policy?.hours ?? AUDIO_RETENTION_HOURS;
  const warnHours = policy?.warnHours ?? AUDIO_RETENTION_WARN_HOURS;
  const retentionMs = hours * 60 * 60 * 1000;
  const warnAfterMs = warnHours * 60 * 60 * 1000;
  const raw = typeof manifest.endedAt === 'string' && manifest.endedAt.length > 0
    ? manifest.endedAt
    : manifest.updatedAt;
  const start = Date.parse(raw);
  if (!Number.isFinite(start)) return null;
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

/** Human label like "deletes in 12 h". Only when retention is effective. */
export function audioRetentionLabel(
  manifest: AudioRetentionManifestLike,
  nowMs: number,
  policy: AudioRetentionPolicy | null | undefined,
): {text: string; warn: boolean} | null {
  const anchor = audioRetentionAnchor(manifest, nowMs, policy);
  if (!anchor || anchor.expired) return null;
  const hours = Math.max(1, Math.ceil(anchor.remainingMs / (60 * 60 * 1000)));
  return {text: `deletes in ${hours} h`, warn: anchor.warn};
}

export function isActiveRecordingPhase(phase: string): boolean {
  return ACTIVE.has(phase);
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
  const nowMs = options.now();
  const keys = (await options.store.keys()).filter((key) => key.startsWith('manifest:'));
  const deleted: string[] = [];
  for (const key of keys) {
    const recordingId = key.slice('manifest:'.length);
    let raw = await options.store.read(key);
    if (raw === null) continue;
    let manifest = options.parseManifest(raw, recordingId);
    if (manifest.recordingId !== recordingId) continue;
    let anchor = audioRetentionAnchor(manifest, nowMs, options.policy);
    if (!anchor?.expired) continue;
    if (isActiveRecordingPhase(manifest.phase)) {
      const sealed = await options.sealInProgress?.(recordingId);
      if (sealed) {
        manifest = sealed;
        anchor = audioRetentionAnchor(manifest, nowMs, options.policy);
        if (!anchor?.expired) continue;
      }
    }
    await deletePrivateRecordingAudio(options.store, recordingId, manifest.chunks.length);
    deleted.push(recordingId);
  }
  return {deleted, inspected: keys.length};
}

export const EXPIRED_AUDIO_REFUSED = 'private_recording_audio_expired';

export function refuseExpiredAudio(
  manifest: AudioRetentionManifestLike,
  nowMs: number,
  policy: AudioRetentionPolicy | null | undefined,
): void {
  const anchor = audioRetentionAnchor(manifest, nowMs, policy);
  if (anchor?.expired) {
    throw Object.assign(new Error('Private recording audio expired'), {code: EXPIRED_AUDIO_REFUSED});
  }
}
