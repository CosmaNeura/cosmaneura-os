import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {openDraftStore} from './draft-store';
import {DraftJournal,editorAddress} from './draft-journal';
import {NotebookTitleEditor} from './NotebookTitleEditor';
import type {AccountRecoveryAccess} from './account-recovery';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id='00000000-0000-4000-8000-000000000001',receiptId='00000000-0000-4000-8000-000000000002';
describe('durable notebook rename',()=>{
  let root:Root,container:HTMLDivElement,recovery:AccountRecoveryAccess;
  const identity={mode:'clerk_jwt' as const,getToken:vi.fn()},saved=vi.fn(),close=vi.fn(),denied=vi.fn();
  beforeEach(async()=>{vi.spyOn(workspaceApi,'read').mockResolvedValue({id,appointment_id:null,label:'Original',revision:0,entries:[],work_candidates:[],notebook:{title:'Original',title_revision:0,created_at:'2026-10-16T12:00:00+00:00'}});Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
    recovery={journal:new DraftJournal(await openDraftStore({scope:'e'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto:webcrypto})),authorize:vi.fn().mockResolvedValue(undefined)};
    container=document.createElement('div');document.body.append(container);root=createRoot(container);saved.mockClear();close.mockClear();denied.mockClear();
  });
  afterEach(async()=>{await act(async()=>root.unmount());recovery.journal.close();container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
  async function wait(check:()=>boolean){for(let n=0;n<100&&!check();n++)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});expect(check()).toBe(true);}
  const button=(label:string)=>[...container.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent===label)!;
  async function mount(){await act(async()=>root.render(<NotebookTitleEditor identity={identity} recovery={recovery} workspaceId={id} title="Original" titleRevision={0} onSaved={saved} onClose={close} onAccessLost={denied}/>));await wait(()=>!container.querySelector<HTMLInputElement>('input')!.disabled||!!button('Check saved rename'));}
  async function type(){const input=container.querySelector('input')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'Yesterday’s synthetic visit');input.dispatchEvent(new Event('input',{bubbles:true}));});}
  it('persists before dispatch, restores a lost response, and resolves without another rename',async()=>{
    const rename=vi.spyOn(workspaceApi,'renameNotebook').mockImplementation(async(_identity,wid,body)=>{expect(await recovery.journal.load(editorAddress(wid,'notebook-title'))).toMatchObject({pending:body.idempotency_key,data:{pending:body}});throw new WorkspaceApiError(503);});
    await mount();await type();await act(async()=>button('Save title').click());await wait(()=>!!button('Check saved rename'));
    const body=rename.mock.calls[0][2],receipt={contract_version:1 as const,workspace_id:id,title:body.title,title_revision:1,receipt_id:receiptId};
    const resolve=vi.spyOn(workspaceApi,'resolveNotebookTitle').mockResolvedValue({contract_version:1,outcome:'saved',receipt});
    await act(async()=>root.unmount());root=createRoot(container);await mount();await act(async()=>button('Check saved rename').click());await wait(()=>saved.mock.calls.length===1);
    expect(resolve).toHaveBeenCalledExactlyOnceWith(identity,id,body);expect(rename).toHaveBeenCalledOnce();expect(saved).toHaveBeenCalledExactlyOnceWith(receipt);expect(await recovery.journal.load(editorAddress(id,'notebook-title'))).toBeNull();
  });
  it('checks absence before an explicit same-request retry',async()=>{
    const rename=vi.spyOn(workspaceApi,'renameNotebook').mockRejectedValueOnce(new WorkspaceApiError(503));
    vi.spyOn(workspaceApi,'resolveNotebookTitle').mockResolvedValue({contract_version:1,outcome:'not_found',receipt:null});
    await mount();await type();await act(async()=>button('Save title').click());await wait(()=>!!button('Check saved rename'));const body=rename.mock.calls[0][2];
    await act(async()=>button('Check saved rename').click());expect(rename).toHaveBeenCalledOnce();expect(saved).not.toHaveBeenCalled();
    rename.mockResolvedValue({contract_version:1,workspace_id:id,title:body.title,title_revision:1,receipt_id:receiptId});await act(async()=>button('Retry same rename').click());await wait(()=>saved.mock.calls.length===1);
    expect(rename.mock.calls[1]).toEqual([identity,id,body]);
  });
  it('recovers a rejected stale version without repeatedly retrying the stale request',async()=>{
    const rename=vi.spyOn(workspaceApi,'renameNotebook').mockRejectedValueOnce(new WorkspaceApiError(409,'notebook_title_conflict'));
    vi.spyOn(workspaceApi,'resolveNotebookTitle').mockResolvedValue({contract_version:1,outcome:'not_found',receipt:null});
    vi.mocked(workspaceApi.read).mockResolvedValue({id,appointment_id:null,label:'Original',revision:0,entries:[],work_candidates:[],notebook:{title:'Other saved title',title_revision:1,created_at:'2026-10-16T12:00:00+00:00'}});
    await mount();await type();await act(async()=>button('Save title').click());await wait(()=>!!button('Check saved rename'));
    await act(async()=>button('Check saved rename').click());expect(button('Retry same rename')).toBeUndefined();expect(container.textContent).toContain('Other saved title');
    await act(async()=>button('Use current title version').click());await wait(()=>!container.querySelector<HTMLInputElement>('input')!.disabled);
    expect(container.querySelector<HTMLInputElement>('input')!.value).toBe('Yesterday’s synthetic visit');expect(await recovery.journal.load(editorAddress(id,'notebook-title'))).toBeNull();
    rename.mockResolvedValue({contract_version:1,workspace_id:id,title:'Yesterday’s synthetic visit',title_revision:2,receipt_id:receiptId});
    await act(async()=>button('Save title').click());await wait(()=>saved.mock.calls.length===1);
    expect(rename.mock.calls[1][2].expected_title_revision).toBe(1);expect(rename.mock.calls[1][2].idempotency_key).not.toBe(rename.mock.calls[0][2].idempotency_key);
  });

});
