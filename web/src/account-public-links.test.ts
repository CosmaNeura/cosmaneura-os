import {afterEach,expect,it,vi} from 'vitest';
import {ACCOUNT_PUBLIC_URL_KEYS,validAccountPublicUrl} from '../../clients/shared/account-public-url.mjs';
import {
  accountPublicLinksHiddenOnClient,
  privacyPolicyUrl,
  supportUrl,
} from './account-public-links';

afterEach(()=>{
  vi.unstubAllEnvs();
});

it('exports the shared Account public URL keys for build pass-through',()=>{
  expect([...ACCOUNT_PUBLIC_URL_KEYS]).toEqual(['VITE_PRIVACY_POLICY_URL','VITE_SUPPORT_URL']);
});

it('accepts https URLs on host cosmas.ai without credentials or port',()=>{
  expect(validAccountPublicUrl('https://cosmas.ai/cosmabot/privacy')).toBe('https://cosmas.ai/cosmabot/privacy');
  expect(validAccountPublicUrl(' https://cosmas.ai/cosmabot/support ')).toBe('https://cosmas.ai/cosmabot/support');
});

it('accepts uppercase https cosmas.ai URLs after URL normalization',()=>{
  expect(validAccountPublicUrl('HTTPS://COSMAS.AI/cosmabot/privacy')).toBe('https://cosmas.ai/cosmabot/privacy');
});

it.each([
  'javascript:alert(1)',
  'data:text/html,hi',
  'http://cosmas.ai/cosmabot/privacy',
  'cosmas.ai/cosmabot/privacy',
  '//cosmas.ai/cosmabot/privacy',
  'https://user:pass@cosmas.ai/cosmabot/privacy',
  'https://user@cosmas.ai/cosmabot/privacy',
  'https://evil.example/privacy',
  'https://www.cosmas.ai/privacy',
  'https://cosmas.ai.evil.example/privacy',
  'https://evilcosmas.ai/privacy',
  'https://cosmas.ai./privacy',
  'https://cosmas.ai:8443/privacy',
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
