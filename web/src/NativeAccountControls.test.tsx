import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {NativeAccountControls} from './NativeAccountControls';
import {DEFAULT_PRIVACY_POLICY_URL,DEFAULT_SUPPORT_URL} from './account-public-links';

vi.mock('./unsaved-work',()=>({useUnsavedWorkPresent:()=>false}));
vi.mock('./account-deletion-api',async original=>{
  const module=await original<typeof import('./account-deletion-api')>();
  return {...module,accountDeletionApi:{deleteAccount:vi.fn()}};
});

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

function publicLinks(){
  return [...host.querySelectorAll<HTMLAnchorElement>('.native-account-controls .account-public-links a')];
}

it('shows Privacy Policy and Support with configured URLs in native Account controls',async()=>{
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://native.example.invalid/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','https://native.example.invalid/support');
  await act(async()=>root.render(<NativeAccountControls displayName="Alex Rivera" practiceName="Rivera Clinic" onSignOut={vi.fn()}/>));
  const [privacy,support]=publicLinks();
  expect(privacy?.textContent).toBe('Privacy Policy');
  expect(support?.textContent).toBe('Support');
  expect(privacy.href).toBe('https://native.example.invalid/privacy');
  expect(support.href).toBe('https://native.example.invalid/support');
  expect(privacy.target).toBe('_blank');
  expect(privacy.rel).toBe('noopener noreferrer');
  expect(support.rel).toBe('noopener noreferrer');
});

it('falls back to placeholder defaults in native Account controls when config is omitted',async()=>{
  vi.stubEnv('VITE_PRIVACY_POLICY_URL',undefined);
  vi.stubEnv('VITE_SUPPORT_URL',undefined);
  await act(async()=>root.render(<NativeAccountControls onSignOut={vi.fn()}/>));
  const [privacy,support]=publicLinks();
  expect(privacy.href).toBe(DEFAULT_PRIVACY_POLICY_URL);
  expect(support.href).toBe(DEFAULT_SUPPORT_URL);
});
