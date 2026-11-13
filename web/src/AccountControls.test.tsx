import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AccountControls} from './AccountControls';
import {ACCOUNT_DELETE_CONFIRM,accountDeletionApi} from './account-deletion-api';

vi.mock('./account-deletion-api',async original=>{
  const module=await original<typeof import('./account-deletion-api')>();
  return {...module,accountDeletionApi:{deleteAccount:vi.fn()}};
});

let host:HTMLDivElement,root:Root;
const identity={mode:'clerk_jwt' as const,getToken:async()=>'a.b.c'};
const buttons=()=>[...host.querySelectorAll<HTMLButtonElement>('button')].filter(b=>!b.closest('[hidden]'));
async function click(name:string){
  const b=buttons().find(b=>b.textContent===name||b.textContent?.includes(name));
  expect(b,`Visible ${name}`).toBeTruthy();
  expect(b!.disabled).toBe(false);
  await act(async()=>b!.click());
}
function publicLinks(){
  return [...host.querySelectorAll<HTMLAnchorElement>('[aria-label="Account"] .account-public-links a')];
}

beforeEach(()=>{
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  host=document.createElement('div');
  document.body.append(host);
  root=createRoot(host);
  vi.mocked(accountDeletionApi.deleteAccount).mockReset();
});
afterEach(async()=>{
  await act(async()=>root.unmount());
  host.remove();
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it('shows Privacy Policy and Support with configured URLs on the Account screen',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL','https://cosmas.ai/cosmabot/privacy');
  vi.stubEnv('VITE_SUPPORT_URL','https://cosmas.ai/cosmabot/support');
  await act(async()=>root.render(<AccountControls identity={identity} onSignOut={vi.fn()}/>));
  const [privacy,support]=publicLinks();
  expect(privacy?.textContent).toBe('Privacy Policy');
  expect(support?.textContent).toBe('Support');
  expect(privacy.href).toBe('https://cosmas.ai/cosmabot/privacy');
  expect(support.href).toBe('https://cosmas.ai/cosmabot/support');
  expect(privacy.target).toBe('_blank');
  expect(privacy.rel).toBe('noopener noreferrer');
  expect(support.target).toBe('_blank');
  expect(support.rel).toBe('noopener noreferrer');
});

it('hides Privacy Policy and Support on the Account screen when config is unset',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');
  vi.stubEnv('VITE_PRIVACY_POLICY_URL',undefined);
  vi.stubEnv('VITE_SUPPORT_URL',undefined);
  await act(async()=>root.render(<AccountControls identity={identity} onSignOut={vi.fn()}/>));
  expect(publicLinks()).toHaveLength(0);
  expect(host.querySelector('[aria-label="Account"]')?.textContent).toContain('Log out');
});

it('shows Delete account in Account controls and Cancel leaves everything untouched',async()=>{
  const signOut=vi.fn(),clearNative=vi.fn();
  await act(async()=>root.render(<AccountControls identity={identity} onSignOut={signOut} clearNativeCredentials={clearNative}/>));
  expect(host.querySelector('[aria-label="Account"]')?.textContent).toContain('Delete account');
  expect(host.querySelector('[aria-label="Account"]')?.textContent).toContain('Log out');
  await click('Delete account');
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain('Delete your account?');
  await click('Cancel');
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(accountDeletionApi.deleteAccount).not.toHaveBeenCalled();
  expect(signOut).not.toHaveBeenCalled();
  expect(clearNative).not.toHaveBeenCalled();
});

it('confirm deletes the account, clears native credentials, and ends the session',async()=>{
  const signOut=vi.fn(),clearNative=vi.fn(async()=>{});
  vi.mocked(accountDeletionApi.deleteAccount).mockResolvedValue({status:'deleted'});
  await act(async()=>root.render(<AccountControls identity={identity} onSignOut={signOut} clearNativeCredentials={clearNative}/>));
  await click('Delete account');
  const confirm=[...host.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find(b=>b.textContent==='Delete account');
  expect(confirm).toBeTruthy();
  await act(async()=>confirm!.click());
  expect(accountDeletionApi.deleteAccount).toHaveBeenCalledWith(identity,ACCOUNT_DELETE_CONFIRM);
  expect(clearNative).toHaveBeenCalledOnce();
  expect(signOut).not.toHaveBeenCalled();
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});

it('keeps Log out independent of deletion',async()=>{
  const signOut=vi.fn();
  await act(async()=>root.render(<AccountControls identity={identity} onSignOut={signOut}/>));
  await click('Log out');
  expect(signOut).toHaveBeenCalledOnce();
  expect(accountDeletionApi.deleteAccount).not.toHaveBeenCalled();
});
