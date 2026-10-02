import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {memoryDraftStorage} from './draft-test-fixture';
import {workspaceApi,type Workspace} from './workspace-api';
import {teamFixture} from './team-setup-test-fixture';
import type {HandoffReviewInput,HandoffRevisionInput,ReviewableHandoff,HandoffReviewReceipt} from './handoff-review-api';
import {hasUnsavedWork} from './unsaved-work';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404))}};});
vi.mock('./draft-store',async original=>({...await original<typeof import('./draft-store')>(),privateDraftScope:async(s:string)=>s}));
vi.mock('./workspace-api',async original=>{const actual=await original<typeof import('./workspace-api')>();return {...actual,workspaceApi:{...actual.workspaceApi,
  open:vi.fn(),catalog:vi.fn(),team:vi.fn(),read:vi.fn(),ask:vi.fn(),append:vi.fn(),retryHandoff:vi.fn()}};});
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const time='2026-10-02T14:00:00Z',identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-owner'},team=teamFixture();
team.capture={enabled:false};team.scheduling={enabled:false};
let root:Root,host:HTMLDivElement,current:Workspace,storage:ReturnType<typeof memoryDraftStorage>,fetcher:ReturnType<typeof vi.fn>;
const reviews:HandoffReviewInput[]=[],revisions:HandoffRevisionInput[]=[];
const hash=async(content:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(content)))].map(n=>n.toString(16).padStart(2,'0')).join('');
async function fixture():Promise<Workspace> {
  const content='Invented Scribe summary: Shawn describes heart issues. DOB unavailable. Confirm diagnosis and current medicines.\nResearch should find candidate clinical trials and preserve eligibility uncertainty.';
  const handoff:ReviewableHandoff={id:uuid(701),origin_entry_id:uuid(600),recipient_role:'follow_up',recipient_name:'follow up',recipient_agent_id:uuid(102),
    brief:'Prepare an administrative follow-up draft',context_revision:1,status:'completed',attempt_id:uuid(702),attempt_count:1,result_entry_id:uuid(601),
    result_sha256:await hash(content),error_code:null,review:null,review_status:'not_reviewed',attempts:[{id:uuid(702),number:1,status:'completed',error_code:null}]};
  return {id:uuid(71),appointment_id:uuid(72),label:'Invented Shawn encounter',revision:3,model_contract_version:1,model_observed_at:time,work_candidates:[],
    entries:[{id:uuid(600),revision:2,kind:'conversation',content:'Chief, break up the Scribe summary for the team.',source_label:null,origin:'human',ticket:null,created_at:time,
      reply:{agent_name:'chief',agent_id:uuid(103),role:'chief',backend:'synthetic-boundary',content:'Follow-up assignment prepared.',context_revision:1,citations:[]}},
      {id:uuid(601),revision:3,kind:'handoff_result',content:handoff.brief,source_label:null,origin:'agent_handoff',ticket:null,created_at:time,
        reply:{agent_name:'follow up',agent_id:uuid(102),role:'follow_up',backend:'synthetic-boundary',content,context_revision:1,citations:[]}}],handoffs:[handoff]};
}
const json=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
async function wire(url:string,init:RequestInit) {
  const handoffId=/\/handoffs\/([^/]+)\//.exec(url)![1],parent=current.handoffs!.find(h=>h.id===handoffId)! as ReviewableHandoff;
  if(url.endsWith('/review')) {
    const body=JSON.parse(init.body as string) as HandoffReviewInput;reviews.push(body);
    const review:HandoffReviewReceipt={id:uuid(800+reviews.length),attempt_id:body.attempt_id,result_entry_id:body.result_entry_id,
      result_sha256:body.result_sha256,decision:body.decision,feedback:body.feedback,created_at:time};
    current={...current,revision:body.expected_revision+1,handoffs:current.handoffs!.map(h=>h.id===parent.id?{...h,review,review_status:'current'}:h)};
    return json({entry_revision:body.expected_revision+1,workspace:current});
  }
  const body=JSON.parse(init.body as string) as HandoffRevisionInput;revisions.push(body);const review=parent.review!,origin=uuid(900),resultId=uuid(901),nextId=uuid(902);
  const prior=current.entries.find(e=>e.id===review.result_entry_id)!,content=prior.reply!.content+'\nRevision: the nurse will confirm medicines by tomorrow; provider reviews trial criteria.';
  const next:ReviewableHandoff={...parent,id:nextId,origin_entry_id:origin,status:'completed',attempt_id:uuid(903),attempt_count:1,result_entry_id:resultId,
    result_sha256:await hash(content),review:null,review_status:'not_reviewed',attempts:[{id:uuid(903),number:1,status:'completed',error_code:null}],
    revision_request:{parent_handoff_id:parent.id,review_id:review.id,attempt_id:review.attempt_id,result_entry_id:review.result_entry_id,result_sha256:review.result_sha256,feedback:review.feedback}};
  current={...current,revision:body.expected_revision+2,handoffs:[...current.handoffs!.map(h=>h.id===parent.id?{...h,review:{...review,revision_handoff_id:next.id}}:h),next],
    entries:[...current.entries,{id:origin,revision:body.expected_revision+1,kind:'conversation',content:'Prepare a revised draft.',source_label:null,origin:'authenticated_human',ticket:null,created_at:time},
      {...prior,id:resultId,revision:body.expected_revision+2,reply:{...prior.reply!,content}}]};
  return json({entry_revision:body.expected_revision+1,revision_handoff_id:next.id,workspace:current});
}
const visible=(element:Element)=>!element.closest('[hidden]');
function button(label:string){return [...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===label||b.getAttribute('aria-label')===label));}
async function wait(check:()=>void){for(let n=0;n<200;n++){let passed=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,3));try{check();passed=true;}catch{}});if(passed)return;}check();}
async function click(label:string){await wait(()=>{expect(button(label),label).toBeTruthy();expect(button(label)!.disabled,label).toBe(false);});await act(async()=>button(label)!.click());}
async function input(selector:string,value:string){const field=host.querySelector<HTMLTextAreaElement>(selector)!;expect(field).toBeTruthy();await act(async()=>{
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function mount(){root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));}
async function open(){await click('Choose an encounter');await wait(()=>expect(host.querySelector('.team-encounter-option')).toBeTruthy());await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());await wait(()=>expect(button('Review result')).toBeTruthy());}
async function review(){await click('Review result');await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toBe(current.entries.find(e=>e.id===current.handoffs![0].result_entry_id)!.reply!.content));}
beforeEach(async()=>{vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');
  current=await fixture();reviews.splice(0);revisions.splice(0);storage=memoryDraftStorage();fetcher=vi.fn(wire);vi.stubGlobal('fetch',fetcher);
  vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));vi.mocked(workspaceApi.open).mockImplementation(async()=>({identity,workspace:structuredClone(current),team:structuredClone(team)}));
  vi.mocked(workspaceApi.read).mockImplementation(async()=>structuredClone(current));vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:current.appointment_id,workspace_id:current.id,label:current.label}]);
  host=document.createElement('div');document.body.append(host);await mount();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();vi.unstubAllEnvs();vi.restoreAllMocks();});

