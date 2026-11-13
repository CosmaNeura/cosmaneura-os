import {afterEach,expect,it,vi} from 'vitest';
import {
  DEFAULT_PRIVACY_POLICY_URL,
  DEFAULT_SUPPORT_URL,
  privacyPolicyUrl,
  supportUrl,
} from './account-public-links';

afterEach(()=>{
  vi.unstubAllEnvs();
});

it('pins the clearly marked placeholder defaults until John publishes final URLs',()=>{
  expect(DEFAULT_PRIVACY_POLICY_URL).toBe('https://cosmas.ai/privacy');
  expect(DEFAULT_SUPPORT_URL).toBe('https://cosmas.ai/support');
});

it('falls back to placeholder defaults when config keys are omitted or blank',()=>{
  vi.stubEnv('VITE_PRIVACY_POLICY_URL',undefined);
  vi.stubEnv('VITE_SUPPORT_URL','');
  expect(privacyPolicyUrl()).toBe(DEFAULT_PRIVACY_POLICY_URL);
  expect(supportUrl()).toBe(DEFAULT_SUPPORT_URL);
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','   ');
  expect(privacyPolicyUrl()).toBe(DEFAULT_PRIVACY_POLICY_URL);
});

it('uses configured VITE_PRIVACY_POLICY_URL and VITE_SUPPORT_URL when set',()=>{
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://example.invalid/privacy-policy');
  vi.stubEnv('VITE_SUPPORT_URL','https://example.invalid/help');
  expect(privacyPolicyUrl()).toBe('https://example.invalid/privacy-policy');
  expect(supportUrl()).toBe('https://example.invalid/help');
});
