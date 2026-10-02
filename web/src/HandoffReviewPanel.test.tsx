import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterAll,afterEach,beforeEach,expect,it,vi} from 'vitest';
import {HandoffReviewPanel} from './HandoffReviewPanel';
import type {Workspace} from './workspace-api';
import type {HandoffReviewInput,HandoffReviewReceipt,HandoffRevisionInput,ReviewableHandoff} from './handoff-review-api';
import {hasUnsavedWork} from './unsaved-work';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const time='2026-10-02T14:00:00Z',access={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
const sha=async(content:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(content)))].map(n=>n.toString(16).padStart(2,'0')).join('');
type EventRecord={step:string;elapsed_ms:number;attempt_id?:string;result_entry_id?:string;result_sha256?:string;decision?:string};
const evidence:{persona:string;round:number;boundary:string;events:EventRecord[];outcome:string}[]=[];
const wireFixtures:{persona:string;round:number;initial_workspace:Workspace;exchanges:{kind:string;request:HandoffReviewInput|HandoffRevisionInput;response:unknown}[]}[]=[];
const exchanges:{kind:string;request:HandoffReviewInput|HandoffRevisionInput;response:unknown}[]=[];
let root:Root,element:HTMLDivElement,workspace:Workspace,replaceWorkspace:(w:Workspace)=>void;
const requests:HandoffReviewInput[]=[],revisionRequests:HandoffRevisionInput[]=[],saved=vi.fn(),close=vi.fn(),pendingChanged=vi.fn(),refresh=vi.fn(),accessLost=vi.fn(),freshAssignment=vi.fn();

async function encounter(round=1):Promise<Workspace> {
  const content='Invented patient Shawn reports prior heart issues. DOB not available.\nResearch: find relevant trial criteria without claiming eligibility.\nFollow-up: confirm history and arrange provider review.\nUncertainty: no verified diagnosis or current medicines.';
  const hash=await sha(content),handoff:ReviewableHandoff={id:uuid(701+round*100),origin_entry_id:uuid(600+round*100),recipient_role:'follow_up',recipient_name:'Follow-up',
    recipient_agent_id:uuid(102),brief:'Prepare a follow-up draft',context_revision:1,status:'completed',attempt_id:uuid(702+round*100),attempt_count:1,
    result_entry_id:uuid(601+round*100),result_sha256:hash,error_code:null,attempts:[{id:uuid(702+round*100),number:1,status:'completed',error_code:null}]};
  return {id:uuid(71+round*100),appointment_id:uuid(72+round*100),label:'Invented visit without DOB',revision:3,model_contract_version:1,model_observed_at:time,
    entries:[{id:handoff.result_entry_id!,revision:3,kind:'handoff_result',content:'Saved handoff',source_label:null,origin:'human',ticket:null,created_at:time,
      reply:{agent_id:uuid(102),agent_name:'Follow-up',role:'follow_up',backend:'synthetic-service-boundary',context_revision:1,content,citations:[]}}],work_candidates:[],handoffs:[handoff]};
}
function response(body:HandoffReviewInput,w=workspace) {
  const review:HandoffReviewReceipt={id:uuid(800+requests.length),attempt_id:body.attempt_id,result_entry_id:body.result_entry_id,
    result_sha256:body.result_sha256,decision:body.decision,feedback:body.feedback,created_at:time};
  return {entry_revision:body.expected_revision+1,workspace:{...w,revision:Math.max(w.revision,body.expected_revision+1),handoffs:w.handoffs!.map(h=>h.result_entry_id===body.result_entry_id?{...h,review}:h)}};
}
const json=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
function installService(){const fetcher=vi.fn(async(url:string,init:RequestInit)=>{
  if(url.endsWith('/revision')){const body=JSON.parse(init.body as string) as HandoffRevisionInput;revisionRequests.push(body);const reply=await revisionResponse(body);
    exchanges.push({kind:'revision',request:structuredClone(body),response:structuredClone(reply)});return json(reply);}
  const body=JSON.parse(init.body as string) as HandoffReviewInput;requests.push(body);const reply=response(body);
  exchanges.push({kind:'review',request:structuredClone(body),response:structuredClone(reply)});return json(reply);});vi.stubGlobal('fetch',fetcher);return fetcher;}