it('completes the product Team work → full draft → changes → revised assignment → acceptance path through actual DOM controls',async()=>{
  await open();await review();expect(reviews).toHaveLength(0);expect(revisions).toHaveLength(0);await click('Request changes');
  await input('[aria-label="Change request"]','Name who confirms medications and when.');await click('Save change request');await wait(()=>expect(button('Prepare revised draft')).toBeTruthy());
  expect(host.textContent).toContain('Changes requested');await click('Prepare revised draft');await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toContain('Revision: the nurse'));
  expect(revisions).toHaveLength(1);expect(host.textContent).not.toContain('Draft accepted');await click('Accept draft for next work');await wait(()=>expect(host.textContent).toContain('Draft accepted'));
  expect(reviews).toHaveLength(2);expect(reviews[0].result_sha256).not.toBe(reviews[1].result_sha256);expect(reviews[1].result_entry_id).toBe(uuid(901));
  expect(reviews[1].result_sha256).toBe(await hash(current.entries.find(e=>e.id===uuid(901))!.reply!.content));expect(hasUnsavedWork()).toBe(false);
  expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.retryHandoff).not.toHaveBeenCalled();
});
it('retains an unconfirmed review in the actual product and blocks navigation and concurrent workspace writes until exact retry',async()=>{
  await open();await review();fetcher.mockRejectedValueOnce(new TypeError('lost response'));await click('Request changes');await input('[aria-label="Change request"]','Retain this exact edit request.');await click('Save change request');
  await wait(()=>expect(button('Retry same review save')).toBeTruthy());const panel=host.querySelector('.handoff-review'),encoded=fetcher.mock.calls[0][1].body;
  expect(hasUnsavedWork()).toBe(true);expect(host.querySelector('main')?.getAttribute('data-settings-navigation-locked')).toBe('true');
  for(const label of ['Team settings','Practice work','Close draft review'])expect(button(label)?.disabled,label).toBe(true);
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.disabled).toBe(true);expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.disabled).toBe(true);
  expect(button('Refresh encounter')?.disabled).toBe(true);await click('Close notebook');expect(host.querySelector('.handoff-review')).toBe(panel);
  await click('Retry same review save');await wait(()=>expect(host.textContent).toContain('Changes requested'));expect(fetcher.mock.calls[1][1].body).toBe(encoded);
  expect(hasUnsavedWork()).toBe(false);expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});
