import {afterEach,expect,it,vi} from 'vitest';
import {
  accountPublicLinksHiddenOnClient,
  privacyPolicyUrl,
  supportUrl,
  validAccountPublicUrl,
} from './account-public-links';

afterEach(()=>{
  vi.unstubAllEnvs();
});

it('accepts https URLs on host cosmas.ai without credentials',()=>{
  expect(validAccountPublicUrl('https://cosmas.ai/cosmabot/privacy')).toBe('https://cosmas.ai/cosmabot/privacy');
  expect(validAccountPublicUrl(' https://cosmas.ai/cosmabot/support ')).toBe('https://cosmas.ai/cosmabot/support');
});

it.each([
  'javascript:alert(1)',
  'data:text/html,hi',
  'http://cosmas.ai/cosmabot/privacy',
  'cosmas.ai/cosmabot/privacy',
  '//cosmas.ai/cosmabot/privacy',
  'https://user:pass@cosmas.ai/cosmabot/privacy',
  'https://evil.example/privacy',
  'https://www.cosmas.ai/privacy',
  'https://cosmas.ai.evil.example/privacy',
  '',
  '   ',
  undefined,
])('rejects invalid account public URL %s',value=>{
  expect(validAccountPublicUrl(value)).toBeNull();
});

it('returns null from privacyPolicyUrl and supportUrl when env is unset or blank',()=>{
  vi.stubEnv('VITE_PRIVACY_POLICY_URL',undefined);
  vi.stubEnv('VITE_SUPPORT_URL','');
  expect(privacyPolicyUrl()).toBeNull();
  expect(supportUrl()).toBeNull();
});

it('resolves configured VITE_PRIVACY_POLICY_URL and VITE_SUPPORT_URL when valid',()=>{
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://cosmas.ai/cosmabot/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','https://cosmas.ai/cosmabot/support');
  expect(privacyPolicyUrl()).toBe('https://cosmas.ai/cosmabot/privacy');
  expect(supportUrl()).toBe('https://cosmas.ai/cosmabot/support');
});

it('hides account public links only on the Mac desktop hosted client',()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','desktop');
  expect(accountPublicLinksHiddenOnClient()).toBe(true);
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','apple');
  expect(accountPublicLinksHiddenOnClient()).toBe(false);
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');
  expect(accountPublicLinksHiddenOnClient()).toBe(false);
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT',undefined);
  expect(accountPublicLinksHiddenOnClient()).toBe(false);
});