function Harness({initial,locked=false,recoveryLocked}:{initial:Workspace;locked?:boolean;recoveryLocked?:boolean}) {
  const [current,setCurrent]=useState(initial),[selected,setSelected]=useState(initial.handoffs![0].id);workspace=current;replaceWorkspace=setCurrent;
  return <HandoffReviewPanel workspace={current} handoff={current.handoffs!.find(h=>h.id===selected)??current.handoffs![0]} identity={access} locked={locked}
    onSaved={value=>{saved(value);setCurrent(value);}} onClose={close} onPendingChange={pendingChanged} onRevisionPrepared={setSelected}
    onRefresh={refresh} onAccessLost={accessLost} recoveryLocked={recoveryLocked} onFreshAssignment={freshAssignment}/>;
}
function button(text:string){const found=[...element.querySelectorAll('button')].find(b=>b.textContent===text);expect(found,text).toBeTruthy();return found!;}
async function click(text:string){expect(button(text).disabled,text).toBe(false);await act(async()=>button(text).click());}
async function input(value:string){const field=element.querySelector('textarea')!;expect(field).toBeTruthy();await act(async()=>{
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function until(check:()=>boolean){for(let n=0;n<100;n++){await act(async()=>{await new Promise(resolve=>setTimeout(resolve,2));});if(check())return;}throw new Error('Mounted review did not settle');}
async function mount(initial=workspace,locked=false){await act(async()=>root.render(<Harness initial={initial} locked={locked}/>));await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');}
async function revised(w=workspace):Promise<Workspace> {
  const original=w.handoffs![0] as ReviewableHandoff,entry=w.entries.find(e=>e.id===original.result_entry_id)!;
  const content=entry.reply!.content+'\nRevision: nurse to confirm medications by tomorrow; provider to review trial options.';
  const id=uuid(900+w.revision),attempt=uuid(950+w.revision),hash=await sha(content);
  const next:ReviewableHandoff={...original,attempt_id:attempt,attempt_count:2,result_entry_id:id,result_sha256:hash,
    attempts:[...original.attempts,{id:attempt,number:2,status:'completed',error_code:null}]};
  return {...w,revision:w.revision+1,entries:[...w.entries,{...entry,id,revision:w.revision+1,reply:{...entry.reply!,content}}],handoffs:[next]};
}
async function revisionResponse(body:HandoffRevisionInput,w=workspace) {
  const parent=w.handoffs![0] as ReviewableHandoff,review=parent.review!,source=w.entries.find(entry=>entry.id===review.result_entry_id)!;
  const nextId=uuid(1000+w.revision),originId=uuid(1100+w.revision),resultId=uuid(1200+w.revision),attemptId=uuid(1300+w.revision);
  const content=source.reply!.content+'\nRevision: nurse to confirm medications by tomorrow; provider to review trial options.';
  const next:ReviewableHandoff={...parent,id:nextId,origin_entry_id:originId,status:'completed',attempt_id:attemptId,attempt_count:1,
    result_entry_id:resultId,result_sha256:await sha(content),review:null,attempts:[{id:attemptId,number:1,status:'completed',error_code:null}],
    revision_request:{parent_handoff_id:parent.id,review_id:review.id,attempt_id:review.attempt_id,result_entry_id:review.result_entry_id,
      result_sha256:review.result_sha256,feedback:review.feedback}};
  const request={id:originId,revision:body.expected_revision+1,kind:'conversation' as const,content:'Prepare a revised draft from the saved change request.',source_label:null,origin:'authenticated_human',ticket:null,created_at:time};
  const result={...source,id:resultId,revision:body.expected_revision+2,reply:{...source.reply!,content}};
  return {entry_revision:body.expected_revision+1,revision_handoff_id:next.id,workspace:{...w,revision:body.expected_revision+2,
    entries:[...w.entries,request,result],handoffs:[{...parent,review:{...review,revision_handoff_id:next.id}},next]}};
}
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');
  workspace=await encounter();requests.splice(0);revisionRequests.splice(0);exchanges.splice(0);saved.mockClear();close.mockClear();pendingChanged.mockClear();refresh.mockReset();accessLost.mockClear();freshAssignment.mockClear();installService();element=document.createElement('div');document.body.append(element);root=createRoot(element);});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();vi.unstubAllEnvs();});

