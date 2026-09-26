import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {InboxPanel,type InboxPanelProps} from './InboxPanel';
import {inboxApi} from './inbox-api';
import {actual,inboxFixture,inboxFixtureIdentity as identity,inboxFixtureScope as scope,inboxFixtureOperation} from './inbox-test-fixture';
import {emptyInboxRecovery,emptyInboxDraft,type InboxRecoveryRecord} from './inbox-recovery';
import {validateInbox,type InboxOperation} from './inbox-contract';
import {vendorDigest} from './vendor-contract';
import {WorkspaceApiError} from './workspace-api';
import type {ReviewOptions} from './inbox-schema';
vi.mock('./inbox-api',()=>({inboxApi:{catalog:vi.fn(),detail:vi.fn(),reviewOptions:vi.fn(),source:vi.fn(),history:vi.fn(),execute:vi.fn(),recover:vi.fn()}}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,container:HTMLDivElement,bundle:Awaited<ReturnType<typeof inboxFixture>>,options:ReviewOptions;
const button=(name:string)=>{const value=Array.from(container.querySelectorAll('button')).find(v=>v.textContent?.trim()===name);if(!value)throw Error('Missing button '+name);return value;};
const control=(name:string)=>{const label=Array.from(container.querySelectorAll('label')).find(l=>Array.from(l.childNodes).filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim()===name);const value=label?.querySelector('input,select,textarea');if(!value)throw Error('Missing control '+name);return value as HTMLInputElement;};
const waitFor=async(check:()=>void)=>{for(let i=0;i<200;i++){let passed=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();passed=true;}catch{/* Await React and owned persistence only. */}});if(passed)return;}check();};
const click=(name:string)=>act(()=>button(name).click());
const check=(name:string)=>act(()=>control(name).click());
const input=(name:string,value:string)=>act(()=>{const c=control(name),prototype=c.tagName==='SELECT'?HTMLSelectElement.prototype:c.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(prototype,'value')!.set!.call(c,value);c.dispatchEvent(new Event(c.tagName==='SELECT'?'change':'input',{bubbles:true}));});
const page=()=>container.querySelector('.inbox-focused')?.getAttribute('data-page');
const ready=()=>waitFor(()=>expect(button('Refresh private Inbox').matches(':disabled')).toBe(false));
const onlyPage=(name:string,fields:number)=>{expect(page()).toBe(name);expect(container.querySelectorAll('fieldset')).toHaveLength(fields);expect(container.querySelectorAll('main')).toHaveLength(name==='list'?0:1);};
function setBundle(value:typeof bundle){bundle=value;vi.mocked(inboxApi.detail).mockResolvedValue(bundle);vi.mocked(inboxApi.catalog).mockResolvedValue({...validateInbox('Catalog',actual.catalog),items:[bundle.detail.summary]});}
async function syntheticReceipt(op:InboxOperation){
  const state=op.kind==='review'?'reviewed':op.kind==='triage'?(op.request.classification==='administrative_review'?'triaged':'needs_human'):op.kind==='result'?(op.request.disposition==='local_review_complete'?'result_recorded':'needs_human'):'closed_local_review';
  const body={contract_version:1,scope:op.scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256,outcome:'recorded',effect:{item_id:op.request.item_id,version:op.request.expected_version+1,source_id:op.request.source_id??null,source_sha256:op.request.source_sha256??null,state},rejection:null,receipt_id:crypto.randomUUID(),recorded_at:actual.review_receipt.recorded_at};
  return validateInbox('Receipt',{...body,receipt_sha256:await vendorDigest('cosmas-inbox-receipt.v1',body)});
}
beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);vi.clearAllMocks();container=document.createElement('div');document.body.append(container);root=createRoot(container);
  setBundle(await inboxFixture('initial'));
  const body={contract_version:1,scope,item_id:bundle.detail.summary.item_id,item_version:bundle.detail.summary.version,source_id:bundle.detail.summary.source_id,source_sha256:bundle.detail.summary.source_sha256,patient_link_id:bundle.detail.summary.patient_link_id,choices:[{workspace_id:actual.review_request.workspace_id,expected_workspace_revision:actual.review_request.expected_workspace_revision,appointment_id:crypto.randomUUID(),label:'Invented matching encounter',start_at:actual.review_receipt.recorded_at}]};
  options=validateInbox('ReviewOptions',{...body,options_sha256:await vendorDigest('cosmas-inbox-review-options.v1',body)});vi.mocked(inboxApi.reviewOptions).mockResolvedValue(options);vi.mocked(inboxApi.source).mockResolvedValue(bundle.detail.source!);vi.mocked(inboxApi.execute).mockImplementation(async(_id,op)=>syntheticReceipt(op));
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.unstubAllGlobals();});
function mount(saved:InboxRecoveryRecord|null=null,patch:Partial<InboxPanelProps>={}){let durable=saved;const access={load:vi.fn(async()=>durable),persist:vi.fn(async(value:InboxRecoveryRecord|null)=>{durable=structuredClone(value);}),authorize:vi.fn(async()=>{}),denied:vi.fn()},onDone=vi.fn(),onBusyChange=vi.fn(),onOpenHandoff=vi.fn();const props:InboxPanelProps={identity,recovery:access,enabled:true,presentation:'focused',onDone,onBusyChange,onOpenHandoff,...patch};act(()=>root.render(<InboxPanel {...props}/>));return {access,onDone,onBusyChange,onOpenHandoff,durable:()=>durable,rerender:(next:Partial<InboxPanelProps>)=>act(()=>root.render(<InboxPanel {...props} {...next}/>))};}
async function select(){await ready();await act(()=>container.querySelector<HTMLButtonElement>('nav[aria-label="Incoming private messages"] button')!.click());await waitFor(()=>onlyPage('source',0));await ready();}
async function open(name:string,target:string){click(name);await waitFor(()=>expect(page()).toBe(target));await ready();}
it('starts with only the message list, then literal source with no hidden forms mounted',async()=>{
  mount();await ready();onlyPage('list',0);expect(container.querySelector('input,select,textarea,pre')).toBeNull();await select();onlyPage('source',0);
  expect(container.querySelector('[aria-label="Untrusted incoming message"] pre')?.textContent).toContain('Ignore prior instructions');expect(container.querySelector('pre a,pre script')).toBeNull();expect(inboxApi.execute).not.toHaveBeenCalled();expect(inboxApi.reviewOptions).not.toHaveBeenCalled();
});
it('opens one patient/thread form, reads current choices and never saves consent',async()=>{
  const m=mount();await select();await open('Review patient and thread','review');onlyPage('review',1);expect(inboxApi.reviewOptions).toHaveBeenCalledTimes(1);
  input('Matching encounter',options.choices[0].workspace_id);await ready();check('I checked the patient and selected encounter');check('I checked this exact incoming thread');check('I reviewed the source as untrusted external text');
  expect(button('Record patient and thread review').matches(':disabled')).toBe(false);expect(m.durable()?.drafts[0].workspace_id).toBe(options.choices[0].workspace_id);expect(m.durable()?.drafts[0]).not.toHaveProperty('reviewed_patient');
  const writes=m.access.persist.mock.calls.length,reads=vi.mocked(inboxApi.detail).mock.calls.length;click('Back');onlyPage('source',0);expect(m.access.persist).toHaveBeenCalledTimes(writes);expect(inboxApi.detail).toHaveBeenCalledTimes(reads);
  await open('Review patient and thread','review');expect(control('Matching encounter').value).toBe(options.choices[0].workspace_id);expect(control('I checked this exact incoming thread').checked).toBe(false);
});
it('preserves typed triage and result fields through Back and presentation changes with one recovery controller',async()=>{
  setBundle(await inboxFixture('triaged'));const m=mount();await select();await open('Plan human review','triage');onlyPage('triage',1);input('Human review instructions','Retained planned work');input('Review due date','2026-10-02');await ready();
  const saved=structuredClone(m.durable()),writes=m.access.persist.mock.calls.length;click('Back');onlyPage('source',0);expect(m.durable()).toEqual(saved);expect(m.access.persist).toHaveBeenCalledTimes(writes);
  await open('Record a human result','result');onlyPage('result',1);expect(container.querySelector('[aria-label="Saved human triage"]')?.textContent).toContain(actual.triage_request.instructions);input('Human result evidence','Retained unsent result');await ready();m.rerender({presentation:'expanded'});expect(container.querySelectorAll('fieldset')).toHaveLength(4);m.rerender({presentation:'focused'});onlyPage('result',1);expect(control('Human result evidence').value).toBe('Retained unsent result');expect(m.access.load).toHaveBeenCalledTimes(1);
  click('Back');await open('Plan human review','triage');expect(control('Human review instructions').value).toBe('Retained planned work');expect(control('Review due date').value).toBe('2026-10-02');
});
it.each(['clinical_human_review','urgent_human_review','source_exception'] as const)('keeps %s triage available before administrative patient review',async classification=>{
  mount();await select();await open('Plan human review','triage');input('Review classification',classification);input('Review due date','2026-10-02');input('Human review instructions','A person must review this invented source.');await ready();check('I confirm that a human must perform this review');click('Record human triage');
  await waitFor(()=>expect(inboxApi.execute).toHaveBeenCalledTimes(1));expect(vi.mocked(inboxApi.execute).mock.calls[0][1]).toMatchObject({kind:'triage',request:{classification,human_disposition_required:true}});expect(inboxApi.reviewOptions).not.toHaveBeenCalled();await waitFor(()=>expect(page()).toBe('recovery'));expect(container.querySelector('fieldset')).toBeNull();
});
it('retains the exact command until proof is archived, then opens only the next eligible page',async()=>{
  const op=await inboxFixtureOperation('review');setBundle(await inboxFixture('reviewed'));const m=mount({...emptyInboxRecovery(scope),pending:op,receipt:validateInbox('Receipt',actual.review_receipt)});
  await waitFor(()=>expect(button('Restore saved Inbox work')).toBeTruthy());click('Restore saved Inbox work');await waitFor(()=>expect(page()).toBe('recovery'));expect(container.querySelector('nav[aria-label="Incoming private messages"],fieldset')).toBeNull();
  click('Keep proof and continue review');await waitFor(()=>onlyPage('triage',1));await ready();expect(m.durable()?.history).toEqual([{operation:op,receipt:actual.review_receipt}]);expect(m.durable()?.pending).toBeNull();expect(inboxApi.execute).not.toHaveBeenCalled();
});
it('returns completed verification to a truthful read-only source summary',async()=>{
  const op=await inboxFixtureOperation('verify');setBundle(await inboxFixture('closed'));mount({...emptyInboxRecovery(scope),pending:op,receipt:validateInbox('Receipt',actual.verify_receipt)});
  await waitFor(()=>expect(button('Restore saved Inbox work')).toBeTruthy());click('Restore saved Inbox work');await waitFor(()=>expect(page()).toBe('recovery'));click('Keep proof and continue review');await waitFor(()=>onlyPage('source',0));expect(container.textContent).toContain('The owner verified this local review');expect(container.textContent).toContain('No reply, vendor action or clinical completion is claimed');
});
it('keeps history and historical sources separate from current source and draft input',async()=>{
  const m=mount();await select();await open('Plan human review','triage');input('Human review instructions','Preserve this current-source draft');await ready();click('Back');await open('Source and review history','history');onlyPage('history',0);
  const before=structuredClone(m.durable()),historical={...bundle.detail.source!,text:'Retained earlier source text',sequence:1};vi.mocked(inboxApi.source).mockResolvedValue(historical);click('Read source version 1');await waitFor(()=>onlyPage('historical',0));await ready();expect(container.querySelector('[aria-label="Historical untrusted message"]')?.textContent).toContain(historical.text);expect(m.durable()).toEqual(before);
  click('Back');onlyPage('history',0);click('Back');onlyPage('source',0);expect(container.querySelector('[aria-label="Untrusted incoming message"] pre')?.textContent).toBe(bundle.detail.source!.text);await open('Plan human review','triage');expect(control('Human review instructions').value).toBe('Preserve this current-source draft');
});
it('copies earlier human text into the current draft without reusing old confirmations or changing the old draft',async()=>{
  const d=bundle.detail.summary,old={...emptyInboxDraft(d.item_id,crypto.randomUUID(),'e'.repeat(64)),workspace_id:options.choices[0].workspace_id,instructions:'An earlier human plan',result_evidence:'An earlier human result',result_disposition:'local_review_complete' as const};const m=mount({...emptyInboxRecovery(scope),drafts:[old]});
  await waitFor(()=>expect(button('Restore saved Inbox work')).toBeTruthy());click('Restore saved Inbox work');await select();await open('Source and review history','history');click('Copy earlier text for editing');await waitFor(()=>onlyPage('triage',1));await ready();expect(control('Human review instructions').value).toBe(old.instructions);expect(control('I confirm that a human must perform this review').checked).toBe(false);
  expect(m.durable()?.drafts[0]).toEqual(old);expect(m.durable()?.drafts[1]).toMatchObject({source_id:d.source_id,workspace_id:'',result_disposition:'needs_human'});expect(inboxApi.execute).not.toHaveBeenCalled();
});
it('passes only a fresh selected ID to handoff after its read finishes and navigation is no longer busy',async()=>{
  const m=mount();await select();let finish!:(value:typeof bundle)=>void;vi.mocked(inboxApi.detail).mockImplementationOnce(()=>new Promise(r=>{finish=r;}));click('Open incoming follow-up');await waitFor(()=>expect(finish).toBeTypeOf('function'));expect(m.onOpenHandoff).not.toHaveBeenCalled();expect(button('Done').disabled).toBe(true);expect(m.onBusyChange).toHaveBeenLastCalledWith(true);
  await act(async()=>finish(bundle));await waitFor(()=>expect(m.onOpenHandoff).toHaveBeenCalledTimes(1));expect(m.onOpenHandoff).toHaveBeenCalledWith(bundle.detail.summary.item_id);expect(m.onBusyChange).toHaveBeenLastCalledWith(false);expect(m.durable()?.pending).toBeNull();expect(inboxApi.execute).not.toHaveBeenCalled();
});
it('requires a renewed selection if source or authority changed during handoff opening',async()=>{
  const m=mount();await select();const changed=structuredClone(bundle);changed.detail.availability.review=false;changed.detail.summary.workspace_current=false;vi.mocked(inboxApi.detail).mockResolvedValue(changed);click('Open incoming follow-up');await waitFor(()=>expect(container.textContent).toContain('review state changed'));expect(m.onOpenHandoff).not.toHaveBeenCalled();expect(inboxApi.execute).not.toHaveBeenCalled();
});
it('does not hand off a parked item or lose its original exact command on navigation',async()=>{
  const op=await inboxFixtureOperation(),m=mount({...emptyInboxRecovery(scope),parked:[{operation:op,receipt:null}]});await waitFor(()=>expect(button('Restore saved Inbox work')).toBeTruthy());click('Restore saved Inbox work');await select();expect(button('Open incoming follow-up').matches(':disabled')).toBe(true);click('Open incoming follow-up');expect(m.onOpenHandoff).not.toHaveBeenCalled();click('Back');onlyPage('list',0);expect(m.durable()?.parked).toEqual([{operation:op,receipt:null}]);
});
it('never discloses or forwards a late handoff selection after account access is lost',async()=>{
  const m=mount();await select();vi.mocked(inboxApi.detail).mockRejectedValueOnce(new WorkspaceApiError(403));click('Open incoming follow-up');await waitFor(()=>expect(container.textContent).toContain('Access to private Inbox is unavailable'));expect(m.onOpenHandoff).not.toHaveBeenCalled();expect(container.querySelector('pre,fieldset')).toBeNull();
});
it('retains read-only source/history when new Inbox work is disabled',async()=>{
  const readOnly=structuredClone(bundle);readOnly.detail.availability={review:false,triage:false,result:false,verify:false,history_capacity_remaining:99};setBundle(readOnly);vi.mocked(inboxApi.catalog).mockResolvedValue({...validateInbox('Catalog',actual.catalog),enabled:false,items:[bundle.detail.summary]});mount(null,{onOpenHandoff:undefined});await select();expect(container.textContent).toContain('New Inbox work is disabled');onlyPage('source',0);expect(container.querySelector('[aria-label="Available Inbox review steps"]')?.querySelectorAll('button')).toHaveLength(1);await open('Source and review history','history');onlyPage('history',0);expect(inboxApi.execute).not.toHaveBeenCalled();
});

