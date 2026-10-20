import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CreatorReviewPanel} from './CreatorReviewPanel';
import {creatorReviewApi} from './creator-review-api';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {HttpCreatorReviewApi,type CreatorReviewView} from '../../clients/scribe-review/creator-review-api';
import type {AuthenticatedWorkspaceIdentity,Workspace} from './workspace-api';

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
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();host.remove();});

it('reports the real review failure while retaining an explicit refresh to the existing transcript',async()=>{
  read.mockRejectedValueOnce(new Error('private denied/session detail'));
  await mount();await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(source).toHaveBeenLastCalledWith(null);expect(host.textContent).toContain('This recording is unavailable');
  expect(host.textContent).not.toContain('private denied/session detail');expect(continueToNote).not.toHaveBeenCalled();
  await act(async()=>host.querySelector<HTMLButtonElement>('[data-review-action="refresh"]')!.click());
  await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('ready'));
  expect(source).toHaveBeenLastCalledWith(view);expect(read).toHaveBeenCalledTimes(2);expect(decide).not.toHaveBeenCalled();
});

it('clears a successful API snapshot if the exact encrypted review recovery cannot be read',async()=>{
  vi.spyOn(access.journal,'load').mockRejectedValueOnce(new Error('private journal detail'));
  await mount();await vi.waitFor(()=>expect(availability).toHaveBeenLastCalledWith('unavailable'));
  expect(source).toHaveBeenLastCalledWith(null);expect(host.textContent).toContain('This recording is unavailable');
  expect(host.textContent).not.toContain('private journal detail');expect(decide).not.toHaveBeenCalled();
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