it.each([{persona:'Family-practice physician',round:1},{persona:'Nurse practitioner',round:1},{persona:'Physician assistant',round:1},
  {persona:'Family-practice physician',round:2},{persona:'Nurse practitioner',round:2},{persona:'Physician assistant',round:2}])('$persona round $round completes request-edits and exact revised-draft acceptance through DOM controls',async({persona,round})=>{
  const started=performance.now(),events:EventRecord[]=[],step=(label:string,body?:HandoffReviewInput)=>events.push({step:label,elapsed_ms:Math.round((performance.now()-started)*100)/100,
    ...(body?{attempt_id:body.attempt_id,result_entry_id:body.result_entry_id,result_sha256:body.result_sha256,decision:body.decision}:{})});
  workspace=await encounter(round);const initial=structuredClone(workspace);await mount();step('opened_complete_saved_draft');
  const original=workspace.entries[0].reply!.content;expect(element.querySelector('[aria-label="Complete saved draft"]')!.textContent).toBe(original);
  expect(element.textContent).toContain('DOB not available');expect(requests).toHaveLength(0);await click('Request changes');step('requested_changes');
  expect(button('Save change request').disabled).toBe(true);await input('Please name who will confirm the medicines and when.');await click('Save change request');
  await until(()=>element.textContent!.includes('Changes requested'));step('change_request_saved',requests[0]);
  expect(requests[0]).toMatchObject({decision:'changes_requested',result_sha256:await sha(original),feedback:'Please name who will confirm the medicines and when.'});
  expect(button('Prepare revised draft').disabled).toBe(false);expect(hasUnsavedWork()).toBe(false);
  await click('Prepare revised draft');await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false'&&workspace.handoffs!.length===2);step('revised_assignment_saved');
  const next=workspace,nextHandoff=next.handoffs!.at(-1)!;expect(revisionRequests).toHaveLength(1);
  expect(element.textContent).not.toContain('Draft accepted');expect(element.querySelector('[aria-label="Complete saved draft"]')!.textContent).toBe(next.entries.at(-1)!.reply!.content);step('opened_revised_saved_draft');
  await click('Accept draft for next work');await until(()=>element.textContent!.includes('Draft accepted'));step('revised_draft_accepted',requests[1]);
  expect(requests[1]).toMatchObject({decision:'accepted',feedback:'',expected_revision:next.revision,result_entry_id:nextHandoff.result_entry_id,
    attempt_id:nextHandoff.attempt_id,result_sha256:await sha(next.entries.at(-1)!.reply!.content)});
  expect(requests[0].result_sha256).not.toBe(requests[1].result_sha256);expect(saved).toHaveBeenCalledTimes(3);expect(hasUnsavedWork()).toBe(false);
  expect(element.textContent).toContain('Clinical sign-off and any delivery remain separate');await click('Close draft review');expect(close).toHaveBeenCalledOnce();step('closed_review');
  evidence.push({persona,round,boundary:'Mounted React DOM and actual bounded review/revision APIs; invented HTTP service responses and completed specialist work. Scripted nontechnical persona scenario, not physical device or clinical review.',events,outcome:'completed'});
  wireFixtures.push({persona,round,initial_workspace:initial,exchanges:structuredClone(exchanges)});
});

