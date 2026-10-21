import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CreatorReviewPanel} from './CreatorReviewPanel';
import {creatorReviewApi} from './creator-review-api';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {HttpCreatorReviewApi,type CreatorReviewView} from '../../clients/scribe-review/creator-review-api';
import {CreatorReviewError} from '../../clients/scribe-review/creator-review-api';
import type {AuthenticatedWorkspaceIdentity,Workspace} from './workspace-api';
import {WorkspaceApiError} from './workspace-api';
import {editorAddress} from './draft-journal';
import {editorDraft} from './editor-recovery';
import type {PendingReviewDecision} from '../../clients/scribe-review/creator-review-journal';
import golden from '../../tests/fixtures/creator_review.json';

vi.mock('./creator-review-api',()=>({creatorReviewApi:vi.fn()}));
const wid='00000000-0000-4000-8000-000000000001',sid='00000000-0000-4000-8000-000000000002';
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const workspace:Workspace={id:wid,appointment_id:sid,label:'Invented visit',revision:1,entries:[],work_candidates:[]};
const view:CreatorReviewView={schema_version:'1.0',session_id:sid,status:'processing',source:null,working:null,review_queue:null,translation_progress:[]};
let host:HTMLDivElement,root:Root,access:EditorRecoveryAccess;
const availability=vi.fn(),source=vi.fn(),lock=vi.fn(),continueToNote=vi.fn(),read=vi.fn(),decide=vi.fn();
const mount=(owner=identity,recovery:EditorRecoveryAccess|null=access)=>act(async()=>root.render(<EditorRecoveryContext.Provider value={recovery}>
  <CreatorReviewPanel workspaceId={wid} sessionId={sid} identity={owner} locked={false} onLock={lock} onSource={source} onContinue={continueToNote}
    onAvailability={availability}/>
</EditorRecoveryContext.Provider>));
beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  access={workspaceId:wid,journal:new DraftJournal(await memoryDraftStorage()({scope:'a'.repeat(64)})),authorize:vi.fn().mockResolvedValue(workspace),denied:vi.fn()};
  const api=new HttpCreatorReviewApi(sid,vi.fn());vi.spyOn(api,'read').mockImplementation(read);vi.spyOn(api,'decide').mockImplementation(decide);
  vi.mocked(creatorReviewApi).mockReturnValue(api);read.mockResolvedValue(view);
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();host.remove();vi.unstubAllGlobals();vi.unstubAllEnvs();});

it('reports the real review failure while retaining an explicit refresh to the existing transcript',async()=>{
  read.mockRejectedValueOnce(new Error('private denied/session detail'));
  await mount();await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(source).toHaveBeenLastCalledWith(null);expect(host.textContent).toContain('The transcript could not be retrieved');
  expect(host.textContent).not.toContain('private denied/session detail');expect(continueToNote).not.toHaveBeenCalled();
  await act(async()=>host.querySelector<HTMLButtonElement>('[data-review-action="refresh"]')!.click());
  await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('ready'));
  expect(source).toHaveBeenLastCalledWith(view);expect(read).toHaveBeenCalledTimes(2);expect(decide).not.toHaveBeenCalled();
});

it('clears a successful API snapshot if the exact encrypted review recovery cannot be read',async()=>{
  vi.spyOn(access.journal,'load').mockRejectedValueOnce(new Error('private journal detail'));
  await mount();await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(source).toHaveBeenLastCalledWith(null);expect(host.textContent).toContain('Your review recovery could not be checked');
  expect(host.textContent).not.toContain('private journal detail');expect(decide).not.toHaveBeenCalled();
});

function transcript(which:'ready'|'waiting'='ready'):CreatorReviewView{
  const result=structuredClone(golden[which]);result.session_id=sid;result.review_queue.session_id=sid;
  result.source.segments[0].content='Invented transcript must disappear';
  for(const item of result.review_queue.items)item.source_content=result.source.segments[0].content;
  return result as CreatorReviewView;
}

it('distinguishes denied fresh workspace authorization and clears an otherwise valid transcript',async()=>{
  read.mockResolvedValue(transcript());vi.mocked(access.authorize).mockRejectedValueOnce(new WorkspaceApiError(403,'untrusted-private-reason'));
  const recovery=vi.spyOn(access.journal,'load');
  await mount();await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(host.textContent).toContain('Your access to this workspace could not be confirmed');
  expect(host.textContent).toContain('authorization_response_403_access_unavailable');
  expect(host.textContent).not.toContain('untrusted-private-reason');expect(host.textContent).not.toContain('Invented transcript must disappear');
  expect(recovery).not.toHaveBeenCalled();expect(source).toHaveBeenLastCalledWith(null);
  expect(host.querySelector('[data-review-action="continue"]')).toBeNull();expect(decide).not.toHaveBeenCalled();
});

