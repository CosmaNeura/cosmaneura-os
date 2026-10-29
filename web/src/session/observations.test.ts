// @vitest-environment node
import {afterEach,describe,expect,it,vi} from 'vitest';
import {pendingWorkspace} from '../model-work-test-fixture';
import type {Workspace} from '../workspace-api';
import {WorkspaceSession} from './workspace-session';

afterEach(()=>vi.useRealTimers());
describe('session background observation',()=>{
  it('pauses hidden reads and performs one immediate read on returning to the foreground',async()=>{
    vi.useFakeTimers();const workspace=await pendingWorkspace(),read=vi.fn(async()=>workspace),session=new WorkspaceSession({observationRead:read});session.setWorkspace(workspace);session.setIdentity({boxId:'invented-box',actorId:'invented-owner'});
    let visible=false,changed=()=>{};const cleanup=session.observations.watch({visible:()=>visible,subscribeVisibility:listener=>{changed=listener;return()=>{};},modelFailure:vi.fn()});
    await vi.advanceTimersByTimeAsync(10000);expect(read).not.toHaveBeenCalled();visible=true;changed();await Promise.resolve();expect(read).toHaveBeenCalledOnce();
    visible=false;changed();await vi.advanceTimersByTimeAsync(10000);expect(read).toHaveBeenCalledOnce();cleanup?.();
  });
  it('drops a late result and stops polling immediately on session invalidation',async()=>{
    vi.useFakeTimers();const workspace=await pendingWorkspace();let finish!:(value:Workspace)=>void;
    const read=vi.fn(()=>new Promise<Workspace>(resolve=>{finish=resolve;})),session=new WorkspaceSession({observationRead:read});session.setWorkspace(workspace);session.setIdentity({boxId:'invented-box',actorId:'invented-owner'});
    const failure=vi.fn(),cleanup=session.observations.watch({visible:()=>true,subscribeVisibility:()=>()=>{},modelFailure:failure});
    vi.advanceTimersByTime(2000);expect(read).toHaveBeenCalledOnce();session.clear();finish({...workspace,revision:3});await Promise.resolve();await vi.advanceTimersByTimeAsync(10000);
    expect(session.getSnapshot().workspace).toBeNull();expect(failure).not.toHaveBeenCalled();expect(read).toHaveBeenCalledOnce();cleanup?.();
  });
  it('keeps working text and requests comparison when the saved notebook changes during model work',async()=>{
    vi.useFakeTimers();const workspace=await pendingWorkspace();const latest:Workspace={...workspace,revision:3,entries:[...workspace.entries,{id:'invented-new-note',kind:'scratchpad',revision:3,content:'Invented saved change',source_label:null,origin:'human',ticket:null,created_at:'2026-10-23T12:00:00Z'}]};
    const session=new WorkspaceSession({observationRead:async()=>latest});session.setWorkspace(workspace);session.setIdentity({boxId:'invented-box',actorId:'invented-owner'});session.setNote('Invented unsaved text');
    const cleanup=session.observations.watch({visible:()=>true,subscribeVisibility:()=>()=>{},modelFailure:vi.fn()});await vi.advanceTimersByTimeAsync(2000);
    expect(session.getSnapshot()).toMatchObject({workspace:latest,note:'Invented unsaved text',conflict:true});cleanup?.();
  });
  it('aborts the active read and removes host subscriptions on cleanup',async()=>{
    vi.useFakeTimers();const workspace=await pendingWorkspace(),remove=vi.fn();let signal:AbortSignal|undefined;
    const session=new WorkspaceSession({observationRead:async(_owner,_id,current)=>{signal=current;return new Promise(()=>{});}});session.setWorkspace(workspace);session.setIdentity({boxId:'invented-box',actorId:'invented-owner'});
    const cleanup=session.observations.watch({visible:()=>true,subscribeVisibility:()=>remove,modelFailure:vi.fn()});vi.advanceTimersByTime(2000);cleanup?.();
    expect(signal?.aborted).toBe(true);expect(remove).toHaveBeenCalledOnce();expect(vi.getTimerCount()).toBe(0);
  });
});
