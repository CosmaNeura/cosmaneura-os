import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {MembershipWorkspaceMount} from './MembershipWorkMount';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {membershipApi} from './membership-api';
import {membershipFixture,membershipFixtureOptions,membershipHistoryOperations} from './membership-test-fixture';
import {emptyMembershipRecovery,type MembershipRecoveryRecord} from './membership-recovery';
import type {MembershipReviewBundle} from './membership-operation';
import {WorkspaceApiError} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-owner-token'};
describe('membership owner mount and existing private recovery',()=>{
 let root:Root,container:HTMLDivElement,journal:DraftJournal,context:EditorRecoveryAccess,current:MembershipReviewBundle;
 beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);current=await membershipFixture(3);journal=new DraftJournal(await memoryDraftStorage()({scope:'d'.repeat(64)}));context={journal,workspaceId:current.detail.scope.workspace_id,authorize:vi.fn(async()=>({id:current.detail.scope.workspace_id,appointment_id:current.detail.scope.workspace_id,label:'Invented encounter',revision:1,entries:[],work_candidates:[]})),denied:vi.fn()};
  container=document.createElement('div');document.body.append(container);root=createRoot(container);
  vi.spyOn(membershipApi,'bootstrap').mockImplementation(async()=>membershipFixtureOptions(current.detail));vi.spyOn(membershipApi,'options').mockImplementation(async()=>membershipFixtureOptions(current.detail));vi.spyOn(membershipApi,'catalog').mockImplementation(async()=>({contract_version:1,scope:current.detail.scope,items:[current.detail.summary]}));vi.spyOn(membershipApi,'detail').mockImplementation(async()=>current);vi.spyOn(membershipApi,'execute');vi.spyOn(membershipApi,'recover');
 });
 afterEach(async()=>{await act(async()=>root.unmount());container.remove();journal.close();vi.restoreAllMocks();vi.unstubAllGlobals();});
 const button=(label:string)=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent===label)!;
 const until=async(check:()=>void)=>{for(let i=0;i<150;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{}});if(done)return;}check();};
 const render=async(enabled=true,access:EditorRecoveryAccess|null=context,auth=identity)=>{await act(async()=>root.render(<EditorRecoveryContext.Provider value={access}><MembershipWorkspaceMount identity={auth} workspaceId={current.detail.scope.workspace_id} enabled={enabled}/></EditorRecoveryContext.Provider>));};
 const save=async(data:MembershipRecoveryRecord)=>{const address=editorAddress(current.detail.scope.workspace_id,'membership-work');await journal.load(address);await journal.persist(address,{kind:'editor',workspaceId:current.detail.scope.workspace_id,editor:'membership-work',pending:null,data});return address;};
 it('does not bootstrap, read recovery or show membership when the default-off gate is disabled',async()=>{await render(false);expect(container.textContent).toBe('');expect(context.authorize).not.toHaveBeenCalled();expect(membershipApi.bootstrap).not.toHaveBeenCalled();});
 it('requires the current workspace recovery context before reading membership',async()=>{await render(true,null);expect(container.textContent).toContain('Checking private encounter access and recovery');expect(membershipApi.bootstrap).not.toHaveBeenCalled();await render(true,{...context,workspaceId:crypto.randomUUID()});expect(membershipApi.bootstrap).not.toHaveBeenCalled();});
 it('restores an exact pending verification through the existing journal with no automatic action or restored consent',async()=>{
  const ops=await membershipHistoryOperations(current.history),data={...emptyMembershipRecovery(current.detail.scope),pending:ops[2]};const address=await save(data);await render();await until(()=>expect(button('Restore membership draft')).toBeDefined());
  await act(async()=>button('Restore membership draft').click());await until(()=>expect(container.textContent).toContain('Private membership draft restored'));expect((await journal.load(address))?.kind).toBe('editor');
  expect(vi.mocked(context.authorize).mock.calls.length).toBeGreaterThanOrEqual(3);expect(membershipApi.execute).not.toHaveBeenCalled();expect(membershipApi.recover).not.toHaveBeenCalled();expect(container.querySelectorAll('input[type=checkbox]:checked')).toHaveLength(0);
 });
 it('rejects another owner scope in saved content before offering its private draft',async()=>{const data=emptyMembershipRecovery({...current.detail.scope,owner_id:crypto.randomUUID()});data.draft.result_evidence='Other owner private text';await save(data);await render();await until(()=>expect(container.textContent).toContain('Private recovery is unavailable'));expect(button('Restore membership draft')).toBeUndefined();expect(container.textContent).not.toContain('Other owner private text');expect(membershipApi.execute).not.toHaveBeenCalled();});
 it.each([401,403,404])('withholds private UI when current scope bootstrap denies access %s',async status=>{vi.mocked(membershipApi.bootstrap).mockRejectedValueOnce(new WorkspaceApiError(status));await render();await until(()=>expect(container.textContent).toContain('Private membership review could not be opened'));expect(context.denied).toHaveBeenCalled();expect(membershipApi.options).not.toHaveBeenCalled();expect(container.querySelector('textarea')).toBeNull();});
 it('discards late bootstrap from an earlier identity and reloads only current authority',async()=>{
  let release!:(v:ReturnType<typeof membershipFixtureOptions>)=>void;vi.mocked(membershipApi.bootstrap).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));await render();await until(()=>expect(membershipApi.bootstrap).toHaveBeenCalledTimes(1));
  const next={mode:'clerk_jwt' as const,getToken:async()=> 'different-invented-owner'};await render(true,context,next);await until(()=>expect(button('Refresh membership work')).toBeDefined());await act(async()=>release(membershipFixtureOptions(current.detail)));await until(()=>expect(vi.mocked(membershipApi.options).mock.calls.every(call=>call[0]===next)).toBe(true));expect(membershipApi.execute).not.toHaveBeenCalled();
 });
 it('retries failed bootstrap explicitly while preserving saved work',async()=>{vi.mocked(membershipApi.bootstrap).mockRejectedValueOnce(new WorkspaceApiError(503));const address=await save(emptyMembershipRecovery(current.detail.scope)),before=await journal.load(address);await render();await until(()=>expect(button('Retry opening membership review')).toBeDefined());await act(async()=>button('Retry opening membership review').click());await until(()=>expect(button('Restore membership draft')).toBeDefined());expect(await journal.load(address)).toEqual(before);expect(membershipApi.bootstrap).toHaveBeenCalledTimes(2);expect(membershipApi.execute).not.toHaveBeenCalled();});
});