it('keeps text and decisions closed after encrypted recovery fails, then reopens only after a successful fresh read and recovery',async()=>{
  read.mockResolvedValue(transcript());vi.spyOn(access.journal,'load').mockRejectedValueOnce(Error('untrusted-private-journal-detail'));
  await mount();await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(host.textContent).toContain('recovery_unconfirmed_recovery_unavailable');
  expect(host.textContent).not.toContain('untrusted-private-journal-detail');expect(host.textContent).not.toContain('Invented transcript must disappear');
  expect(source).toHaveBeenLastCalledWith(null);expect(host.querySelector('[data-review-action="continue"]')).toBeNull();
  await act(async()=>host.querySelector<HTMLButtonElement>('[data-review-action="refresh"]')!.click());
  await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('ready'));
  expect(read).toHaveBeenCalledTimes(2);expect(access.authorize).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain('Invented transcript must disappear');expect(host.textContent).not.toContain('recovery_unconfirmed');
  expect(host.querySelector('[data-review-action="continue"]')).not.toBeNull();expect(decide).not.toHaveBeenCalled();
});

it('classifies invalid encrypted decision recovery without retaining its arbitrary data',async()=>{
  read.mockResolvedValue(transcript());vi.spyOn(access.journal,'load').mockResolvedValueOnce({kind:'editor',workspaceId:wid,
    editor:`creator-review:${sid}`,pending:'untrusted-key',data:{private_detail:'untrusted-private-recovery'}}as never);
  await mount();await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(host.textContent).toContain('recovery_unconfirmed_recovery_invalid');expect(host.textContent).not.toContain('untrusted-private-recovery');
  expect(host.textContent).not.toContain('Invented transcript must disappear');expect(source).toHaveBeenLastCalledWith(null);
  expect(host.querySelector('[data-review-action="continue"]')).toBeNull();expect(decide).not.toHaveBeenCalled();
});

it('distinguishes invalid transcript response from an unavailable read and never opens recovery or review actions',async()=>{
  read.mockRejectedValueOnce(new CreatorReviewError('invalid_response',{phase:'response',reason:'invalid_response',status:200}));
  const recovery=vi.spyOn(access.journal,'load');
  await mount();await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(host.textContent).toContain('The transcript response could not be verified');expect(host.textContent).toContain('response_response_200_invalid_response');
  expect(recovery).not.toHaveBeenCalled();expect(source).toHaveBeenLastCalledWith(null);expect(decide).not.toHaveBeenCalled();
});

it.each([
  ['JSON',new TextEncoder().encode('{"private":"untrusted-private-marker"')],
  ['UTF-8',new Uint8Array([0xc3,0x28])],
]as const)('keeps the exact encrypted pending decision after malformed409 %s and retries only that request/key',async(_format,badBody)=>{
  const actual=await vi.importActual<typeof import('./creator-review-api')>('./creator-review-api');
  const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');
  const owner:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=> 'synthetic-token'};
  const review=transcript('waiting'),item=review.review_queue!.items![0],kind=`creator-review:${sid}`as const;
  const pending:PendingReviewDecision={key:'review-synthetic-fixed-key',request:{schema_version:'1.0',expected_source_transcript_version:review.source!.source_transcript_version,
    source_segment_id:item.source_segment_id,expected_source_segment_version:item.source_segment_version,translation_id:item.translation_id,
    expected_translation_version:item.translation_version,decision:'accepted'}};
  const address=editorAddress(wid,kind);await access.journal.load(address);await access.journal.persist(address,editorDraft(wid,kind,pending,pending.key));
  let attempts=0;const requests:Record<string,unknown>[]=[];
  vi.stubGlobal('fetch',vi.fn(async(_input:unknown,init:RequestInit)=>{
    const request=JSON.parse(String(init.body));requests.push(request);
    if(request.operation.kind==='creator_review')return Response.json({workspace_id:wid,session_id:sid,operation:'creator_review',receipt:review},{headers:{'Cache-Control':'no-store'}});
    expect(request.operation.kind).toBe('decide_translation');attempts++;
    if(attempts===1)return new Response(badBody,{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
    return Response.json({workspace_id:wid,session_id:sid,operation:'decide_translation',receipt:{schema_version:'1.0',session_id:sid,saved:true,
      review_id:'00000000-0000-4000-8000-000000000004'}},{headers:{'Cache-Control':'no-store'}});
  }));
  vi.mocked(creatorReviewApi).mockReturnValue(actual.creatorReviewApi(wid,sid,owner));
  await mount(owner);await vi.waitFor(()=>expect(host.querySelector('[data-review-action="retry"]')).not.toBeNull());
  await act(async()=>host.querySelector<HTMLButtonElement>('[data-review-action="retry"]')!.click());
  await vi.waitFor(()=>expect(attempts).toBe(1));await vi.waitFor(()=>expect(host.textContent).toContain('The save is unconfirmed'));
  expect(await access.journal.load(address)).toMatchObject({kind:'editor',data:pending,pending:pending.key});expect(lock).toHaveBeenLastCalledWith(true);
  expect(host.textContent).not.toContain('untrusted-private-marker');expect(host.querySelector('[data-review-action="continue"]')).toBeNull();
  await act(async()=>host.querySelector<HTMLButtonElement>('[data-review-action="retry"]')!.click());
  await vi.waitFor(()=>expect(attempts).toBe(2));await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('ready'));
  const decisions=requests.filter(request=>(request.operation as {kind:string}).kind==='decide_translation');
  expect(decisions).toHaveLength(2);expect(decisions[0]).toEqual(decisions[1]);
  expect(decisions[0]).toMatchObject({session_id:sid,idempotency_key:pending.key,operation:{kind:'decide_translation',payload:pending.request}});
  expect(await access.journal.load(address)).toBeNull();expect(continueToNote).not.toHaveBeenCalled();
});

