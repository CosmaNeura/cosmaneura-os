import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {InboxPanel} from './InboxPanel';
import {inboxApi} from './inbox-api';
import {actual,inboxFixture,inboxFixtureIdentity as identity,inboxFixtureOperation,inboxFixtureScope as scope} from './inbox-test-fixture';
import {emptyInboxDraft,emptyInboxRecovery,INBOX_RECOVERY_BYTES,INBOX_PROOF_RESERVE_BYTES,type InboxRecoveryRecord} from './inbox-recovery';
import {validateInbox} from './inbox-contract';
import {vendorBytes,vendorCanonical} from './vendor-contract';

vi.mock('./inbox-api',()=>({inboxApi:{catalog:vi.fn(),detail:vi.fn(),reviewOptions:vi.fn(),source:vi.fn(),history:vi.fn(),execute:vi.fn(),recover:vi.fn()}}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,container:HTMLDivElement;
const button=(name:string)=>Array.from(container.querySelectorAll('button')).find(v=>v.textContent?.trim()===name);
const waitFor=async(assert:()=>void)=>{for(let i=0;i<200;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{assert();done=true;}catch{/* Wait for mounted state. */}});if(done)return;}assert();};
const click=async(name:string)=>{await waitFor(()=>{expect(button(name)).toBeTruthy();expect(button(name)!.matches(':disabled')).toBe(false);});await act(async()=>button(name)!.click());};

async function restoredRecord(kind:'pending'|'parked',targetBytes:number){
  const operation=await inboxFixtureOperation(),record=emptyInboxRecovery(scope);
  if(kind==='pending')record.pending=operation;else record.parked=[{operation,receipt:null}];
  record.drafts=Array.from({length:40},()=>emptyInboxDraft(crypto.randomUUID(),null,null));
  record.drafts[0].instructions='Earlier private draft input must remain unchanged.';
  let remaining=targetBytes-vendorBytes(record);
  for(const draft of record.drafts)for(const key of ['instructions','result_evidence'] as const){
    const length=Math.min(remaining,2000-draft[key].length);draft[key]+='x'.repeat(length);remaining-=length;
  }
  expect(remaining).toBe(0);expect(vendorBytes(record)).toBe(targetBytes);return record;
}
function mount(initial:InboxRecoveryRecord){
  let durable=structuredClone(initial);
  const access={authorize:vi.fn(async()=>{}),load:vi.fn(async()=>structuredClone(durable)),persist:vi.fn(async(value:InboxRecoveryRecord|null)=>{if(!value)throw Error('No whole-record deletion');durable=structuredClone(value);}),denied:vi.fn()};
  act(()=>root.render(<InboxPanel identity={identity} recovery={access} presentation="focused" enabled/>));
  return {access,durable:()=>durable};
}
beforeEach(async()=>{
  vi.stubGlobal('crypto',webcrypto);Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  const bundle=await inboxFixture('initial');vi.mocked(inboxApi.catalog).mockResolvedValue({...validateInbox('Catalog',actual.catalog),items:[bundle.detail.summary]});vi.mocked(inboxApi.detail).mockResolvedValue(bundle);
  container=document.createElement('div');document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});

it.each(['pending','parked'] as const)('withholds an earlier near-bound %s recovery record without overwriting input or dispatching',async kind=>{
  const original=await restoredRecord(kind,INBOX_RECOVERY_BYTES-64),before=vendorCanonical(original),m=mount(original);
  await waitFor(()=>expect(button('Retry loading private Inbox recovery')).toBeTruthy());
  expect(button('Restore saved Inbox work')).toBeUndefined();expect(container.querySelector('textarea,pre,input[type=checkbox]')).toBeNull();
  expect(container.textContent).not.toContain('Earlier private draft input');expect(m.access.persist).not.toHaveBeenCalled();
  expect(vendorCanonical(m.durable())).toBe(before);expect(vendorCanonical(original)).toBe(before);
  const authorizations=m.access.authorize.mock.calls.length;await click('Retry loading private Inbox recovery');
  await waitFor(()=>expect(m.access.load).toHaveBeenCalledTimes(2));
  expect(m.access.authorize.mock.calls.length).toBeGreaterThan(authorizations);expect(m.access.persist).not.toHaveBeenCalled();
  expect(vendorCanonical(m.durable())).toBe(before);expect(inboxApi.execute).not.toHaveBeenCalled();expect(inboxApi.recover).not.toHaveBeenCalled();
});

it('restores an admitted near-bound command and saves its real fixture receipt and immutable history through the product recovery path',async()=>{
  const original=await restoredRecord('pending',INBOX_RECOVERY_BYTES-(INBOX_PROOF_RESERVE_BYTES-4)-64-32),operation=original.pending!;
  const missing=validateInbox('Receipt',{...actual.review_receipt,outcome:'not_found',effect:null,rejection:null,receipt_id:null,recorded_at:null,receipt_sha256:null});
  vi.mocked(inboxApi.recover).mockResolvedValueOnce(missing).mockResolvedValueOnce(validateInbox('Receipt',actual.review_receipt));
  const m=mount(original);await click('Restore saved Inbox work');
  expect(inboxApi.execute).not.toHaveBeenCalled();expect(m.durable().pending).toEqual(operation);
  await click('Recover exact Inbox receipt');await waitFor(()=>expect(m.durable().receipt).toEqual(missing));
  await click('Recover exact Inbox receipt');await waitFor(()=>expect(m.durable().receipt).toEqual(actual.review_receipt));
  await click('Keep proof and continue review');await waitFor(()=>expect(m.durable().history).toEqual([{operation,receipt:actual.review_receipt}]));
  expect(m.durable().pending).toBeNull();expect(m.durable().drafts).toEqual(original.drafts);expect(vendorBytes(m.durable())).toBeLessThan(INBOX_RECOVERY_BYTES);
  expect(container.textContent).not.toContain('Changes could not be saved safely');expect(inboxApi.execute).not.toHaveBeenCalled();expect(inboxApi.recover).toHaveBeenCalledTimes(2);
});