it('manual due date preserves a leap day and consent across view-only switches before exact triage',async()=>{
  const m=mount();await select();await open('Plan human review','triage');expect(control('Review due date').type).toBe('date');click('Type date');expect(control('Review due date').type).toBe('text');
  input('Review classification','clinical_human_review');input('Human review instructions','A person reviews this source.');input('Review due date','2028-02-29');await ready();check('I confirm that a human must perform this review');
  const before=structuredClone(m.durable()),writes=m.access.persist.mock.calls.length;click('Use calendar');expect(control('Review due date').value).toBe('2028-02-29');click('Type date');expect(control('Review due date').value).toBe('2028-02-29');expect(control('I confirm that a human must perform this review').checked).toBe(true);expect(m.durable()).toEqual(before);expect(m.access.persist).toHaveBeenCalledTimes(writes);expect(inboxApi.execute).not.toHaveBeenCalled();
  click('Record human triage');await waitFor(()=>expect(inboxApi.execute).toHaveBeenCalledTimes(1));expect(vi.mocked(inboxApi.execute).mock.calls[0][1]).toMatchObject({kind:'triage',request:{due_date:'2028-02-29',human_disposition_required:true}});expect(m.durable()?.pending?.request).toMatchObject({due_date:'2028-02-29'});
});
it('manual due date retains invalid locale and incomplete text while blocking triage',async()=>{
  const m=mount();await select();await open('Plan human review','triage');click('Type date');input('Review classification','clinical_human_review');input('Human review instructions','Review this source.');
  for(const value of ['2026-02-29','2026-04-31','03/04/2026','2026-0']){input('Review due date',value);await ready();check('I confirm that a human must perform this review');expect(control('Review due date').value).toBe(value);expect(m.durable()?.drafts[0].due_date).toBe(value);expect(button('Record human triage').matches(':disabled')).toBe(true);expect(button('Use calendar').matches(':disabled')).toBe(true);click('Record human triage');expect(m.durable()?.pending).toBeNull();expect(inboxApi.execute).not.toHaveBeenCalled();}
});
it('manual due date restores incomplete Inbox journal text without restoring consent',async()=>{
  const first=mount();await select();await open('Plan human review','triage');click('Type date');input('Review classification','clinical_human_review');input('Human review instructions','Retained instructions');input('Review due date','2026-0');await ready();check('I confirm that a human must perform this review');const saved=JSON.parse(JSON.stringify(first.durable())) as InboxRecoveryRecord;
  await act(async()=>root.unmount());root=createRoot(container);const second=mount(saved);await waitFor(()=>expect(button('Restore saved Inbox work')).toBeTruthy());click('Restore saved Inbox work');await select();await open('Plan human review','triage');expect(control('Review due date').type).toBe('text');expect(control('Review due date').value).toBe('2026-0');expect(control('Human review instructions').value).toBe('Retained instructions');expect(control('I confirm that a human must perform this review').checked).toBe(false);expect(second.durable()?.pending).toBeNull();expect(button('Record human triage').matches(':disabled')).toBe(true);
  input('Review due date','2026-09-23');await ready();expect(second.durable()?.drafts[0].due_date).toBe('2026-09-23');expect(button('Record human triage').matches(':disabled')).toBe(true);expect(inboxApi.execute).not.toHaveBeenCalled();
});
it('manual due date keeps an exact lost-response triage request through focused journal recovery',async()=>{
  const first=mount();await select();await open('Plan human review','triage');click('Type date');input('Review classification','clinical_human_review');input('Human review instructions','Review exactly this request.');input('Review due date','2026-09-23');await ready();check('I confirm that a human must perform this review');vi.mocked(inboxApi.execute).mockRejectedValueOnce(new WorkspaceApiError(503));click('Record human triage');await waitFor(()=>expect(button('Recover exact Inbox receipt').matches(':disabled')).toBe(false));const saved=JSON.parse(JSON.stringify(first.durable())) as InboxRecoveryRecord,op=saved.pending!;expect(op.request).toMatchObject({due_date:'2026-09-23'});expect(saved.receipt).toBeNull();
  await act(async()=>root.unmount());root=createRoot(container);const second=mount(saved);await waitFor(()=>expect(button('Restore saved Inbox work')).toBeTruthy());click('Restore saved Inbox work');await waitFor(()=>expect(page()).toBe('recovery'));expect(container.querySelector('input,textarea')).toBeNull();expect(inboxApi.execute).toHaveBeenCalledTimes(1);expect(inboxApi.recover).not.toHaveBeenCalled();vi.mocked(inboxApi.recover).mockResolvedValueOnce(await syntheticReceipt(op));click('Recover exact Inbox receipt');await waitFor(()=>expect(second.durable()?.receipt?.outcome).toBe('recorded'));expect(vi.mocked(inboxApi.recover).mock.calls[0][1]).toEqual(op);expect(second.durable()?.pending).toEqual(op);expect(inboxApi.execute).toHaveBeenCalledTimes(1);
});
