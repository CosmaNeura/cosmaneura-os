import {act,createElement,useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {DraftJournal} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import type {EditorRecoveryAccess} from '../editor-recovery';
import {notifyNativeWorkspaceForeground} from '../native-workspace-foreground';
import {useGoogleNativeForeground} from '../use-google-native-foreground';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from '../workspace-api';
import {teamFixture,teamUuid} from '../team-setup-test-fixture';
import {WorkspaceSession} from './workspace-session';

const base:Workspace={id:teamUuid(4701),label:'Invented calendar visit',appointment_id:teamUuid(4702),revision:2,entries:[],work_candidates:[]};
const changed=(revision:number,withheld=false):Workspace=>({...base,revision,entries:[{
  id:teamUuid(4703),kind:'calendar_import_source',revision:2,content:withheld?'':'Invented imported summary',
  source_label:withheld?'Unavailable calendar import':'Imported calendar snapshot',calendar_import_source_state:withheld?'unavailable':'current',
  origin:'authenticated_human',ticket:null,created_at:'2026-10-25T12:00:00Z',
}]});
function deferred<T>(){let resolve!:(value:T)=>void,reject!:(error:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
async function fixture(native=false){
  const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null,...(native?{nativeSession:{revision:teamUuid(4704),isCurrent:()=>true}}:{})};
  const team={...teamFixture(),recovery_scope:'a'.repeat(64)},read=vi.fn(async()=>base),readTeam=vi.fn(async()=>team);
  const session=new WorkspaceSession({recovery:{team:readTeam,read}});session.setIdentity(identity);session.setWorkspace(base);session.setTeam(team);
  const journal=new DraftJournal(await memoryDraftStorage()({scope:'b'.repeat(64)}));
  session.recovery.journal.current={scope:'b'.repeat(64),serverScope:team.recovery_scope,value:journal};
  const access=()=>session.recovery.editorAccess(identity,team.recovery_scope,journal,base.id,true,false,vi.fn())!;
  return {identity,session,journal,read,readTeam,access};
}
const stale={status:409,code:'workspace_revision_conflict'};
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

describe('editor authorization workspace publication',()=>{
  it.each([false,true])('rejects an older response after a newer read publishes (same revision: %s)',async sameRevision=>{
    const f=await fixture(),old=deferred<Workspace>(),fresh=deferred<Workspace>();
    f.read.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const prior=f.access().authorize().catch(e=>e);await vi.waitFor(()=>expect(f.read).toHaveBeenCalledTimes(1));
    // Replacement access handles must share the publication fence.
    const next=f.access().authorize();await vi.waitFor(()=>expect(f.read).toHaveBeenCalledTimes(2));
    const current=changed(sameRevision?2:3,true);fresh.resolve(current);expect(await next).toBe(current);
    old.resolve(changed(2));expect(await prior).toMatchObject(stale);
    expect(f.session.getSnapshot().workspace).toBe(current);expect(f.session.getSnapshot().conflict).toBe(false);
  });

  it('publishes a fresh equal-revision withholding update',async()=>{
    const f=await fixture(),visible=changed(2),hidden=changed(2,true);f.session.setWorkspace(visible);f.read.mockResolvedValueOnce(hidden);
    expect(await f.access().authorize()).toBe(hidden);expect(f.session.getSnapshot().workspace).toBe(hidden);
  });

  it('keeps a newer workspace published by another source reader',async()=>{
    const f=await fixture(),read=deferred<Workspace>();f.read.mockReturnValueOnce(read.promise);
    const pending=f.access().authorize().catch(e=>e);await vi.waitFor(()=>expect(f.read).toHaveBeenCalledOnce());
    const current=changed(4,true);f.session.sources.receive(current);read.resolve(changed(3));
    expect(await pending).toMatchObject(stale);expect(f.session.getSnapshot().workspace).toBe(current);
  });

  it('does not revive an old response after a newer authorization was refused',async()=>{
    const f=await fixture(),read=deferred<Workspace>();f.read.mockReturnValueOnce(read.promise);
    const pending=f.access().authorize().catch(e=>e);await vi.waitFor(()=>expect(f.read).toHaveBeenCalledOnce());
    const denied=new WorkspaceApiError(403);f.readTeam.mockRejectedValueOnce(denied);
    await expect(f.access().authorize()).rejects.toBe(denied);read.resolve(changed(3));
    expect(await pending).toMatchObject(stale);expect(f.session.getSnapshot().workspace).toBe(base);
  });

  it('allows an earlier completed read while a later read is still pending',async()=>{
    const f=await fixture(),first=deferred<Workspace>(),second=deferred<Workspace>();
    f.read.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const a=f.access().authorize();await vi.waitFor(()=>expect(f.read).toHaveBeenCalledTimes(1));
    const b=f.access().authorize();await vi.waitFor(()=>expect(f.read).toHaveBeenCalledTimes(2));
    const visible=changed(3),hidden=changed(3,true);first.resolve(visible);expect(await a).toBe(visible);
    second.resolve(hidden);expect(await b).toBe(hidden);expect(f.session.getSnapshot().workspace).toBe(hidden);
  });

  it.each(['generation','journal','visit','scope'] as const)('retains the %s authority boundary',async boundary=>{
    const f=await fixture(),read=deferred<Workspace>();f.read.mockReturnValueOnce(read.promise);
    if(boundary==='scope')f.readTeam.mockResolvedValueOnce({...await f.readTeam(),recovery_scope:'c'.repeat(64)});
    const pending=f.access().authorize().catch(e=>e);
    if(boundary!=='scope'){
      await vi.waitFor(()=>expect(f.read).toHaveBeenCalledOnce());
      if(boundary==='generation')f.session.invalidate();
      if(boundary==='journal')f.session.recovery.journal.current=null;
      if(boundary==='visit')f.session.setWorkspace({...base,id:teamUuid(4799)});
      read.resolve(changed(3));
    }
    expect(await pending).toMatchObject({status:403});expect(f.session.getSnapshot().workspace?.revision).toBe(2);
  });

  it('keeps a native return reload after the pre-background read settles late',async()=>{
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
    const f=await fixture(true),old=deferred<Workspace>(),fresh=deferred<Workspace>(),errors:unknown[]=[];
    f.read.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const access=f.access();
    function Editor({access}:{access:EditorRecoveryAccess}){
      const [reload,setReload]=useState(0);
      useGoogleNativeForeground(f.identity,{suspended:()=>{},resumed:()=>setReload(n=>n+1)});
      useEffect(()=>{void access.authorize().catch(e=>errors.push(e));},[access,reload]);
      return null;
    }
    const host=document.createElement('div'),root=createRoot(host);document.body.append(host);
    try{
      await act(async()=>root.render(createElement(Editor,{access})));await vi.waitFor(()=>expect(f.read).toHaveBeenCalledTimes(1));
      await act(async()=>notifyNativeWorkspaceForeground(f.identity,false));
      await act(async()=>notifyNativeWorkspaceForeground(f.identity,true));await vi.waitFor(()=>expect(f.read).toHaveBeenCalledTimes(2));
      const hidden=changed(2,true);await act(async()=>fresh.resolve(hidden));await act(async()=>old.resolve(changed(2)));
      await vi.waitFor(()=>expect(errors).toHaveLength(1));expect(errors[0]).toMatchObject(stale);
      expect(f.session.getSnapshot().workspace).toBe(hidden);
    }finally{await act(async()=>root.unmount());host.remove();}
  });
});
