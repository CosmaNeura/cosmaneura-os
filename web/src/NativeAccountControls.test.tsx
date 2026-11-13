import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {NativeAccountControls} from './NativeAccountControls';

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
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','apple');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://cosmas.ai/cosmabot/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','https://cosmas.ai/cosmabot/support');
  await act(async()=>root.render(<NativeAccountControls displayName="Alex Rivera" practiceName="Rivera Clinic" onSignOut={vi.fn()}/>));
  const [privacy,support]=publicLinks();
  expect(privacy?.textContent).toBe('Privacy Policy');
  expect(support?.textContent).toBe('Support');
  expect(privacy.href).toBe('https://cosmas.ai/cosmabot/privacy');
  expect(support.href).toBe('https://cosmas.ai/cosmabot/support');
  expect(privacy.target).toBe('_blank');
  expect(privacy.rel).toBe('noopener noreferrer');
  expect(support.rel).toBe('noopener noreferrer');
});

it('hides Privacy Policy and Support in native Account controls when config is unset',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','apple');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL',undefined);
  vi.stubEnv('VITE_SUPPORT_URL',undefined);
  await act(async()=>root.render(<NativeAccountControls onSignOut={vi.fn()}/>));
  expect(publicLinks()).toHaveLength(0);
});