it('clears only the matching encrypted pending decision after a valid decoded409 conflict',async()=>{
  const actual=await vi.importActual<typeof import('./creator-review-api')>('./creator-review-api');
  const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');
  const owner:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=> 'synthetic-token'};
  const review=transcript('waiting'),item=review.review_queue!.items![0],kind=`creator-review:${sid}`as const;
  const pending:PendingReviewDecision={key:'review-synthetic-conflict-key',request:{schema_version:'1.0',expected_source_transcript_version:review.source!.source_transcript_version,
    source_segment_id:item.source_segment_id,expected_source_segment_version:item.source_segment_version,translation_id:item.translation_id,
    expected_translation_version:item.translation_version,decision:'accepted'}};
  const address=editorAddress(wid,kind);await access.journal.load(address);await access.journal.persist(address,editorDraft(wid,kind,pending,pending.key));
  const decisions:Record<string,unknown>[]=[];
  vi.stubGlobal('fetch',vi.fn(async(_input:unknown,init:RequestInit)=>{
    const request=JSON.parse(String(init.body));
    if(request.operation.kind==='creator_review')return Response.json({workspace_id:wid,session_id:sid,operation:'creator_review',receipt:review},{headers:{'Cache-Control':'no-store'}});
    decisions.push(request);return Response.json({code:'capture_session_changed'},{status:409,headers:{'Cache-Control':'no-store'}});
  }));
  vi.mocked(creatorReviewApi).mockReturnValue(actual.creatorReviewApi(wid,sid,owner));
  await mount(owner);await vi.waitFor(()=>expect(host.querySelector('[data-review-action="retry"]')).not.toBeNull());
  await act(async()=>host.querySelector<HTMLButtonElement>('[data-review-action="retry"]')!.click());
  await vi.waitFor(()=>expect(host.textContent).toContain('The review changed. Check the current version before deciding again.'));
  expect(decisions).toEqual([{session_id:sid,idempotency_key:pending.key,operation:{kind:'decide_translation',payload:pending.request}}]);
  expect(await access.journal.load(address)).toBeNull();expect(host.querySelector('[data-review-action="retry"]')).toBeNull();
  expect(continueToNote).not.toHaveBeenCalled();expect(lock).toHaveBeenLastCalledWith(false);
});

it('waits for matching recovery access without reading another notebook and drops late owner responses',async()=>{
  await mount(identity,null);expect(availability).toHaveBeenLastCalledWith('loading');expect(creatorReviewApi).not.toHaveBeenCalled();
  await mount(identity,{...access,workspaceId:sid});expect(availability).toHaveBeenLastCalledWith('unavailable');expect(creatorReviewApi).not.toHaveBeenCalled();
  let reject!:(cause:unknown)=>void;read.mockImplementationOnce(()=>new Promise((_resolve,no)=>reject=no));
  await mount();await vi.waitFor(()=>expect(read).toHaveBeenCalledOnce());
  await mount({...identity},null);const observed=availability.mock.calls.length;
  await act(async()=>reject(new Error('old owner private failure')));
  expect(availability.mock.calls.length).toBe(observed);expect(availability).toHaveBeenLastCalledWith('loading');
  expect(source).toHaveBeenLastCalledWith(null);expect(host.textContent).not.toContain('old owner private failure');expect(lock).toHaveBeenLastCalledWith(false);
});
