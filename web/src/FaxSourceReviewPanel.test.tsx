import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.mock('./fax-inbound-source-api',async()=>({...await vi.importActual<Record<string,unknown>>('./fax-inbound-source-api'),faxSourceApi:{review:vi.fn(),resolve:vi.fn()}}));
vi.mock('./workspace-api',async()=>({...await vi.importActual<Record<string,unknown>>('./workspace-api'),workspaceApi:{read:vi.fn()}}));
import {FaxSourceReviewPanel,type FaxSourceReviewPanelProps} from './FaxSourceReviewPanel';
import {faxSourceApi,faxSourceRequestHash,FAX_SOURCE_LABEL,type FaxSourceReviewRequest,type FaxSourceReceipt} from './fax-inbound-source-api';
import {emptyFaxSourceRecovery,type FaxSourceRecovery} from './fax-inbound-source-recovery';
import {workspaceApi,WorkspaceApiError,type Workspace} from './workspace-api';
import {vendorSha256} from './vendor-contract';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0'),scope={box_id:uuid(1),owner_id:uuid(2),workspace_id:uuid(3)};
let root:Root,host:HTMLDivElement,props:FaxSourceReviewPanelProps,saved:FaxSourceRecovery|null;
const passage='Invented fax. Patient-reported heart history is uncertain. DOB and trial eligibility unknown.';
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===name);
async function wait(check:()=>void){for(let n=0;n<300;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,1));try{check();done=true;}catch{}});if(done)return;}check();}
const idle=()=>wait(()=>expect(host.textContent).not.toContain('Waiting for the current fax passage operation'));
async function mount(){await act(async()=>root.render(<FaxSourceReviewPanel {...props}/>));await wait(()=>expect(host.querySelector('textarea')||button('Restore saved fax passage')).toBeTruthy());}
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>button(name)!.click());await idle();}
async function enter(){await act(async()=>{const t=host.querySelector<HTMLTextAreaElement>('textarea')!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(t,passage);t.dispatchEvent(new Event('input',{bubbles:true}));const p=host.querySelector<HTMLInputElement>('input[aria-label="Pages used"]')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(p,'1, 3');p.dispatchEvent(new Event('input',{bubbles:true}));});}
async function ack(){await act(async()=>host.querySelectorAll<HTMLInputElement>('input[type=checkbox]').forEach(c=>c.click()));}
async function receipt(request:FaxSourceReviewRequest):Promise<FaxSourceReceipt>{return {contract_version:1,scope,idempotency_key:request.idempotency_key,request_sha256:await faxSourceRequestHash(scope,request),review_id:uuid(7),entry_id:uuid(8),entry_revision:request.expected_revision+1,operation_id:request.operation_id,source_sha256:'b'.repeat(64),content_sha256:await vendorSha256(new TextEncoder().encode(request.passage)),document_sha256:request.document_sha256,page_numbers:request.page_numbers,coverage:'human_selected_passage',extraction:'human_entered_no_ocr',source_withheld:false,state:'saved'};}
function workspace(r:FaxSourceReceipt,request:FaxSourceReviewRequest){return {id:scope.workspace_id,revision:r.entry_revision,entries:[{id:r.entry_id,revision:r.entry_revision,kind:'fax_inbound_source',source_label:FAX_SOURCE_LABEL,content:request.passage,practice_fax_source_state:'current'}],note:{latest:{content:'Invented existing note'}}} as unknown as Workspace;}
beforeEach(()=>{
 vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);saved=null;
 props={identity:{mode:'clerk_jwt',getToken:async()=>null},scope,offered:{operation_id:uuid(4),document_sha256:'a'.repeat(64),pages:3,label:'Invented received fax'},visit:{id:scope.workspace_id,label:'Invented walk-in · DOB optional',revision:5},
 recovery:{authorize:vi.fn(async()=>{}),load:vi.fn(async()=>saved),persist:vi.fn(async v=>{saved=v?structuredClone(v):null;})},onSaved:vi.fn(),onAskChief:vi.fn(),onAuthenticationLost:vi.fn(),onBusyChange:vi.fn(),onRefreshDocument:vi.fn(async()=>props.offered)};
 vi.mocked(faxSourceApi.review).mockImplementation(async(_identity,_scope,request)=>{const r=await receipt(request);vi.mocked(workspaceApi.read).mockResolvedValue(workspace(r,request));return r;});
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('starts with no read, no OCR, optional DOB and explicit four confirmations',async()=>{
 await mount();expect(faxSourceApi.review).not.toHaveBeenCalled();expect(faxSourceApi.resolve).not.toHaveBeenCalled();expect(workspaceApi.read).not.toHaveBeenCalled();
 expect(host.textContent).toContain('does not extract or OCR');expect(host.textContent).toContain('Date of birth is optional');expect(host.querySelectorAll('input[type=checkbox]')).toHaveLength(4);
 await enter();expect(button('Save reviewed fax passage for this visit')!.disabled).toBe(true);await ack();expect(button('Save reviewed fax passage for this visit')!.disabled).toBe(false);
});
it('provider reviews exact pages, journals before POST, saves separately then prepares editable Chief request',async()=>{
 await mount();await enter();await ack();vi.mocked(faxSourceApi.review).mockImplementationOnce(async(_i,_s,request)=>{
  expect(saved!.pending!.request).toEqual(request);expect(saved!.pending!.request_sha256).toBe(await faxSourceRequestHash(scope,request));const r=await receipt(request);vi.mocked(workspaceApi.read).mockResolvedValue(workspace(r,request));return r;
 });
 await click('Save reviewed fax passage for this visit');expect(saved!.pending).toBeNull();expect(saved!.saved!.state).toBe('saved');expect(props.onSaved).toHaveBeenCalledOnce();expect(props.onAskChief).not.toHaveBeenCalled();
 expect(host.textContent).toContain('Fax passage saved for this visit');const r=saved!.saved!,request=saved!.saved_request!;vi.mocked(faxSourceApi.resolve).mockResolvedValueOnce(r);await click('Prepare a Chief request');
 expect(props.onAskChief).toHaveBeenCalledWith({receipt:r,workspace:workspace(r,request),entry:expect.objectContaining({content:passage,practice_fax_source_state:'current'})});expect(faxSourceApi.review).toHaveBeenCalledOnce();
});
it('does not dispatch when encrypted persistence fails',async()=>{
 await mount();await enter();await ack();vi.mocked(props.recovery!.persist).mockRejectedValueOnce(new Error('invented storage failure'));await click('Save reviewed fax passage for this visit');expect(faxSourceApi.review).not.toHaveBeenCalled();expect(host.textContent).toContain('retained');
});
it('recovers a lost save reply by original-key resolve without another source save',async()=>{
 await mount();await enter();await ack();vi.mocked(faxSourceApi.review).mockRejectedValueOnce(new WorkspaceApiError(503));await click('Save reviewed fax passage for this visit');
 const request=structuredClone(saved!.pending!.request),r=await receipt(request);vi.mocked(faxSourceApi.resolve).mockResolvedValueOnce(r);vi.mocked(workspaceApi.read).mockResolvedValueOnce(workspace(r,request));await click('Check saved fax review');
 expect(faxSourceApi.resolve).toHaveBeenCalledWith(props.identity,scope,request,expect.any(AbortSignal));expect(faxSourceApi.review).toHaveBeenCalledOnce();expect(saved!.pending).toBeNull();
});
it('only offers same saved request after authoritative not-found and retains frozen intent',async()=>{
 await mount();await enter();await ack();vi.mocked(faxSourceApi.review).mockRejectedValueOnce(new WorkspaceApiError(503));await click('Save reviewed fax passage for this visit');const request=structuredClone(saved!.pending!.request);
 vi.mocked(faxSourceApi.resolve).mockResolvedValueOnce({contract_version:1,scope,idempotency_key:request.idempotency_key,state:'not_found'});await click('Check saved fax review');await click('Send exact saved fax review');
 expect(vi.mocked(faxSourceApi.review).mock.calls[1][2]).toEqual(request);expect(saved!.pending).toBeNull();
});
it('a missing old-revision save can be explicitly reset for current visit without another save',async()=>{
 await mount();await enter();await ack();vi.mocked(faxSourceApi.review).mockRejectedValueOnce(new WorkspaceApiError(503));await click('Save reviewed fax passage for this visit');const request=structuredClone(saved!.pending!.request);
 props={...props,visit:{...props.visit,revision:6}};await act(async()=>root.render(<FaxSourceReviewPanel {...props}/>));
 vi.mocked(faxSourceApi.resolve).mockResolvedValueOnce({contract_version:1,scope,idempotency_key:request.idempotency_key,state:'not_found'});await click('Check saved fax review');expect(button('Send exact saved fax review')!.disabled).toBe(true);
 await click('Prepare a new review for current visit');expect(saved!.pending).toBeNull();expect(saved!.visit.revision).toBe(6);expect(saved!.passage).toBe(passage);expect(host.querySelector('textarea')).toBeNull();expect(faxSourceApi.review).toHaveBeenCalledOnce();
 await click('Check exact acquired PDF');expect(button('Save reviewed fax passage for this visit')!.disabled).toBe(true);
});
it('hides withheld historical source and refuses Chief preparation when current workspace changes',async()=>{
 await mount();await enter();await ack();await click('Save reviewed fax passage for this visit');const r=saved!.saved!,request=saved!.saved_request!;
 vi.mocked(faxSourceApi.resolve).mockResolvedValueOnce(r);vi.mocked(workspaceApi.read).mockResolvedValueOnce({...workspace(r,request),entries:[{...workspace(r,request).entries[0],content:'',practice_fax_source_state:'unavailable'}]});
 await click('Prepare a Chief request');expect(props.onAskChief).not.toHaveBeenCalled();expect(host.textContent).not.toContain(passage);expect(saved!.saved!.request_sha256).toBe(r.request_sha256);
});
it('resets acknowledgments on same-visit revision and uses fresh revision before new save',async()=>{
 await mount();await enter();await ack();props={...props,visit:{...props.visit,revision:6}};await act(async()=>root.render(<FaxSourceReviewPanel {...props}/>));
 expect([...host.querySelectorAll<HTMLInputElement>('input[type=checkbox]')].every(c=>!c.checked)).toBe(true);expect(host.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe(passage);await ack();await click('Save reviewed fax passage for this visit');
 expect(vi.mocked(faxSourceApi.review).mock.calls[0][2].expected_revision).toBe(6);
});
it('immediately masks native suspension, resets review and resumes only after explicit document check',async()=>{
 props.identity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:uuid(90),isCurrent:()=>true}};await mount();await enter();await ack();await act(async()=>notifyNativeWorkspaceForeground(props.identity,false));
 expect(host.querySelector('textarea')).toBeNull();expect(host.textContent).not.toContain('Invented received fax');await act(async()=>notifyNativeWorkspaceForeground(props.identity,true));expect(host.querySelector('textarea')).toBeNull();
 expect(props.onRefreshDocument).not.toHaveBeenCalled();await click('Check exact acquired PDF');expect([...host.querySelectorAll<HTMLInputElement>('input[type=checkbox]')].every(c=>!c.checked)).toBe(true);expect(faxSourceApi.review).not.toHaveBeenCalled();
});
it('retains exact pending journal and fences late native save response',async()=>{
 props.identity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:uuid(90),isCurrent:()=>true}};await mount();await enter();await ack();let finish!:(r:FaxSourceReceipt)=>void;vi.mocked(faxSourceApi.review).mockReturnValueOnce(new Promise(r=>{finish=r;}));
 await act(async()=>button('Save reviewed fax passage for this visit')!.click());await wait(()=>expect(saved?.pending).toBeTruthy());const request=structuredClone(saved!.pending!.request);
 await act(async()=>notifyNativeWorkspaceForeground(props.identity,false));await act(async()=>notifyNativeWorkspaceForeground(props.identity,true));await act(async()=>finish(await receipt(request)));
 await wait(()=>expect(button('Restore saved fax passage')).toBeDefined());expect(saved!.pending!.request).toEqual(request);expect(props.onSaved).not.toHaveBeenCalled();expect(workspaceApi.read).not.toHaveBeenCalled();
});
it('restored private draft remains masked until exact document is checked and all acknowledgments renewed',async()=>{
 saved={...emptyFaxSourceRecovery(scope,props.offered,props.visit),passage,page_numbers:[1,3]};await mount();expect(host.textContent).not.toContain(passage);await click('Restore saved fax passage');expect(host.querySelector('textarea')).toBeNull();await click('Check exact acquired PDF');
 expect(host.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe(passage);expect(button('Save reviewed fax passage for this visit')!.disabled).toBe(true);expect(faxSourceApi.review).not.toHaveBeenCalled();
});
it('absence of document revalidation keeps restored passage masked and prevents new share',async()=>{
 saved={...emptyFaxSourceRecovery(scope,props.offered,props.visit),passage,page_numbers:[1,3]};props={...props,onRefreshDocument:undefined};await mount();await click('Restore saved fax passage');await click('Check exact acquired PDF');expect(host.querySelector('textarea')).toBeNull();expect(faxSourceApi.review).not.toHaveBeenCalled();
});
it('does not adopt late response after identity replacement or expose prior passage',async()=>{
 await mount();await enter();await ack();let finish!:(r:FaxSourceReceipt)=>void;vi.mocked(faxSourceApi.review).mockReturnValueOnce(new Promise(r=>{finish=r;}));await act(async()=>button('Save reviewed fax passage for this visit')!.click());await wait(()=>expect(saved?.pending).toBeTruthy());const request=structuredClone(saved!.pending!.request);
 props={...props,identity:{mode:'clerk_jwt',getToken:async()=>null},scope:{...scope,owner_id:uuid(99)},recovery:{authorize:async()=>{},load:async()=>null,persist:async()=>{}}};await act(async()=>root.render(<FaxSourceReviewPanel {...props}/>));await act(async()=>finish(await receipt(request)));
 expect(host.textContent).not.toContain(passage);expect(props.onSaved).not.toHaveBeenCalled();expect(workspaceApi.read).not.toHaveBeenCalled();
});

it('updates the parent masked workspace when a reopened saved source is revoked, preserving the exact review without another save',async()=>{
 await mount();await enter();await ack();await click('Save reviewed fax passage for this visit');const r=saved!.saved!,request=saved!.saved_request!;
 const withheld={...r,source_withheld:true},masked={...workspace(r,request),entries:[{...workspace(r,request).entries[0],content:'',practice_fax_source_state:'unavailable' as const}]};
 vi.mocked(faxSourceApi.resolve).mockResolvedValueOnce(withheld);vi.mocked(workspaceApi.read).mockResolvedValueOnce(masked);
 await act(async()=>{await root.unmount();root=createRoot(host);root.render(<FaxSourceReviewPanel {...props}/>);});await wait(()=>expect(button('Restore saved fax passage')).toBeDefined());await click('Restore saved fax passage');await click('Check saved fax source');expect(saved!.saved).toEqual(withheld);expect(saved!.saved_request).toEqual(request);expect(props.onSaved).toHaveBeenLastCalledWith(withheld,masked);
 expect(host.querySelector('textarea')).toBeNull();expect(host.textContent).not.toContain(passage);expect(button('Prepare a Chief request')).toBeUndefined();expect(faxSourceApi.review).toHaveBeenCalledOnce();expect(props.onAskChief).not.toHaveBeenCalled();
});