it('reopens a persisted review/revision and does not issue duplicate commands on reload',async()=>{
  await open();await review();await click('Request changes');await input('[aria-label="Change request"]','Add a due date.');await click('Save change request');await wait(()=>expect(button('Prepare revised draft')).toBeTruthy());
  await click('Prepare revised draft');await wait(()=>expect(current.handoffs).toHaveLength(2));await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toContain('Revision: the nurse'));
  await click('Close draft review');const callCount=fetcher.mock.calls.length;await act(async()=>root.unmount());await mount();await open();
  const old=host.querySelector<HTMLButtonElement>('.team-work-overview .team-task-grid article:last-child button')!;await act(async()=>old.click());await wait(()=>expect(host.textContent).toContain('Revised assignment saved.'));
  expect([...host.querySelectorAll('button')].some(b=>visible(b)&&b.textContent==='Prepare revised draft')).toBe(false);expect(fetcher).toHaveBeenCalledTimes(callCount);expect(revisions).toHaveLength(1);
  await click('Review revised draft');await wait(()=>expect(host.querySelector('[aria-label="Complete saved draft"]')?.textContent).toContain('Revision: the nurse'));
});
it('focuses review controls and recovers a definite conflict without losing the requested edits',async()=>{
  await open();await review();expect(document.activeElement).toBe(host.querySelector('.handoff-review h3'));
  fetcher.mockResolvedValueOnce(new Response(JSON.stringify({detail:'workspace_revision_conflict'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  await click('Request changes');await input('[aria-label="Change request"]','Preserve this edit after loading the current draft.');await click('Save change request');
  await wait(()=>expect(button('Refresh draft to review')).toBeTruthy());expect(button('Retry same review save')).toBeUndefined();
  const first=JSON.parse(fetcher.mock.calls[0][1].body as string);current={...current,revision:current.revision+1};
  await click('Refresh draft to review');await wait(()=>expect(button('Save change request')?.disabled).toBe(false));
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="Change request"]')!.value).toBe('Preserve this edit after loading the current draft.');
  await click('Save change request');await wait(()=>expect(host.textContent).toContain('Changes requested'));
  expect(reviews).toHaveLength(1);expect(reviews[0].expected_revision).toBe(first.expected_revision+1);expect(reviews[0].idempotency_key).not.toBe(first.idempotency_key);
});
it('clears the product private draft view when review authority is denied',async()=>{
  await open();await review();fetcher.mockResolvedValueOnce(new Response('{}',{status:403,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));
  await click('Accept draft for next work');await wait(()=>expect(host.textContent).toContain('Private content has been cleared from this view.'));
  expect(host.querySelector('.handoff-review')).toBeNull();expect(host.textContent).not.toContain('Shawn describes heart issues');
});
it('carries stale-source requested changes into an editable Chief question without automatically starting model work',async()=>{
  current={...current,handoffs:current.handoffs!.map(h=>({...h,review_status:'stale' as const,review:{id:uuid(810),attempt_id:h.attempt_id,
    result_entry_id:h.result_entry_id!,result_sha256:h.result_sha256!,decision:'changes_requested' as const,feedback:'Confirm current medicines before allocating follow-up.',created_at:time}}))};
  await open();await input('#team-question','Keep my existing question about records.');await review();expect(button('Accept draft for next work')?.disabled).toBe(true);
  await click('Ask Chief for fresh work');await wait(()=>expect(host.querySelector('.handoff-review')).toBeNull());
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toContain('Confirm current medicines before allocating follow-up.');
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')?.value).toContain('Keep my existing question about records.');
  expect(workspaceApi.ask).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();expect(revisions).toHaveLength(0);
});