it('keeps an uncertain decision and retries exactly the same body/key even after the workspace changes',async()=>{
  const first=workspace,fetcher=vi.fn().mockRejectedValueOnce(new TypeError('lost response')).mockImplementationOnce(async(_url:string,init:RequestInit)=>{
    const body=JSON.parse(init.body as string) as HandoffReviewInput;requests.push(body);return json(response(body,first));});vi.stubGlobal('fetch',fetcher);
  await mount();await click('Request changes');await input('Keep this exact change request.');await click('Save change request');await until(()=>element.textContent!.includes('Review save unconfirmed'));
  expect(button('Accept draft for next work').disabled).toBe(true);expect(button('Close draft review').disabled).toBe(true);expect(element.querySelector('textarea')!.disabled).toBe(true);expect(hasUnsavedWork()).toBe(true);
  const next=await revised();await act(async()=>replaceWorkspace(next));await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');
  expect(element.querySelector('[aria-label="Complete saved draft"]')!.textContent).toBe(first.entries[0].reply!.content);
  await click('Retry same review save');await until(()=>element.textContent!.includes('Changes requested'));
  expect(fetcher).toHaveBeenCalledTimes(2);expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);expect(saved).toHaveBeenCalledOnce();expect(hasUnsavedWork()).toBe(false);
});
it('admits only one review during a pending save and does not claim acceptance before confirmation',async()=>{
  let release!:(value:Response)=>void;const fetcher=vi.fn(async(_url:string,init:RequestInit)=>{requests.push(JSON.parse(init.body as string));return new Promise<Response>(resolve=>{release=resolve;});});vi.stubGlobal('fetch',fetcher);
  await mount();const accept=button('Accept draft for next work');await act(async()=>{accept.click();accept.click();});await until(()=>fetcher.mock.calls.length===1);
  expect(element.textContent).not.toContain('Draft accepted');expect(button('Accept draft for next work').disabled).toBe(true);expect(hasUnsavedWork()).toBe(true);
  await act(async()=>release(json(response(requests[0]))));await until(()=>element.textContent!.includes('Draft accepted'));expect(fetcher).toHaveBeenCalledOnce();
});
it('retains an uncertain revised assignment request and resolves the same body without another model assignment',async()=>{
  await mount();await click('Request changes');await input('Add an owner.');await click('Save change request');await until(()=>element.textContent!.includes('Changes requested'));
  const snapshot=workspace;let savedResponse:Awaited<ReturnType<typeof revisionResponse>>|undefined;
  const fetcher=vi.fn().mockImplementationOnce(async(_url:string,init:RequestInit)=>{const body=JSON.parse(init.body as string);savedResponse=await revisionResponse(body,snapshot);throw new TypeError('response lost after assignment recorded');})
    .mockImplementationOnce(async()=>json(savedResponse));vi.stubGlobal('fetch',fetcher);
  await click('Prepare revised draft');await until(()=>element.textContent!.includes('Revised assignment save unconfirmed'));
  expect([...element.querySelectorAll('button')].some(b=>b.textContent==='Prepare revised draft')).toBe(false);expect(button('Close draft review').disabled).toBe(true);expect(hasUnsavedWork()).toBe(true);expect(pendingChanged).toHaveBeenLastCalledWith(true);
  expect(element.textContent).not.toContain('Revised assignment saved.');await click('Retry same revised assignment');
  await until(()=>workspace.handoffs!.length===2&&element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');
  expect(fetcher).toHaveBeenCalledTimes(2);expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);expect(hasUnsavedWork()).toBe(false);expect(pendingChanged).toHaveBeenLastCalledWith(false);
});
it('recognizes a saved revision after remount and offers its actual task status without another command',async()=>{
  await mount();await click('Request changes');await input('Add a due date.');await click('Save change request');await until(()=>element.textContent!.includes('Changes requested'));
  const body:HandoffRevisionInput={expected_revision:workspace.revision,idempotency_key:'retained-revision-key',review_id:(workspace.handoffs![0] as ReviewableHandoff).review!.id};
  const reply=await revisionResponse(body);reply.workspace.handoffs[1].status='queued';reply.workspace.handoffs[1].result_entry_id=null;
  await act(async()=>root.unmount());root=createRoot(element);await mount(reply.workspace);
  expect(element.textContent).toContain('Revised assignment saved.');expect(element.textContent).toContain('Revised draft queued');
  expect([...element.querySelectorAll('button')].some(b=>b.textContent==='Prepare revised draft')).toBe(false);expect(revisionRequests).toHaveLength(0);expect(button('Open revised assignment').disabled).toBe(false);
});
it('withholds review for an altered, shortened or missing result and while capture is locked',async()=>{
  await mount(workspace,true);expect(button('Accept draft for next work').disabled).toBe(true);expect(button('Request changes').disabled).toBe(true);
  const changed=structuredClone(workspace);changed.entries[0].reply!.content='Shortened preview';await act(async()=>replaceWorkspace(changed));await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');
  expect(element.textContent).toContain('complete saved draft could not be verified');expect(element.querySelector('[aria-label="Complete saved draft"]')).toBeNull();expect(requests).toHaveLength(0);
});
it('does not show historical acceptance as acceptance of a new result',async()=>{
  await mount();await click('Accept draft for next work');await until(()=>element.textContent!.includes('Draft accepted'));const next=await revised();
  await act(async()=>replaceWorkspace(next));await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');
  expect(element.textContent).not.toContain('Draft accepted');expect(button('Accept draft for next work').disabled).toBe(false);expect(requests).toHaveLength(1);
});
it('withholds late verification after the displayed result is replaced',async()=>{
  const original=webcrypto.subtle.digest.bind(webcrypto.subtle);let finish!:()=>void;const gate=new Promise<void>(resolve=>{finish=resolve;});
  const spy=vi.spyOn(webcrypto.subtle,'digest').mockImplementationOnce(async(algorithm,data)=>{await gate;return original(algorithm,data);});
  await act(async()=>root.render(<Harness initial={workspace}/>));const changed=structuredClone(workspace);changed.entries[0].reply!.content='Unverified replacement';
  await act(async()=>replaceWorkspace(changed));await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');
  await act(async()=>{finish();await new Promise(resolve=>setTimeout(resolve,5));});expect(button('Accept draft for next work').disabled).toBe(true);
  expect(element.querySelector('[aria-label="Complete saved draft"]')).toBeNull();expect(requests).toHaveLength(0);spy.mockRestore();
});
it('requires a current review after the server marks the previous review stale',async()=>{
  await mount();await click('Accept draft for next work');await until(()=>element.textContent!.includes('Draft accepted'));
  const changed=structuredClone(workspace);changed.handoffs![0].review_status='stale';await act(async()=>replaceWorkspace(changed));
  await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');expect(element.textContent).not.toContain('Draft accepted');
  expect(element.textContent).toContain('Ask Chief for a fresh assignment');expect(button('Accept draft for next work').disabled).toBe(true);expect(button('Request changes').disabled).toBe(true);
});
it('retains feedback after a definite revision conflict and permits a fresh decision only after explicit verified refresh',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:'workspace_revision_conflict'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}))
    .mockImplementationOnce(async(_url:string,init:RequestInit)=>{const body=JSON.parse(init.body as string);requests.push(body);return json(response(body));});vi.stubGlobal('fetch',fetcher);
  await mount();await click('Request changes');await input('Retain this feedback through refresh.');await click('Save change request');await until(()=>element.textContent!.includes('This request was not saved'));
  expect(button('Save change request').disabled).toBe(true);expect([...element.querySelectorAll('button')].some(b=>b.textContent==='Retry same review save')).toBe(false);
  expect(element.querySelector('textarea')!.value).toBe('Retain this feedback through refresh.');
  await act(async()=>root.render(<Harness initial={workspace} locked={true} recoveryLocked={false}/>));expect(button('Refresh draft to review').disabled).toBe(false);
  refresh.mockImplementation(async()=>{replaceWorkspace({...workspace,revision:workspace.revision+1});});await click('Refresh draft to review');
  await act(async()=>root.render(<Harness initial={workspace} locked={false} recoveryLocked={false}/>));
  await until(()=>button('Save change request').disabled===false);expect(element.querySelector('textarea')!.value).toBe('Retain this feedback through refresh.');
  await click('Save change request');await until(()=>element.textContent!.includes('Changes requested'));
  const first=JSON.parse(fetcher.mock.calls[0][1].body),second=JSON.parse(fetcher.mock.calls[1][1].body);
  expect(second.expected_revision).toBe(first.expected_revision+1);expect(second.idempotency_key).not.toBe(first.idempotency_key);
});
it('does not authorize a new decision if a definite-refusal refresh fails or returns no fresh projection',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'workspace_revision_conflict'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));
  await mount();await click('Accept draft for next work');await until(()=>element.textContent!.includes('This request was not saved'));
  refresh.mockRejectedValueOnce(new Error('read unavailable'));await click('Refresh draft to review');await until(()=>element.textContent!.includes('latest draft could not be loaded'));
  expect(button('Accept draft for next work').disabled).toBe(true);await act(async()=>replaceWorkspace({...workspace,revision:workspace.revision+1}));
  await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');expect(button('Accept draft for next work').disabled).toBe(true);
  refresh.mockResolvedValueOnce(undefined);await click('Refresh draft to review');
  await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');expect(button('Accept draft for next work').disabled).toBe(true);
});
it('directs a first definite source refusal to a fresh assignment, preserving feedback without same-key deadlock',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'handoff_sources_changed'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));
  await mount();await click('Request changes');await input('Keep this intended edit.');await click('Save change request');await until(()=>element.textContent!.includes('Ask Chief for a fresh assignment'));
  expect(button('Accept draft for next work').disabled).toBe(true);expect(button('Request changes').disabled).toBe(true);expect(element.querySelector('textarea')!.value).toBe('Keep this intended edit.');
  expect([...element.querySelectorAll('button')].some(b=>b.textContent==='Retry same review save')).toBe(false);
  await click('Ask Chief for fresh work');expect(freshAssignment).toHaveBeenCalledExactlyOnceWith('Keep this intended edit.');expect(requests).toHaveLength(0);
});
it('passes historical requested changes into a fresh editable Chief assignment without a model call',async()=>{
  await mount();await click('Request changes');await input('Keep the original requested owner and deadline.');await click('Save change request');await until(()=>element.textContent!.includes('Changes requested'));
  const changed=structuredClone(workspace);changed.handoffs![0].review_status='stale';await act(async()=>replaceWorkspace(changed));
  await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');await click('Ask Chief for fresh work');
  expect(freshAssignment).toHaveBeenCalledExactlyOnceWith('Keep the original requested owner and deadline.');expect(requests).toHaveLength(1);expect(revisionRequests).toHaveLength(0);
  expect(element.querySelector('h3')!.tabIndex).toBe(-1);
});
it('retains an uncertain old request through later source refusal and allows conflict-independent exact recovery',async()=>{
  const first=workspace,fetcher=vi.fn().mockRejectedValueOnce(new TypeError('lost response')).mockResolvedValueOnce(new Response(JSON.stringify({detail:'handoff_sources_changed'}),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}))
    .mockImplementationOnce(async(_url:string,init:RequestInit)=>{const body=JSON.parse(init.body as string);return json({...response(body,first),workspace:{...response(body,first).workspace,handoffs:response(body,first).workspace.handoffs.map(h=>({...h,review_status:'stale'}))}});});vi.stubGlobal('fetch',fetcher);
  await mount();await click('Accept draft for next work');await until(()=>element.textContent!.includes('Review save unconfirmed'));await click('Retry same review save');
  await until(()=>button('Retry same review save').disabled===false);await act(async()=>root.render(<Harness initial={first} locked={true} recoveryLocked={false}/>));
  expect(button('Retry same review save').disabled).toBe(false);await click('Retry same review save');await until(()=>element.textContent!.includes('Ask Chief for a fresh assignment'));
  expect(fetcher.mock.calls.every(c=>c[1].body===fetcher.mock.calls[0][1].body)).toBe(true);expect(element.textContent).not.toContain('Draft accepted');expect(hasUnsavedWork()).toBe(false);
});
it.each([401,403,404,426])('withholds the exact draft and notifies the product on authority refusal %s',async status=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('private error body',{status})));await mount();await click('Accept draft for next work');
  await until(()=>element.textContent!.includes('draft is withheld'));expect(element.querySelector('[aria-label="Complete saved draft"]')).toBeNull();expect(element.textContent).not.toContain('Invented patient Shawn');
  expect(accessLost).toHaveBeenCalledOnce();expect(accessLost.mock.calls[0][0]).toMatchObject({status});
});
it('clears change input when opening a different completed assignment before a save',async()=>{
  await mount();await click('Request changes');await input('Feedback for the old result');const next=await revised();await act(async()=>replaceWorkspace(next));
  await until(()=>element.querySelector('.handoff-review')?.getAttribute('aria-busy')==='false');expect(element.querySelector('textarea')).toBeNull();expect(hasUnsavedWork()).toBe(false);expect(requests).toHaveLength(0);
});
it('blocks excess or blank feedback without submitting a human decision',async()=>{
  await mount();await click('Request changes');await input('   ');expect(button('Save change request').disabled).toBe(true);
  await input('😀'.repeat(2001));expect(button('Save change request').disabled).toBe(true);expect(element.textContent).toContain('2,000 characters');expect(requests).toHaveLength(0);
});

afterAll(async()=>{
  const directory=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env.COSMABOT_AGENT_OPERATIONAL_EVIDENCE_DIR;if(!directory)return;
  const fsModule='node:fs/promises';const {mkdir,writeFile}=await import(/* @vite-ignore */fsModule) as {
    mkdir:(path:string,options:{recursive:true})=>Promise<unknown>;writeFile:(path:string,content:string)=>Promise<void>};await mkdir(directory,{recursive:true});
  await writeFile(`${directory}/handoff-review-scenarios.json`,JSON.stringify({schema:'cosmabot.handoff-review-ui-evidence.v1',synthetic_only:true,
    scenario_count:evidence.length,completed:evidence.filter(s=>s.outcome==='completed').length,scenarios:evidence},null,2)+'\n');
  await writeFile(`${directory}/handoff-review-wire-fixtures.json`,JSON.stringify({schema:'cosmabot.handoff-review-synthetic-wire-fixtures.v1',synthetic_only:true,
    boundary:'Reusable invented requests and mocked responses from mounted UI trials; not a database seed or server end-to-end result.',fixtures:wireFixtures},null,2)+'\n');
});
