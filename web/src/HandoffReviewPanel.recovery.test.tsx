import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {HandoffReviewPanel} from './HandoffReviewPanel';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress,editorAddress as addressFor} from './draft-journal';
import {openDraftStore,DraftStoreError,type DraftValue} from './draft-store';
import {WorkspaceApiError,type Workspace,type WorkspaceIdentity} from './workspace-api';
import type {HandoffReviewInput,HandoffRevisionInput} from './handoff-review-api';
import {reviewIdentity,reviewWorkspace,reviewReply,reviewRecord,reviewTime,reviewUuid,unavailableReviewWorkspace} from './handoff-review-recovery-fixture';
import {vendorSha256} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let host:HTMLDivElement,root:Root,idb:IDBFactory,journal:DraftJournal,access:EditorRecoveryAccess|null,workspace:Workspace;
let initial:Workspace,failWrites:number,scope:string;
const saved=vi.fn(),denied=vi.fn(),pendingChanged=vi.fn(),fresh=vi.fn();
const json=(value:unknown)=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
const address=()=>editorAddress(initial.id,`handoff-review:${initial.handoffs![0].id}`);
async function storage(){const s=await openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});return {read:s.read.bind(s),close:s.close.bind(s),write:async(id:string,expected:string|null,value:DraftValue|null)=>{
 if(id===address()&&failWrites){failWrites--;throw new DraftStoreError('unavailable');}return s.write(id,expected,value);
}};}
async function newJournal(){journal=new DraftJournal(await storage());access={workspaceId:initial.id,journal,authorize:vi.fn(async()=>workspace),denied};}
function Harness({identity=reviewIdentity}:{identity?:WorkspaceIdentity}){
 const [value,setValue]=useState(initial);workspace=value;
 return <EditorRecoveryContext.Provider value={access}><HandoffReviewPanel identity={identity} workspace={value} handoff={value.handoffs![0]} locked={false}
  onSaved={w=>{saved(w);setValue(w);}} onPendingChange={pendingChanged} onFreshAssignment={fresh} onAccessLost={denied}/></EditorRecoveryContext.Provider>;
}
const button=(text:string)=>{const b=[...host.querySelectorAll('button')].find(b=>b.textContent===text);expect(b,text).toBeTruthy();return b!;};
async function wait(check:()=>void|Promise<void>){for(let i=0;i<150;i++){let done=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,3));try{await check();done=true;}catch{}});if(done)return;}await check();}
async function click(text:string){await wait(()=>expect(button(text).disabled,text).toBe(false));await act(async()=>button(text).click());}
async function fill(value:string){const field=host.querySelector('textarea')!;expect(field?.disabled).toBe(false);await act(async()=>{
 Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function mount(identity:WorkspaceIdentity=reviewIdentity){await act(async()=>root.render(<Harness identity={identity}/>));await wait(()=>expect(host.querySelector('.handoff-review')?.getAttribute('aria-busy')).toBe('false'));}
async function reopen(value=workspace){await act(async()=>root.unmount());journal.close();initial=value;await newJournal();root=createRoot(host);await mount();}
async function pendingReady(){await wait(()=>expect(host.textContent).toContain('Review save unconfirmed'));}
async function createChange(){await click('Request changes');await fill('Please add a clinician owner; invented café detail.');await wait(async()=>expect((await journal.load(address()))?.kind).toBe('editor'));await click('Save change request');}
beforeEach(async()=>{
 Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');idb=new IDBFactory();scope='a'.repeat(64);failWrites=0;initial=await reviewWorkspace();workspace=initial;await newJournal();
 saved.mockClear();denied.mockClear();pendingChanged.mockClear();fresh.mockClear();host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());journal.close();host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});

it.each(['before_commit','after_commit'] as const)('restores encrypted exact review after %s loss without submitting until compare and explicit replay',async when=>{
 let committed:Awaited<ReturnType<typeof reviewReply>>|null=null;
 const fetcher=vi.fn(async(_url:string,init:RequestInit)=>{const body=JSON.parse(String(init.body)) as HandoffReviewInput;
   const persisted=await journal.load(address());expect(persisted).toMatchObject({pending:body.idempotency_key,data:{pending:{body}}});
   if(fetcher.mock.calls.length===1){if(when==='after_commit')committed=await reviewReply(initial,body);throw new TypeError('invented lost reply');}
   return json(committed??await reviewReply(initial,body));
 });vi.stubGlobal('fetch',fetcher);await mount();await createChange();await pendingReady();
 const command=String(fetcher.mock.calls[0][1].body),retained=await journal.load(address());expect(retained).toMatchObject({data:{pending:{kind:'review'}}});
 await reopen((committed as Awaited<ReturnType<typeof reviewReply>>|null)?.workspace??workspace);expect(host.textContent).toContain('saved handoff review draft');expect(fetcher).toHaveBeenCalledTimes(1);
 expect([...host.querySelectorAll('button')].filter(b=>b.textContent==='Accept draft for next work').every(b=>b.disabled)).toBe(true);await click('Restore handoff review draft');
 await wait(()=>expect(button('Retry same review save').disabled).toBe(true));expect(fetcher).toHaveBeenCalledTimes(1);
 await click('Check saved review status');expect(fetcher).toHaveBeenCalledTimes(1);expect(saved).toHaveBeenCalled();expect(await journal.load(address())).toEqual(retained);
 await click('Retry same review save');await wait(()=>expect(host.textContent).toContain('Changes requested'));
 expect(fetcher).toHaveBeenCalledTimes(2);expect(String(fetcher.mock.calls[1][1].body)).toBe(command);expect(await journal.load(address())).toBeNull();
});
it('preserves unsent feedback and optional DOB through encrypted reopen without creating a review',async()=>{
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);await mount();await click('Request changes');await fill('Unsent clinician request, café.');
 await wait(async()=>expect(await journal.load(address())).toMatchObject({pending:null,data:{feedback:'Unsent clinician request, café.'}}));
 await reopen();expect(fetcher).not.toHaveBeenCalled();await click('Restore handoff review draft');await wait(()=>expect((host.querySelector('textarea') as HTMLTextAreaElement)?.value).toBe('Unsent clinician request, café.'));
 expect(button('Save change request').disabled).toBe(false);expect(fetcher).not.toHaveBeenCalled();expect(workspace.label).toContain('without DOB');
});
it('prevents POST when the exact command journal write fails and keeps the volatile body for a storage retry',async()=>{
 const fetcher=vi.fn(async(_url:string,init:RequestInit)=>json(await reviewReply(initial,JSON.parse(String(init.body)))));vi.stubGlobal('fetch',fetcher);await mount();failWrites=1;
 await click('Accept draft for next work');await wait(()=>expect(host.textContent).toContain('request was not submitted'));
 expect(fetcher).not.toHaveBeenCalled();expect(button('Accept draft for next work').disabled).toBe(true);expect(button('Retry same review save').disabled).toBe(true);
 await click('Recheck handoff review recovery');await wait(()=>expect(button('Retry same review save').disabled).toBe(false));
 await click('Retry same review save');await wait(()=>expect(host.textContent).toContain('Draft accepted'));expect(fetcher).toHaveBeenCalledOnce();
});
it('retains committed acceptance when clearing the encrypted journal fails, then retrieves its exact receipt with the same key',async()=>{
 let committed:Awaited<ReturnType<typeof reviewReply>>|null=null;const fetcher=vi.fn(async(_u:string,init:RequestInit)=>{
  committed=committed??await reviewReply(initial,JSON.parse(String(init.body)));if(fetcher.mock.calls.length===1)failWrites=1;return json(committed);
 });vi.stubGlobal('fetch',fetcher);await mount();await click('Accept draft for next work');await pendingReady();
 expect(await journal.load(address())).toMatchObject({data:{pending:{body:{decision:'accepted'}}}});expect(saved).not.toHaveBeenCalled();
 await reopen(committed!.workspace);await click('Restore handoff review draft');await click('Check saved review status');await click('Retry same review save');
 await wait(async()=>expect(await journal.load(address())).toBeNull());expect(fetcher.mock.calls[0][1].body).toBe(fetcher.mock.calls[1][1].body);
});
it('withholds restored feedback and draft after current source revocation while confirming a historical exact review',async()=>{
 let committed:Awaited<ReturnType<typeof reviewReply>>|null=null;const fetcher=vi.fn(async(_u:string,init:RequestInit)=>{
  committed=committed??await reviewReply(initial,JSON.parse(String(init.body)));if(fetcher.mock.calls.length===1)throw new TypeError('lost');
  return json({...committed,feedback_withheld:true,workspace:unavailableReviewWorkspace(committed.workspace)});
 });vi.stubGlobal('fetch',fetcher);await mount();await createChange();await pendingReady();await reopen(unavailableReviewWorkspace(committed!.workspace));
 await click('Restore handoff review draft');expect(host.textContent).not.toContain('café');expect(host.querySelector('textarea')).toBeNull();expect(host.querySelector('[aria-label="Complete saved draft"]')).toBeNull();
 await click('Check saved review status');await click('Retry same review save');await wait(()=>expect(host.textContent).toContain('exact saved review is confirmed'));
 expect(await journal.load(address())).toBeNull();expect(host.textContent).not.toContain('café');expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Prepare revised draft'||b.textContent==='Ask Chief for fresh work')).toBe(false);
});
it('does not authorize retained text against a different result or guessed encounter',async()=>{
 const record=await reviewRecord(initial,'feedback'),editor=`handoff-review:${initial.handoffs![0].id}` as const;
 await journal.load(address());await journal.persist(address(),{kind:'editor',workspaceId:initial.id,editor,data:record,pending:null});
 const changed={...initial,handoffs:initial.handoffs!.map(h=>({...h,attempt_id:reviewUuid(91)}))};initial=changed;workspace=changed;await mount();await click('Restore handoff review draft');
 await wait(()=>expect(host.textContent).toContain('belongs to an earlier draft'));expect(button('Accept draft for next work').disabled).toBe(true);expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe(record.feedback);
 await reopen({...workspace,appointment_id:reviewUuid(92)});await click('Restore handoff review draft');await wait(()=>expect(denied).toHaveBeenCalled());expect(host.textContent).toContain('local record is retained');
});
it('clears only nonpending historical feedback from encrypted storage before accepting the verified current draft',async()=>{
 const record=await reviewRecord(initial,'feedback'),old=initial.handoffs![0],editor=`handoff-review:${old.id}` as const;
 await journal.load(address());await journal.persist(address(),{kind:'editor',workspaceId:initial.id,editor,data:record,pending:null});
 initial={...initial,handoffs:[{...old,attempt_id:reviewUuid(81),attempts:[{id:reviewUuid(81),number:2,status:'completed',error_code:null}]}]};workspace=initial;
 const fetcher=vi.fn(async(_u:string,init:RequestInit)=>json(await reviewReply(initial,JSON.parse(String(init.body)))));vi.stubGlobal('fetch',fetcher);
 await mount();await click('Restore handoff review draft');await wait(()=>expect(button('Discard retained feedback').disabled).toBe(false));
 expect(button('Accept draft for next work').disabled).toBe(true);expect(button('Ask Chief for fresh work').disabled).toBe(false);
 await click('Discard retained feedback');await wait(async()=>expect(await journal.load(address())).toBeNull());
 expect(fetcher).not.toHaveBeenCalled();await click('Accept draft for next work');await wait(()=>expect(host.textContent).toContain('Draft accepted'));
 expect(fetcher).toHaveBeenCalledOnce();expect(JSON.parse(String(fetcher.mock.calls[0][1].body)).attempt_id).toBe(reviewUuid(81));
});
it.each([401,403,404,426])('keeps encrypted pending work but hides plaintext when fresh recovery access is denied %s',async status=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new TypeError('lost')));await mount();await createChange();await pendingReady();await reopen();
 if(!access)throw new Error('No fixture access');access.authorize=vi.fn().mockRejectedValue(new WorkspaceApiError(status));await mount();await click('Restore handoff review draft');
 expect(denied).toHaveBeenCalled();expect(await journal.load(address())).not.toBeNull();expect(host.textContent).not.toContain('invented café detail');expect(host.querySelector('textarea')).toBeNull();
});
it('uses separate encrypted account namespaces and withholds late work after the current account changes',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new TypeError('lost')));await mount();await createChange();await pendingReady();
 await act(async()=>root.render(<Harness identity={{mode:'clerk_jwt',getToken:async()=> 'another-invented-account'}}/>));
 expect(host.textContent).toContain('Workspace access is unavailable');expect(host.textContent).not.toContain('café');
 await act(async()=>root.unmount());journal.close();scope='b'.repeat(64);await newJournal();root=createRoot(host);await mount();expect(host.textContent).not.toContain('saved handoff review draft');
});
it('fails closed for an authenticated panel without recovery storage, including synthetic environment configuration',async()=>{
 access=null;vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','true');const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);await act(async()=>root.render(<Harness/>));
 expect(button('Accept draft for next work').disabled).toBe(true);expect(host.querySelector('[aria-label="Complete saved draft"]')).toBeNull();expect(fetcher).not.toHaveBeenCalled();
 await act(async()=>root.unmount());root=createRoot(host);
 await act(async()=>root.render(<HandoffReviewPanel workspace={initial} handoff={initial.handoffs![0]} identity={reviewIdentity} locked={false} onSaved={saved}/>));
 await wait(()=>expect(button('Accept draft for next work').disabled).toBe(true));
 expect(button('Accept draft for next work').disabled).toBe(true);expect(host.querySelector('[aria-label="Complete saved draft"]')).toBeNull();
});
it('restores an unknown revision command and replays only its same original key after checking current saved history',async()=>{
 const record=await reviewRecord(initial,'revision');if(record.pending?.kind!=='revision')throw new Error('Wrong fixture');
 initial={...initial,revision:4,handoffs:initial.handoffs!.map(h=>({...h,review:record.pending!.kind==='revision'?record.pending!.review:null,review_status:'current' as const}))};workspace=initial;
 const base=await reviewRecord(initial,'revision');await journal.load(address());await journal.persist(address(),{kind:'editor',workspaceId:initial.id,editor:`handoff-review:${initial.handoffs![0].id}`,data:base,pending:base.pending!.body.idempotency_key});
 const fetcher=vi.fn(async(_u:string,init:RequestInit)=>{
  const body=JSON.parse(String(init.body)) as HandoffRevisionInput,h=initial.handoffs![0],review=h.review!,entry=initial.entries[0],nextId=reviewUuid(50),origin=reviewUuid(51),resultId=reviewUuid(52),content='Revised invented follow-up draft.';
  return json({entry_revision:body.expected_revision+1,revision_handoff_id:nextId,workspace:{...initial,revision:body.expected_revision+2,
   entries:[...initial.entries,{...entry,id:origin,revision:body.expected_revision+1,kind:'conversation',origin:'authenticated_human',reply:null},
     {...entry,id:resultId,revision:body.expected_revision+2,reply:{...entry.reply!,content}}],
   handoffs:[{...h,review:{...review,revision_handoff_id:nextId}},{...h,id:nextId,origin_entry_id:origin,attempt_id:reviewUuid(53),result_entry_id:resultId,result_sha256:await vendorSha256(new TextEncoder().encode(content)),review:null,
    revision_request:{parent_handoff_id:h.id,review_id:review.id,attempt_id:review.attempt_id,result_entry_id:review.result_entry_id,result_sha256:review.result_sha256,feedback:review.feedback}}]}});
 });vi.stubGlobal('fetch',fetcher);await mount();expect(fetcher).not.toHaveBeenCalled();await click('Restore handoff review draft');await wait(()=>expect(button('Retry same revised assignment').disabled).toBe(true));
 await click('Check saved review status');await click('Retry same revised assignment');await wait(async()=>expect(await journal.load(address())).toBeNull());
 expect(fetcher).toHaveBeenCalledOnce();expect(JSON.parse(String(fetcher.mock.calls[0][1].body))).toEqual(base.pending!.body);expect(workspace.handoffs).toHaveLength(2);
 expect(addressFor(workspace.id,`handoff-review:${initial.handoffs![0].id}`)).toBe(address());expect(reviewTime).toBeTruthy();
});
