import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {ConversationEntries} from './ConversationEntries';
import {EditorRecoveryContext,editorDraft,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {DraftStoreError,openDraftStore,type DraftValue} from './draft-store';
import {answerCopyData} from './answer-copy-contract';
import {hasUnsavedWork} from './unsaved-work';
import type {ConversationProjection} from './session/entries';
import type {Workspace,WorkspaceEntry} from './workspace-api';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const wid='00000000-0000-4000-8000-000000000071',eid='00000000-0000-4000-8000-000000000072';
const original='## Invented visit summary\n\nConfirm the recorded history before use.\n';
const edited='## Edited invented visit summary\n\nClinician reviewed this invented wording, café.\n';
let root:Root,host:HTMLDivElement,idb:IDBFactory,journal:DraftJournal,access:EditorRecoveryAccess|null,workspace:Workspace,scope:string;
let failWrites:boolean,holdWrite:boolean,releaseWrite:(()=>void)|null;
const source=vi.fn(),check=vi.fn(),action=vi.fn(),work=vi.fn(),busyChanged=vi.fn(),denied=vi.fn(),writeClipboard=vi.fn(),fetcher=vi.fn();
const address=editorAddress(wid,`answer-copy:${eid}`);
const entry=():WorkspaceEntry=>({id:eid,revision:2,kind:'conversation',content:'Create an invented visit summary.',source_label:null,origin:'human',ticket:null,created_at:'2026-11-04T12:00:00Z',
 reply:{agent_name:'Chief',role:'chief',backend:'azure_gpt41',content:original,context_revision:1,citations:[{entry_id:'00000000-0000-4000-8000-000000000073',revision:1,label:'Invented saved notes',kind:'scratchpad'}]}});
async function newJournal(){
 const store=await openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
 journal=new DraftJournal({read:store.read,close:store.close,async write(id,expected,value:DraftValue|null){
   if(holdWrite){holdWrite=false;await new Promise<void>(resolve=>{releaseWrite=resolve;});}
   if(failWrites)throw new DraftStoreError('unavailable');return store.write(id,expected,value);
 }});
 access={journal,workspaceId:wid,recoveryScope:scope,authorize:vi.fn(async()=>workspace),denied};
}
async function show(locked=false){const turns=workspace.entries.filter(e=>e.reply),projection:ConversationProjection={workspaceId:workspace.id,botAddress:'chief',turns,entries:turns.map(e=>({kind:'turn',id:e.id,entry:e,reviewLabel:'Unreviewed draft',actions:[]}))};
 await act(async()=>root.render(<EditorRecoveryContext.Provider value={access}><ConversationEntries presentation="messages" projection={projection} latestSourceRevision={2} busy={false} recoveryBlocked={false} locked={locked} onWork={work} onSource={source} onCheck={check} onAction={action} onBusyChange={busyChanged}/></EditorRecoveryContext.Provider>));}
const button=(label:string)=>{const b=[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===label||b.getAttribute('aria-label')===label);expect(b,label).toBeTruthy();return b!;};
async function wait(assertion:()=>void|Promise<void>){for(let n=0;n<150;n++){let done=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,3));try{await assertion();done=true;}catch{}});if(done)return;}await assertion();}
async function click(label:string){await wait(()=>expect(button(label).disabled,label).toBe(false));await act(async()=>button(label).click());}
async function openEditor(){await act(async()=>host.querySelector<HTMLButtonElement>('.messages-source-details')!.click());await click('Edit a copy');}
async function fill(value:string){const field=host.querySelector<HTMLTextAreaElement>('.answer-copy-editor > label textarea')!;expect(field.disabled).toBe(false);await act(async()=>{
 Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function savedCopy(value:string){await wait(async()=>{expect(await journal.load(address)).toMatchObject({kind:'editor',editor:`answer-copy:${eid}`,pending:null,data:{content:value,originalContent:original}});expect(button('Copy edited copy').disabled).toBe(false);expect(hasUnsavedWork()).toBe(false);});}
async function reopen(){await act(async()=>root.unmount());journal.close();await newJournal();root=createRoot(host);await show();await openEditor();await wait(()=>expect(host.textContent).toContain('saved answer copy draft'));}
beforeEach(async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();scope='a'.repeat(64);failWrites=false;holdWrite=false;releaseWrite=null;workspace={id:wid,appointment_id:null,label:'Invented private notebook',revision:2,entries:[entry()],work_candidates:[]};
 for(const mock of [source,check,action,work,busyChanged,denied,writeClipboard,fetcher])mock.mockReset();writeClipboard.mockResolvedValue(undefined);vi.stubGlobal('navigator',{clipboard:{writeText:writeClipboard}});vi.stubGlobal('fetch',fetcher);
 await newJournal();host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{releaseWrite?.();await act(async()=>root.unmount());journal.close();host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('edits, encrypts, closes, reopens, restores and explicitly copies a private answer without changing the original or sending work',async()=>{
 await show();await openEditor();await savedCopy(original);await fill(edited);await savedCopy(edited);expect(writeClipboard).not.toHaveBeenCalled();
 const db=await new Promise<IDBDatabase>(resolve=>{const request=idb.open(`cosmas-private-drafts:v1:${scope}`);request.onsuccess=()=>resolve(request.result);});
 const sealed=await new Promise<{ciphertext:ArrayBuffer}>(resolve=>{const request=db.transaction('sealed-drafts').objectStore('sealed-drafts').get(address);request.onsuccess=()=>resolve(request.result);});
 expect(sealed.ciphertext).toBeInstanceOf(ArrayBuffer);expect(new TextDecoder().decode(sealed.ciphertext)).not.toContain('Clinician reviewed');db.close();expect(localStorage.length).toBe(0);
 await click('Close message details');expect(host.querySelector('[role=dialog]')).toBeNull();expect(workspace.entries[0].reply!.content).toBe(original);expect(workspace.note).toBeUndefined();
 await reopen();expect(host.textContent).toContain('saved answer copy draft');expect(button('Close message details').disabled).toBe(true);expect(button('Copy edited copy').disabled).toBe(true);expect(host.textContent).not.toContain(edited);
 await click('Restore answer copy draft');await savedCopy(edited);expect(access!.authorize).toHaveBeenCalledOnce();expect(host.querySelector<HTMLTextAreaElement>('.answer-copy-editor > label textarea')!.value).toBe(edited);
 await click('Copy edited copy');expect(writeClipboard).toHaveBeenCalledExactlyOnceWith(edited);await click('Finish editing');expect(button('Copy answer').disabled).toBe(false);await click('Close message details');
 expect(workspace.entries[0].reply!.content).toBe(original);expect(fetcher).not.toHaveBeenCalled();for(const fn of [source,check,action,work,denied])expect(fn).not.toHaveBeenCalled();
});

it('fences close, Escape, backdrop, citations and navigation during a write, then preserves the newest edit queued behind it',async()=>{
 workspace.entries.push({...entry(),id:'00000000-0000-4000-8000-000000000074',reply:{...entry().reply!,content:'Another invented Chief answer'}});
 await show();await openEditor();await savedCopy(original);holdWrite=true;await fill('First invented edit');await wait(()=>expect(releaseWrite).toBeTypeOf('function'));await fill(edited);
 expect(button('Close message details').disabled).toBe(true);expect(button('Invented saved notes').disabled).toBe(true);expect(button('Copy edited copy').disabled).toBe(true);expect(busyChanged).toHaveBeenLastCalledWith(true);expect(hasUnsavedWork()).toBe(true);
 const another=host.querySelectorAll<HTMLButtonElement>('.messages-source-details')[1];expect(another.disabled).toBe(true);
 await act(async()=>{another.click();button('Close message details').click();button('Invented saved notes').click();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));host.querySelector('.workspace-dialog-backdrop')!.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));});
 expect(host.querySelector('[role=dialog]')).not.toBeNull();expect(source).not.toHaveBeenCalled();await act(async()=>releaseWrite!());await savedCopy(edited);expect(busyChanged).toHaveBeenLastCalledWith(false);await click('Close message details');
});

it('retains failed volatile edits through recheck and recovery of an earlier saved copy before retrying storage',async()=>{
 await show();await openEditor();await savedCopy(original);failWrites=true;await fill(edited);await wait(()=>expect(host.textContent).toContain('Local editor storage is unavailable'));expect(button('Close message details').disabled).toBe(true);expect(host.querySelector<HTMLTextAreaElement>('.answer-copy-editor > label textarea')!.value).toBe(edited);
 failWrites=false;await click('Recheck answer copy recovery');await wait(()=>expect(host.textContent).toContain('saved answer copy draft'));expect(button('Close message details').disabled).toBe(true);
 await click('Restore answer copy draft');await savedCopy(edited);expect(host.querySelector<HTMLTextAreaElement>('.answer-copy-editor > label textarea')!.value).toBe(edited);await click('Copy edited copy');expect(writeClipboard).toHaveBeenCalledExactlyOnceWith(edited);expect(fetcher).not.toHaveBeenCalled();
});

it.each(['changed-content','changed-context','other-workspace','revoked-source'] as const)('withholds recovery under %s and retains the encrypted record until explicit discard',async change=>{
 await show();await openEditor();await savedCopy(original);await fill(edited);await savedCopy(edited);await reopen();
 const saved=structuredClone(workspace);if(change==='other-workspace')workspace={...saved,id:'00000000-0000-4000-8000-000000000081'};
 else if(change==='changed-content')workspace={...saved,entries:saved.entries.map(e=>({...e,reply:{...e.reply!,content:'A different invented answer'}}))};
 else if(change==='changed-context')workspace={...saved,entries:saved.entries.map(e=>({...e,reply:{...e.reply!,context_revision:9}}))};
 else workspace={...saved,entries:saved.entries.map(e=>({...e,ehr_source_state:'unavailable' as const}))};
 await click('Restore answer copy draft');await wait(()=>expect(denied).toHaveBeenCalled());expect(button('Copy edited copy').disabled).toBe(true);expect(button('Close message details').disabled).toBe(true);expect((await journal.load(address))?.kind).toBe('editor');expect(host.querySelector<HTMLTextAreaElement>('.answer-copy-editor > label textarea')!.value).toBe(original);expect(writeClipboard).not.toHaveBeenCalled();
 workspace=saved;await click('Discard answer copy draft');await savedCopy(original);expect(host.querySelector<HTMLTextAreaElement>('.answer-copy-editor > label textarea')!.value).toBe(original);expect(fetcher).not.toHaveBeenCalled();
});

it('isolates the same reply IDs in another authorized owner scope and never copies late success or manual fallback after a lock',async()=>{
 await show();await openEditor();await savedCopy(original);await fill(edited);await savedCopy(edited);await act(async()=>root.unmount());journal.close();scope='b'.repeat(64);await newJournal();root=createRoot(host);await show();await openEditor();await savedCopy(original);expect(host.textContent).not.toContain('saved answer copy draft');expect(access!.authorize).not.toHaveBeenCalled();
 let settle!:(()=>void);writeClipboard.mockImplementationOnce(()=>new Promise<void>(resolve=>{settle=resolve;}));await click('Copy edited copy');await show(true);await act(async()=>settle());expect(host.textContent).not.toContain('Copied to your clipboard');expect(host.querySelector('.message-copy-answer textarea')).toBeNull();await show(false);expect(button('Copy edited copy').disabled).toBe(false);
 writeClipboard.mockRejectedValueOnce(new DOMException('Denied','NotAllowedError'));await click('Copy edited copy');expect(host.querySelector<HTMLTextAreaElement>('.message-copy-answer textarea')!.readOnly).toBe(true);expect(host.querySelector<HTMLTextAreaElement>('.message-copy-answer textarea')!.value).toBe(original);await show(true);expect(button('Select edited copy').disabled).toBe(true);expect(fetcher).not.toHaveBeenCalled();
});

it('validates a separate UUID-addressed answer-copy kind, bounded exact data and null pending authority',async()=>{
 await journal.load(address);const draft=editorDraft(wid,`answer-copy:${eid}`,answerCopyData(entry(),edited));await journal.persist(address,draft);
 await expect(journal.load(editorAddress(wid,'answer-copy:not-a-uuid'))).rejects.toMatchObject({code:'invalid'});
 for(const bad of [{...draft,pending:eid},{...draft,data:{...answerCopyData(entry(),edited),entryId:wid}},{...draft,data:{...answerCopyData(entry(),edited),content:'x'.repeat(65537)}},{...draft,data:{...answerCopyData(entry(),edited),approved:true}}])await expect(journal.persist(address,bad)).rejects.toMatchObject({code:'integrity'});
 expect(await journal.load(address)).toEqual(draft);expect(fetcher).not.toHaveBeenCalled();
});

it('retains an oversized pasted copy for correction without failing storage or enabling copy and close',async()=>{
 await show();await openEditor();await savedCopy(original);const tooLong='é'.repeat(40000);await fill(tooLong);expect(host.textContent).toContain('too long to save');expect(button('Close message details').disabled).toBe(true);expect(button('Copy edited copy').disabled).toBe(true);expect(host.querySelector<HTMLTextAreaElement>('.answer-copy-editor > label textarea')!.disabled).toBe(false);
 expect((await journal.load(address))).toMatchObject({data:{content:original}});await fill(edited);await savedCopy(edited);expect(host.textContent).not.toContain('too long to save');expect(fetcher).not.toHaveBeenCalled();
});

it('requires the authorized encrypted recovery context before opening an editable copy',async()=>{
 access=null;await show();await act(async()=>host.querySelector<HTMLButtonElement>('.messages-source-details')!.click());expect(button('Edit a copy').disabled).toBe(true);await act(async()=>button('Edit a copy').click());expect(host.querySelector('.answer-copy-editor')).toBeNull();expect(button('Close message details').disabled).toBe(false);expect(journal.has(address)).toBe(false);expect(fetcher).not.toHaveBeenCalled();
});

it('offers editing only for the completed available Chief conversation, without turning other saved results into editable clinical records',async()=>{
 for(const changed of [{...entry(),reply:{...entry().reply!,role:'scribe' as const}},{...entry(),kind:'handoff_result' as const},{...entry(),reply:{...entry().reply!,backend:'azure_gpt41_unavailable'}},{...entry(),ehr_source_state:'unavailable' as const}]){
   workspace={...workspace,entries:[changed]};await show();await act(async()=>host.querySelector<HTMLButtonElement>('.messages-source-details')!.click());expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Edit a copy')).toBe(false);await click('Close message details');
 }
 expect(journal.has(address)).toBe(false);expect(fetcher).not.toHaveBeenCalled();
});
