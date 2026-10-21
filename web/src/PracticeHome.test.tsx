import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {PracticeHome,type StartPrivateRecording} from './PracticeHome';
import {DraftJournal,accountEditorAddress,editorAddress} from './draft-journal';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {openDraftStore} from './draft-store';
import type {AccountRecoveryAccess} from './account-recovery';
import {workspaceApi,WorkspaceApiError,type ProviderTeam,type Workspace} from './workspace-api';
import {validatePrivateDraftRecovery,validatePrivateDraftLinkRecovery} from './private-draft-recovery';
import type {PrivateRecordingSnapshot} from './private-recording-runtime';
import {WorkspaceConnectionRecoveryContext} from './PracticeAccessGate';
import {workspaceProtocolGeneration} from './workspace-protocol';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},configuration:{practice_context:'',bots:[{role:'chief',name:'Chief',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[{role:'chief',agent_id:id(10),name:'Chief',initials:'Ch',description:'Prepare private drafts',prompt:'Saved context',capabilities:[]}]};
const workspace:Workspace={id:id(1),appointment_id:null,label:'Private note',revision:0,entries:[],work_candidates:[],private_draft:{title:'Private note',state:'unlinked',link_receipt_id:null,linked_at:null}};
describe('practice Quick start recovery',()=>{
  let root:Root,container:HTMLDivElement,recovery:AccountRecoveryAccess;
  const identity={mode:'clerk_jwt' as const,getToken:vi.fn()},opened=vi.fn(),useTeam=vi.fn(),settings=vi.fn();
  beforeEach(async()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);vi.clearAllMocks();
    // fake-indexeddb and Node WebCrypto return Node-realm binary objects.
    vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
    recovery={journal:new DraftJournal(await openDraftStore({scope:'a'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto:webcrypto})),authorize:vi.fn().mockResolvedValue(undefined)};
    vi.spyOn(workspaceApi,'catalog').mockResolvedValue([]);
    vi.spyOn(workspaceApi,'privateDraftSummaries').mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    vi.spyOn(workspaceApi,'createPrivateDraft').mockResolvedValue({identity,workspace:structuredClone(workspace),team:structuredClone(team)});
    vi.spyOn(workspaceApi,'resolvePrivateDraft').mockResolvedValue({contract_version:1,outcome:'saved',workspace:structuredClone(workspace)});
    vi.spyOn(workspaceApi,'openPrivateDraft').mockResolvedValue({identity,workspace:structuredClone(workspace),team:structuredClone(team)});
    container=document.createElement('div');document.body.append(container);root=createRoot(container);
  });
  afterEach(async()=>{await act(async()=>root.unmount());recovery.journal.close();container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
  async function render(member=identity,configured=team){
    const reads=vi.mocked(workspaceApi.privateDraftSummaries).mock.calls.length;
    await act(async()=>root.render(<PracticeHome identity={member} recovery={recovery} team={configured} locked={false} onUseTeam={useTeam} onSettings={settings} onVisits={vi.fn()} onConnections={vi.fn()} onPracticeWork={vi.fn()} onOpened={opened} onAccessLost={vi.fn()} onBusyChange={vi.fn()}/>));
    for(let attempt=0;attempt<100&&vi.mocked(workspaceApi.privateDraftSummaries).mock.calls.length===reads;attempt++)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});
    expect(vi.mocked(workspaceApi.privateDraftSummaries).mock.calls.length).toBeGreaterThan(reads);
  }
  async function click(label:string,heldReply=false){
    const button=[...container.querySelectorAll('button')].find(b=>b.textContent===label)!;expect(button,label).toBeTruthy();expect(button.disabled).toBe(false);
    const calls=vi.mocked(workspaceApi.createPrivateDraft).mock.calls.length;
    await act(async()=>button.click());
    if(label==='Start a private note'||label==='Retry same note creation'){
      for(let attempt=0;attempt<100&&vi.mocked(workspaceApi.createPrivateDraft).mock.calls.length===calls;attempt++)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});
      expect(vi.mocked(workspaceApi.createPrivateDraft).mock.calls.length).toBe(calls+1);
    }
    if(!heldReply)for(let attempt=0;attempt<100&&container.textContent?.includes('Checking…');attempt++)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});
  }
  it('offers the offline sample on signed Home without starting a notebook or an outside action',async()=>{
    await render();await click('Try a sample');expect(container.querySelector('[role="dialog"]')).toBeTruthy();
    expect(container.textContent).toContain('The note and teammate drafts are prepared examples');
    expect(workspaceApi.createPrivateDraft).not.toHaveBeenCalled();expect(opened).not.toHaveBeenCalled();
  });
  it('opens an actual API-backed private notebook without an appointment or provider read',async()=>{
    await render();expect(workspaceApi.createPrivateDraft).not.toHaveBeenCalled();await click('Start a private note');
    const body=vi.mocked(workspaceApi.createPrivateDraft).mock.calls[0][1];expect(body).toMatchObject({title:'Private note'});
    expect(opened).toHaveBeenCalledExactlyOnceWith({identity,workspace,team});expect(await recovery.journal.load(accountEditorAddress('private-draft'))).toBeNull();
  });
  it('retains a lost reply through remount and resolves the same request without another create',async()=>{
    vi.mocked(workspaceApi.createPrivateDraft).mockRejectedValueOnce(new WorkspaceApiError(503));await render();await click('Start a private note');
    const body=vi.mocked(workspaceApi.createPrivateDraft).mock.calls[0][1];expect(container.textContent).toContain('unconfirmed');
    await act(async()=>root.unmount());root=createRoot(container);await render();await click('Check saved note creation');
    expect(workspaceApi.resolvePrivateDraft).toHaveBeenCalledExactlyOnceWith(identity,body);expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();expect(opened).toHaveBeenCalledOnce();
  });
  it('retains the exact encrypted create when fresh post-create authority is denied',async()=>{
    await render();
    vi.mocked(recovery.authorize).mockResolvedValueOnce(undefined).mockRejectedValueOnce(new WorkspaceApiError(403));
    await click('Start a private note');
    const body=vi.mocked(workspaceApi.createPrivateDraft).mock.calls[0][1];
    const saved=await recovery.journal.load(accountEditorAddress('private-draft'));
    expect(saved).toMatchObject({kind:'account-editor',editor:'private-draft',pending:body.idempotency_key,data:{pending:body}});
    expect(opened).not.toHaveBeenCalled();expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();
    expect(workspaceApi.resolvePrivateDraft).not.toHaveBeenCalled();
  });
  it('keeps the original creation after not_found and requires an explicit same-key retry',async()=>{
    vi.mocked(workspaceApi.createPrivateDraft).mockRejectedValueOnce(new WorkspaceApiError(503));
    vi.mocked(workspaceApi.resolvePrivateDraft).mockResolvedValueOnce({contract_version:1,outcome:'not_found',workspace:null});
    await render();await click('Start a private note');const body=vi.mocked(workspaceApi.createPrivateDraft).mock.calls[0][1];
    await click('Check saved note creation');expect(opened).not.toHaveBeenCalled();expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();
    expect((await recovery.journal.load(accountEditorAddress('private-draft')))?.pending).toBe(body.idempotency_key);
    await click('Retry same note creation');expect(workspaceApi.createPrivateDraft).toHaveBeenLastCalledWith(identity,body);expect(opened).toHaveBeenCalledOnce();
  });
  it('refreshes only Home lists after explicit same-owner reconnect while retaining an unconfirmed private creation',async()=>{
    const retry=vi.fn(),protocolGeneration=workspaceProtocolGeneration(identity);
    vi.mocked(workspaceApi.privateDraftSummaries).mockRejectedValueOnce(new WorkspaceApiError(503,'workspace_protocol_required'));
    vi.mocked(workspaceApi.catalog).mockRejectedValueOnce(new WorkspaceApiError(503,'workspace_protocol_required'));
    async function draw(sequence:number,phase:'ready'|'blocked',owner=identity){await act(async()=>root.render(
      <WorkspaceConnectionRecoveryContext.Provider value={{identity:owner,sequence,generation:protocolGeneration,phase,busy:false,retry}}>
        <PracticeHome identity={identity} recovery={recovery} team={team} locked={false} onUseTeam={useTeam} onSettings={settings} onVisits={vi.fn()} onConnections={vi.fn()} onPracticeWork={vi.fn()} onOpened={opened} onAccessLost={vi.fn()} onBusyChange={vi.fn()}/>
      </WorkspaceConnectionRecoveryContext.Provider>));}
    await draw(0,'ready');await vi.waitFor(async()=>{await act(async()=>{});expect(container.textContent).toContain('Recent notes could not be loaded');});
    vi.mocked(workspaceApi.createPrivateDraft).mockRejectedValueOnce(new WorkspaceApiError(503));await click('Start a private note');
    const request=vi.mocked(workspaceApi.createPrivateDraft).mock.calls[0][1],retained=await recovery.journal.load(accountEditorAddress('private-draft'));
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});vi.mocked(workspaceApi.catalog).mockResolvedValue([]);
    await draw(0,'blocked');await draw(0,'ready');expect(workspaceApi.privateDraftSummaries).toHaveBeenCalledOnce();
    await draw(1,'ready',{mode:'clerk_jwt',getToken:vi.fn()});expect(workspaceApi.privateDraftSummaries).toHaveBeenCalledOnce();
    await draw(1,'ready');await vi.waitFor(async()=>{await act(async()=>{});expect(container.textContent).toContain('No private notes yet.');});
    expect(workspaceApi.privateDraftSummaries).toHaveBeenCalledTimes(2);expect(workspaceApi.catalog).toHaveBeenCalledTimes(2);
    expect(container.textContent).not.toContain('Recent notes could not be loaded');expect(container.textContent).toContain('note creation is unconfirmed');
    expect(await recovery.journal.load(accountEditorAddress('private-draft'))).toEqual(retained);
    expect(workspaceApi.createPrivateDraft).toHaveBeenCalledExactlyOnceWith(identity,request);expect(workspaceApi.resolvePrivateDraft).not.toHaveBeenCalled();expect(opened).not.toHaveBeenCalled();
    await draw(1,'ready');expect(workspaceApi.privateDraftSummaries).toHaveBeenCalledTimes(2);
  });
  it('withholds former-account late results and never opens their notebook',async()=>{
    let finish!:(value:Awaited<ReturnType<typeof workspaceApi.createPrivateDraft>>)=>void;
    vi.mocked(workspaceApi.createPrivateDraft).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));await render();await click('Start a private note',true);
    const next={mode:'clerk_jwt' as const,getToken:vi.fn()};await render(next);await act(async()=>finish({identity,workspace,team}));expect(opened).not.toHaveBeenCalled();
  });
  it('filters recent notes by title, patient and real review state while showing dates and actions',async()=>{
    const base={workspace_id:id(201),title:'Yesterday’s synthetic note',title_revision:0,revision:2,created_at:'2026-10-15T15:00:00Z',updated_at:'2026-10-15T16:00:00Z',link_state:'linked' as const,appointment_id:id(301),patient_label:'Invented Rowan',visit_at:'2026-10-15T15:00:00Z',note_state:'needs_review' as const,duration_seconds:90,recording_state:'finished' as const};
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[base,{...base,workspace_id:id(202),title:'Other note',patient_label:'Invented Ash',note_state:'reviewed'}],has_more:false});
    await render();const rows=()=>container.querySelectorAll('.notebook-list-row');expect(rows()).toHaveLength(2);expect(rows()[0].textContent).toContain('Invented Rowan');expect(rows()[0].textContent).toContain('1:30 recording');expect(rows()[0].querySelector('time')?.dateTime).toBe(base.updated_at);
    const search=container.querySelector<HTMLInputElement>('.notebook-list-tools input[type=search]')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(search,'Rowan');search.dispatchEvent(new Event('input',{bubbles:true}));});expect(rows()).toHaveLength(1);
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(search,'');search.dispatchEvent(new Event('input',{bubbles:true}));container.querySelector<HTMLInputElement>('.notebook-list-tools input[type=checkbox]')!.click();});expect(rows()).toHaveLength(1);expect(rows()[0].textContent).toContain('Needs review');
    expect([...rows()[0].querySelectorAll('button')].map(button=>button.textContent)).toContain('Rename');
  });
  it('offers safe team activation without per-bot forms or automatic save',async()=>{await render(identity,{...team,revision:0});expect(useTeam).not.toHaveBeenCalled();await click('Use this team');expect(useTeam).toHaveBeenCalledOnce();expect(container.querySelectorAll('.practice-quick-start input').length).toBe(1);});
  it('opens Scribe before catalog readiness and caches the background exact create without navigating',async()=>{
    const record=vi.fn();let finish!:(value:Awaited<ReturnType<typeof workspaceApi.createPrivateDraft>>)=>void;
    vi.mocked(workspaceApi.createPrivateDraft).mockImplementationOnce(()=>new Promise(resolve=>finish=resolve));
    await act(async()=>root.render(<PracticeHome identity={identity} recovery={recovery} team={team} locked={false} onRecord={record} onUseTeam={useTeam} onSettings={settings} onVisits={vi.fn()} onConnections={vi.fn()} onPracticeWork={vi.fn()} onOpened={opened} onAccessLost={vi.fn()} onBusyChange={vi.fn()}/>));
    await click('Start recording');expect(record).toHaveBeenCalledOnce();expect(workspaceApi.createPrivateDraft).not.toHaveBeenCalled();
    const input=record.mock.calls[0][0] as StartPrivateRecording;expect(input.title).toMatch(/^Visit recording · /);let first!:Promise<Awaited<ReturnType<typeof workspaceApi.createPrivateDraft>>>;
    await act(async()=>{first=input.prepareNotebook('Synthetic cardiometabolic visit');expect(input.prepareNotebook('Another title')).toBe(first);});
    for(let n=0;n<100&&!vi.mocked(workspaceApi.createPrivateDraft).mock.calls.length;n++)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});
    expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();const body=vi.mocked(workspaceApi.createPrivateDraft).mock.calls[0][1];expect(body.title).toBe('Synthetic cardiometabolic visit');
    expect((await recovery.journal.load(accountEditorAddress('private-draft')))?.pending).toBe(body.idempotency_key);
    await act(async()=>{finish({identity,workspace,team});await first;});expect(opened).not.toHaveBeenCalled();expect(await recovery.journal.load(accountEditorAddress('private-draft'))).toBeNull();
  });
  it('allows local Scribe entry while retaining an earlier uncertain note without a duplicate create',async()=>{
    vi.mocked(workspaceApi.createPrivateDraft).mockRejectedValueOnce(new WorkspaceApiError(503));await render();await click('Start a private note');
    const body=vi.mocked(workspaceApi.createPrivateDraft).mock.calls[0][1],record=vi.fn();
    await act(async()=>root.render(<PracticeHome identity={identity} recovery={recovery} team={team} locked={false} onRecord={record} onUseTeam={useTeam} onSettings={settings} onVisits={vi.fn()} onConnections={vi.fn()} onPracticeWork={vi.fn()} onOpened={opened} onAccessLost={vi.fn()} onBusyChange={vi.fn()}/>));
    await click('Start recording');const input=record.mock.calls[0][0] as StartPrivateRecording;
    await act(async()=>{await expect(input.prepareNotebook()).rejects.toMatchObject({status:503});});expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();
    expect((await recovery.journal.load(accountEditorAddress('private-draft')))?.pending).toBe(body.idempotency_key);expect(workspaceApi.resolvePrivateDraft).not.toHaveBeenCalled();
  });
  it('consumes sidebar Scribe requests once, waits for unlock and does not replay a former identity request',async()=>{
    const record=vi.fn();async function request(number:number,locked:boolean,member=identity){await act(async()=>root.render(<PracticeHome identity={member} recovery={recovery} team={team} locked={locked} openRecordingRequest={number} onRecord={record} onUseTeam={useTeam} onSettings={settings} onVisits={vi.fn()} onConnections={vi.fn()} onPracticeWork={vi.fn()} onOpened={opened} onAccessLost={vi.fn()} onBusyChange={vi.fn()}/>));}
    await request(0,false);expect(record).not.toHaveBeenCalled();await request(1,true);expect(record).not.toHaveBeenCalled();await request(1,false);expect(record).toHaveBeenCalledOnce();
    await request(1,false);expect(record).toHaveBeenCalledOnce();const next={mode:'clerk_jwt' as const,getToken:vi.fn()};await request(1,false,next);expect(record).toHaveBeenCalledOnce();await request(2,false,next);expect(record).toHaveBeenCalledTimes(2);expect(workspaceApi.createPrivateDraft).not.toHaveBeenCalled();
  });
  it('distinguishes same-title audio and empty stops while preserving uncertain stop recovery',async()=>{
    const saved:PrivateRecordingSnapshot={recordingId:id(101),title:'Private recording',createdAt:'2026-10-08T21:43:27.000Z',phase:'sealed',elapsedSeconds:18.704,recordedChunks:2,recordedBytes:598616,workspaceId:null,busy:false,localOnly:true,transcription:'not_requested',failure:null,startupStage:null};
    const rows=[saved,{...saved,recordingId:id(102),elapsedSeconds:96.5},{...saved,recordingId:id(103),elapsedSeconds:0,recordedChunks:0,recordedBytes:0},{...saved,recordingId:id(104),phase:'stop_unconfirmed' as const,elapsedSeconds:0,recordedChunks:0,recordedBytes:0}],reopen=vi.fn();
    await act(async()=>root.render(<PracticeHome identity={identity} recovery={recovery} team={team} locked={false} recordings={rows} onReopenRecording={reopen} onUseTeam={useTeam} onSettings={settings} onVisits={vi.fn()} onConnections={vi.fn()} onPracticeWork={vi.fn()} onOpened={opened} onAccessLost={vi.fn()} onBusyChange={vi.fn()}/>));
    const times=[...container.querySelectorAll<HTMLTimeElement>('[aria-label="Saved private recordings"] time')];expect(times).toHaveLength(4);expect(times[0].dateTime).toBe(saved.createdAt);
    const buttons=[...container.querySelectorAll<HTMLButtonElement>('[aria-label="Saved private recordings"] button')];
    expect(buttons.map(button=>`${button.querySelector('strong')?.textContent}${button.querySelector('span')?.textContent}`)).toEqual(['Private recording0:18 · Saved on this device · Private','Private recording1:36 · Saved on this device · Private','Private recording0:00 · Stopped · no audio captured · Private','Private recording0:00 · Check recording status · Private']);
    await act(async()=>buttons[1].click());expect(reopen).toHaveBeenCalledExactlyOnceWith(id(102));expect(workspaceApi.createPrivateDraft).not.toHaveBeenCalled();
  });
  it.each(['opened','failed'] as const)('shows the selected saved note opening before a held access check and settles it when %s',async outcome=>{
    const row={workspace_id:id(201),title:'Invented saved recording notebook',title_revision:0,revision:2,created_at:'2026-10-15T15:00:00Z',updated_at:'2026-10-15T16:00:00Z',link_state:'unlinked' as const,appointment_id:null,patient_label:null,visit_at:null,note_state:'draft' as const,duration_seconds:23,recording_state:'finished' as const};
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[row,{...row,workspace_id:id(202),title:'Another retained note'}],has_more:false});
    await render();let release!:()=>void,reject!:(cause:unknown)=>void;
    vi.mocked(recovery.authorize).mockClear().mockImplementation(()=>new Promise<void>((resolve,fail)=>{release=resolve;reject=fail;}));
    const selected=container.querySelector('.notebook-list-row')!,open=[...selected.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='Open')!;
    await act(async()=>{open.click();open.click();});
    expect(selected.querySelector('[role="status"]')?.textContent).toBe('Opening saved note…');
    expect(open.textContent).toBe('Opening…');expect(open.disabled).toBe(true);
    expect(container.querySelectorAll('.notebook-list-row [role="status"]')).toHaveLength(1);
    expect(recovery.authorize).toHaveBeenCalledOnce();expect(workspaceApi.openPrivateDraft).not.toHaveBeenCalled();expect(opened).not.toHaveBeenCalled();
    if(outcome==='opened'){
      await act(async()=>release());await vi.waitFor(()=>expect(opened).toHaveBeenCalledOnce());
      expect(workspaceApi.openPrivateDraft).toHaveBeenCalledExactlyOnceWith(identity,row.workspace_id);
    }else{
      await act(async()=>reject(new WorkspaceApiError(503)));await vi.waitFor(()=>expect(container.querySelector('[role="alert"]')?.textContent).toContain('could not be opened'));
      expect(workspaceApi.openPrivateDraft).not.toHaveBeenCalled();expect(opened).not.toHaveBeenCalled();
    }
    await vi.waitFor(()=>expect(selected.querySelector('[role="status"]')).toBeNull());
    expect(open.textContent).toBe('Open');expect(open.disabled).toBe(false);expect(selected.textContent).toContain(row.title);
  });
  it('withholds a late saved-note open result after the Home owner is replaced',async()=>{
    const row={workspace_id:id(201),title:'Invented retained note',title_revision:0,revision:2,created_at:'2026-10-15T15:00:00Z',updated_at:'2026-10-15T16:00:00Z',link_state:'unlinked' as const,appointment_id:null,patient_label:null,visit_at:null,note_state:'draft' as const,duration_seconds:23,recording_state:'finished' as const};
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[row],has_more:false});
    await render();let release!:(value:Awaited<ReturnType<typeof workspaceApi.openPrivateDraft>>)=>void;
    vi.mocked(workspaceApi.openPrivateDraft).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
    await click('Open',true);await vi.waitFor(()=>expect(workspaceApi.openPrivateDraft).toHaveBeenCalledOnce());
    expect(container.querySelector('.notebook-list-row [role="status"]')?.textContent).toBe('Opening saved note…');
    const next={mode:'clerk_jwt' as const,getToken:vi.fn()};await render(next);
    expect(container.querySelector('.notebook-list-row [role="status"]')).toBeNull();
    await act(async()=>release({identity,workspace,team}));
    expect(opened).not.toHaveBeenCalled();expect(container.querySelector('.notebook-list-row [role="status"]')).toBeNull();
    expect([...container.querySelectorAll<HTMLButtonElement>('.notebook-list-row button')].find(b=>b.textContent==='Open')?.disabled).toBe(false);
  });
  it('refuses added authority fields and mismatched encrypted request keys',async()=>{
    const body={title:'Private note',idempotency_key:id(5)},data={contract:'private-draft-recovery.v1' as const,title:'Private note',pending:body};
    expect(()=>validatePrivateDraftRecovery({...data,patient_id:id(9)})).toThrow();expect(()=>validatePrivateDraftRecovery({...data,pending:{...body,title:'Other'}})).toThrow();
    await recovery.journal.load(accountEditorAddress('private-draft'));
    await expect(recovery.journal.persist(accountEditorAddress('private-draft'),{kind:'account-editor',editor:'private-draft',data,pending:id(6)})).rejects.toMatchObject({code:'integrity'});
    const link={contract:'private-draft-link-recovery.v1',workspace_id:id(1),pending:{expected_revision:1,idempotency_key:id(6),appointment_id:id(7),appointment_link_confirmed:true}};
    expect(()=>validatePrivateDraftLinkRecovery({...link,pending:{...link.pending,appointment_link_confirmed:false}},id(1))).toThrow();
    await recovery.journal.load(editorAddress(id(1),'private-draft-link'));
    await expect(recovery.journal.persist(editorAddress(id(1),'private-draft-link'),{kind:'editor',workspaceId:id(1),editor:'private-draft-link',data:link,pending:id(8)})).rejects.toMatchObject({code:'integrity'});
  });
});
