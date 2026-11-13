import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AccountPublicLinks} from './AccountPublicLinks';
import {DEFAULT_PRIVACY_POLICY_URL,DEFAULT_SUPPORT_URL} from './account-public-links';

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

it('renders Privacy Policy and Support with the configured URLs',async()=>{
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://docs.example.invalid/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','https://docs.example.invalid/support');
  await act(async()=>root.render(<AccountPublicLinks/>));
  const [privacy,support]=links();
  expect(privacy?.textContent).toBe('Privacy Policy');
  expect(support?.textContent).toBe('Support');
  expect(privacy.href).toBe('https://docs.example.invalid/privacy');
  expect(support.href).toBe('https://docs.example.invalid/support');
  for(const link of [privacy,support]){
    expect(link.target).toBe('_blank');
    expect(link.rel).toBe('noopener noreferrer');
    expect(link.getAttribute('referrerpolicy')).toBe('no-referrer');
  }
});

it('falls back to placeholder defaults when config is omitted',async()=>{
  vi.stubEnv('VITE_PRIVACY_POLICY_URL',undefined);
  vi.stubEnv('VITE_SUPPORT_URL',undefined);
  await act(async()=>root.render(<AccountPublicLinks/>));
  const [privacy,support]=links();
  expect(privacy.href).toBe(DEFAULT_PRIVACY_POLICY_URL);
  expect(support.href).toBe(DEFAULT_SUPPORT_URL);
});
