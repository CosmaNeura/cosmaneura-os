import {afterEach, expect, it} from 'vitest';
import {readRecordingPreferences, recordingRegions, saveRecordingPreferences} from './recording-preferences';
const owner = 'a'.repeat(64), other = 'b'.repeat(64);
afterEach(() => localStorage.clear());
it('remembers only explicit location and language choices in the current owner scope', () => {
  saveRecordingPreferences(owner, {regions:'us-ny, US-NJ',language:'en-US+es-US'});
  expect(readRecordingPreferences(owner)).toEqual({regions:'US-NY, US-NJ',language:'en-US+es-US'});
  expect(readRecordingPreferences(other)).toEqual({regions:'',language:'en-US'});
  const stored = JSON.parse(localStorage.getItem(localStorage.key(0)!)!);
  expect(Object.keys(stored).sort()).toEqual(['language','regions']);
});
it('rejects missing scope, malformed defaults, duplicated or invalid regions', () => {
  saveRecordingPreferences(undefined, {regions:'US-NY',language:'en-US'});
  expect(localStorage.length).toBe(0);
  for (const value of ['', 'US-NY,us-ny', 'New York', '<script>', 'US-NY,../../']) expect(recordingRegions(value)).toBeNull();
  localStorage.setItem(`cosmas.recording-preferences.v1.${owner}`, '{');
  expect(readRecordingPreferences(owner).regions).toBe('');
});
