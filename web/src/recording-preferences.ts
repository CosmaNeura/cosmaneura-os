import type { CaptureLanguage } from './capture-api';

export type RecordingPreferences = { regions: string; language: CaptureLanguage; captureMode?: 'microphone' | 'desktop_meeting' };
const empty: RecordingPreferences = { regions: '', language: 'en-US' };
export function recordingRegions(value: string): string[] | null {
  const regions = value.split(',').map(part => part.trim().toUpperCase()).filter(Boolean);
  return regions.length > 0 && regions.length <= 16 && new Set(regions).size === regions.length &&
    regions.every(region => /^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$/.test(region)) ? regions : null;
}
function key(scope?: string): string | null {
  return scope && /^[a-f0-9]{64}$/.test(scope) ? `cosmas.recording-preferences.v1.${scope}` : null;
}
/** Only location, language and source defaults. Never retain consent, windows or visit data. */
export function readRecordingPreferences(scope?: string): RecordingPreferences {
  try {
    const address = key(scope);
    if (!address) return { ...empty };
    const value: unknown = JSON.parse(localStorage.getItem(address) ?? 'null');
    if (!value || typeof value !== 'object' || !('regions' in value) || !('language' in value) ||
      typeof value.regions !== 'string' || !recordingRegions(value.regions) ||
      !['en-US', 'en-US+es-US'].includes(String(value.language))) return { ...empty };
    return { regions: recordingRegions(value.regions)!.join(', '), language: value.language as CaptureLanguage,
      ...('captureMode' in value && (value.captureMode === 'microphone' || value.captureMode === 'desktop_meeting')
        ? {captureMode: value.captureMode} : {}) };
  } catch { return { ...empty }; }
}
export function readPrivateRecordingLanguage(scope: string): CaptureLanguage {
  try {
    const address = key(scope), value = address && localStorage.getItem(address + '.private-language');
    if (value === 'en-US' || value === 'en-US+es-US') return value;
  } catch { /* Preferences never block recording. */ }
  return readRecordingPreferences(scope).language;
}
/** Private recording remembers language only; no location or consent is inferred. */
export function savePrivateRecordingLanguage(scope: string, language: CaptureLanguage): void {
  try {
    const address = key(scope);
    if (address && ['en-US', 'en-US+es-US'].includes(language)) localStorage.setItem(address + '.private-language', language);
  } catch { /* Preferences never block recording. */ }
}
export function saveRecordingPreferences(scope: string | undefined, preferences: RecordingPreferences): void {
  try {
    const address = key(scope), regions = recordingRegions(preferences.regions);
    if (address && regions) localStorage.setItem(address, JSON.stringify({ regions: regions.join(', '), language: preferences.language,
      ...(['microphone', 'desktop_meeting'].includes(preferences.captureMode ?? '') ? {captureMode: preferences.captureMode} : {}) }));
  } catch { /* A device that disallows preferences still supports recording. */ }
}
