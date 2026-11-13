import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AccountPublicLinks} from './AccountPublicLinks';

let host:HTMLDivElement,root:Root;

beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  host=document.createElement('div');
  document.body.append(host);
  root=createRoot(host);
});
afterEach(async()=>{
  await act(async()=>root.unmount());
  host.remove();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function links(){
  return [...host.querySelectorAll<HTMLAnchorElement>('.account-public-links a')];
}

it('renders Privacy Policy and Support with the configured cosmas.ai URLs on web',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://cosmas.ai/cosmabot/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','https://cosmas.ai/cosmabot/support');
  await act(async()=>root.render(<AccountPublicLinks/>));
  const [privacy,support]=links();
  expect(privacy?.textContent).toBe('Privacy Policy');
  expect(support?.textContent).toBe('Support');
  expect(privacy.href).toBe('https://cosmas.ai/cosmabot/privacy');
  expect(support.href).toBe('https://cosmas.ai/cosmabot/support');
  for(const link of [privacy,support]){
    expect(link.target).toBe('_blank');
    expect(link.rel).toBe('noopener noreferrer');
    expect(link.getAttribute('referrerpolicy')).toBe('no-referrer');
  }
});

it('shows configured links on the iPhone apple hosted client',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','apple');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://cosmas.ai/cosmabot/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','https://cosmas.ai/cosmabot/support');
  await act(async()=>root.render(<AccountPublicLinks/>));
  expect(links()).toHaveLength(2);
});

it('hides both links on the Mac desktop hosted client even when configured',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','desktop');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://cosmas.ai/cosmabot/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','https://cosmas.ai/cosmabot/support');
  await act(async()=>root.render(<AccountPublicLinks/>));
  expect(host.querySelector('.account-public-links')).toBeNull();
  expect(links()).toHaveLength(0);
});

it('hides both links when VITE_PRIVACY_POLICY_URL and VITE_SUPPORT_URL are unset',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL',undefined);
  vi.stubEnv('VITE_SUPPORT_URL',undefined);
  await act(async()=>root.render(<AccountPublicLinks/>));
  expect(host.querySelector('.account-public-links')).toBeNull();
  expect(links()).toHaveLength(0);
});

it('omits an individual link when only one URL is valid',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://cosmas.ai/cosmabot/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','javascript:alert(1)');
  await act(async()=>root.render(<AccountPublicLinks/>));
  const shown=links();
  expect(shown).toHaveLength(1);
  expect(shown[0].textContent).toBe('Privacy Policy');
  expect(shown[0].href).toBe('https://cosmas.ai/cosmabot/privacy');
});
