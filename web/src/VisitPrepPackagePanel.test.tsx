import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from '../../tests/fixtures/visit-prep-ready.json';
import {VisitPrepPackagePanel} from './VisitPrepPackagePanel';
import {readVisitPrep} from './visit-prep-api';
import {validateVisitPrep,type VisitPrepReceipt} from './visit-prep-contract';
import {coreConnectionApi} from './core-connection-api';
import {workspaceApi} from './workspace-api';
vi.mock('./visit-prep-api',()=>({readVisitPrep:vi.fn()}));
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
vi.mock('./workspace-api',async original=>({...await original<object>(),workspaceApi:{team:vi.fn()}}));
const identity={mode:'clerk_jwt' as const,getToken:vi.fn()},crypto=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const value=()=>({...structuredClone(fixture),checked_at:new Date().toISOString()}) as VisitPrepReceipt;
beforeEach(()=>{
  vi.stubGlobal('crypto',crypto.webcrypto);Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  vi.mocked(workspaceApi.team).mockResolvedValue({revision:1,configuration:{bots:[{role:'visit_prep',enabled:true,include_evidence:true}]},
    members:[{role:'visit_prep',capabilities:[{key:'core.visit_prep.read',state:'enabled'}]}]} as never);
  vi.mocked(coreConnectionApi.read).mockResolvedValue({connection_status:'connected',discovery:{connection:{connection_sha256:fixture.connection_sha256}}} as never);
  vi.mocked(readVisitPrep).mockResolvedValue(value());
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
async function mount(locked=false){await act(async()=>root.render(<VisitPrepPackagePanel identity={identity} locked={locked}/>));}
async function select(){await act(async()=>{const input=host.querySelector('input')!;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,fixture.preparation_ref);
  input.dispatchEvent(new Event('input',{bubbles:true}));});}
async function open(){await act(async()=>[...host.querySelectorAll('button')].find(b=>b.textContent?.endsWith('patient preparation'))!.click());}
it('opens the actual patient story and cited interpretation only after explicit selection',async()=>{
  await mount();expect(readVisitPrep).not.toHaveBeenCalled();await select();await open();
  expect(host.textContent).toContain('Invented story: I changed my morning routine.');
  expect(host.textContent).toContain('AI-prepared interpretation');
  expect(host.textContent).toContain('No patient chart is linked');
  const citation=host.querySelector<HTMLButtonElement>('[aria-label="Show patient source"]')!;
  await act(async()=>citation.click());expect(document.activeElement?.textContent).toContain('Tell me what happened');
  await act(async()=>window.dispatchEvent(new Event('blur')));
  expect(host.textContent).not.toContain('Invented story');
});
it('clears and discards a late reply when permission changes',async()=>{
  let release!:(v:VisitPrepReceipt)=>void;vi.mocked(readVisitPrep).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  await mount();await select();await open();await mount(true);await act(async()=>release(value()));
  expect(host.textContent).not.toContain('Invented story');
});
it('validates the closed contract and rejects stale content rather than showing a previous brief',()=>{
  const receipt=value(),command={preparation_ref:receipt.preparation_ref,connection_sha256:receipt.connection_sha256,
    workspace_id:receipt.workspace_id,request_nonce:receipt.request_nonce,bot:{address:'visit_prep',team_revision:1}};
  expect(validateVisitPrep(receipt,command)).toEqual(receipt);
  receipt.package.status='stale';expect(()=>validateVisitPrep(receipt,command)).toThrow();
});
