import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_VENDOR_SETUP_ENABLED','VITE_EFAX_INBOUND_ENABLED','VITE_EFAX_INBOUND_SOURCE_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
const observedFax=vi.hoisted(()=>({session:null as import('./session/workspace-session').WorkspaceSession|null,operation:undefined as ((blocked:boolean)=>void)|undefined}));
vi.mock('./session/use-workspace-session',async importOriginal=>{const original=await importOriginal<typeof import('./session/use-workspace-session')>();return {...original,useWorkspaceSession:(...args:Parameters<typeof original.useWorkspaceSession>)=>{observedFax.session=args[0];return original.useWorkspaceSession(...args);}};});
vi.mock('./EFaxSourceReviewMount',async importOriginal=>{const original=await importOriginal<typeof import('./EFaxSourceReviewMount')>();return {...original,EFaxSourceReviewMount:(props:import('./EFaxSourceReviewMount').EFaxSourceReviewMountProps)=>{observedFax.operation=props.onOperationBusyChange;return <original.EFaxSourceReviewMount {...props}/>;}};});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {openDraftStore} from './draft-store';
import {PRESENTATION_KEY} from './session/presentation';
import {workspaceApi} from './workspace-api';
import {conversationsApi} from './conversations-api';
import {efaxInboundApi} from './efax-inbound-api';
import {efaxSourceApi,type EFaxSourceReceipt,type EFaxSourceReviewRequest} from './efax-inbound-source-api';
import {RECEIVED_FAX_PASSAGE,type ReceivedFaxStats} from '../ux-acceptance/efax';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement,idb:IDBFactory;
const storage=({scope}:{scope:string})=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const task=()=>[...host.querySelectorAll<HTMLElement>('.ehr-read-task[aria-label="Review received fax"]')].find(visible);
const stats=()=>(window as Window&{receivedFaxStats?:ReceivedFaxStats}).receivedFaxStats!;
async function wait(check:()=>void){for(let n=0;n<300;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name)?.matches(':disabled'),name).toBe(false));await act(async()=>{button(name)!.focus({preventScroll:true});button(name)!.click();});}
async function type(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function openChat(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()?.disabled).toBe(false));}
async function openTask(){await click('Details');await click('Choose notes or sources');await click('Review received fax');await wait(()=>expect(task()).toBeDefined());await wait(()=>expect(['Restore saved received-fax work','Check saved received-fax result','Check received-fax access'].some(name=>{const target=button(name);return target&&!target.matches(':disabled');})).toBe(true));}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());}
async function prepareAcquisition(open=true){if(open)await openTask();await click('Check received-fax access');await act(async()=>{const select=host.querySelectorAll<HTMLSelectElement>('.efax-inbound-panel select')[1];select.value=select.options[1].value;select.dispatchEvent(new Event('change',{bubbles:true}));});await click('Check received faxes · last 7 days');await wait(()=>expect(task()?.querySelector<HTMLButtonElement>('li button')?.disabled).toBe(false));await act(async()=>task()!.querySelector<HTMLButtonElement>('li button')!.click());await click('Prepare exact image acquisition');await wait(()=>expect(task()?.querySelector<HTMLInputElement>('article input')?.matches(':disabled')).toBe(false));await act(async()=>task()!.querySelector<HTMLInputElement>('article input')!.click());await click('Approve exact image acquisition');await click('Acquire approved PDF once');}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 idb=new IDBFactory();localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','/?scenario=received-fax-happy#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await mount();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it.each(['phone','desktop'] as const)('opens one received-fax task from Chief and returns the exact draft, focus and reading position (%s)',async layout=>{
 vi.mocked(window.matchMedia).mockReturnValue({matches:layout==='phone',addEventListener:vi.fn(),removeEventListener:vi.fn()} as unknown as MediaQueryList);await openChat();await type('Keep these exact Chief directions while reviewing fax.');
 const scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:1100});Object.defineProperty(scroll,'clientHeight',{configurable:true,value:200});await act(async()=>{scroll.scrollTop=230;scroll.dispatchEvent(new Event('scroll'));});
 const doc=document.documentElement;Object.defineProperty(document,'scrollingElement',{configurable:true,value:doc});Object.defineProperty(doc,'scrollHeight',{configurable:true,value:1800});Object.defineProperty(doc,'clientHeight',{configurable:true,value:800});doc.scrollTop=layout==='desktop'?693:0;
 const before={top:scroll.scrollTop,document:doc.scrollTop};const marks=vi.spyOn(conversationsApi,'mark'),ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');await openTask();expect(host.querySelectorAll('.efax-inbound-panel')).toHaveLength(1);expect(host.querySelector('.settings-hub-nav')?.hasAttribute('hidden')).toBe(true);expect(stats().observations).toBe(0);expect(stats().acquisitions).toBe(0);
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(button('Details')));expect(question().value).toBe('Keep these exact Chief directions while reviewing fax.');expect(document.activeElement).not.toBe(question());expect(scroll.scrollTop).toBe(before.top);expect(doc.scrollTop).toBe(before.document);expect(marks).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('reuses the same retained account journal from Saved sources and returns to its exact invoking control',async()=>{
 await openChat();await type('Keep the source-review draft.');await openTask();const panel=host.querySelector('.efax-inbound-panel');await click('‹ Back to Chief of Staff');await click('Details');await click('Choose notes or sources');await click('Saved sources');const sourceButton=button('Review received fax')!;await click('Review received fax');await wait(()=>expect(task()).toBeDefined());expect(host.querySelector('.efax-inbound-panel')).toBe(panel);
 await click('‹ Back to saved sources');await wait(()=>expect(document.activeElement).toBe(sourceButton));expect(question().value).toBe('Keep the source-review draft.');expect(stats().observations).toBe(0);expect(stats().acquisitions).toBe(0);
});
it('locks Back through a real active status read and unlocks after its cleanup',async()=>{
 await openChat();await type('Retain this while checking access.');await openTask();const original=efaxInboundApi.status;let finish!:()=>void;vi.spyOn(efaxInboundApi,'status').mockImplementation(async(...args)=>{await new Promise<void>(resolve=>{finish=resolve;});return original(...args);});
 await act(async()=>button('Check received-fax access')!.click());await wait(()=>expect(button('‹ Back to Chief of Staff')?.disabled).toBe(true));await act(async()=>button('‹ Back to Chief of Staff')!.click());expect(task()).toBeDefined();await act(async()=>finish());await click('‹ Back to Chief of Staff');expect(question().value).toBe('Retain this while checking access.');
});
it('permits Back for an encrypted lost acquisition, restores the same pending request, and never reacquires',async()=>{
 history.replaceState(null,'','/?scenario=received-fax-lost-acquire#cosmas/home');await openChat();await type('Keep the exact draft while image result is unknown.');await prepareAcquisition();await wait(()=>expect(button('Check saved received-fax result')?.disabled).toBe(false));const request=stats().requests.find(row=>row.path==='/efax-inbound/acquire')!;expect(stats().acquisitions).toBe(1);
 await click('‹ Back to Chief of Staff');expect(question().value).toBe('Keep the exact draft while image result is unknown.');await openTask();await click('Check saved received-fax result');expect(stats().acquisitions).toBe(1);expect(stats().resolves).toBe(1);const resolved=stats().requests.find(row=>row.path==='/efax-inbound/resolve')!;expect((resolved.body as {idempotency_key:string}).idempotency_key).toBe((request.body as {idempotency_key:string}).idempotency_key);expect(stats().documents).toBe(0);
});
it('ignores a retained old task-return callback after a new conversation entry episode',async()=>{
 await openChat();await type('New route keeps its focus.');await openTask();let old:FrameRequestCallback|undefined;vi.spyOn(window,'requestAnimationFrame').mockImplementationOnce(callback=>{old=callback;return 99881;});await click('‹ Back to Chief of Staff');expect(old).toBeTypeOf('function');await click('‹ Messages');await openChat();await act(async()=>question().focus({preventScroll:true}));await act(async()=>old!(0));expect(document.activeElement).toBe(question());expect(question().value).toBe('New route keeps its focus.');expect(stats().acquisitions).toBe(0);
});

const passage=()=>[...host.querySelectorAll<HTMLElement>('[aria-label="Review received fax passage"]')].find(visible);
async function editPassage(text=RECEIVED_FAX_PASSAGE,pageNumbers='1'){
 await wait(()=>expect(passage()?.querySelector('textarea')?.matches(':disabled')).toBe(false));
 await act(async()=>{const field=passage()!.querySelector<HTMLTextAreaElement>('textarea')!;Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,text);field.dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>{const field=passage()!.querySelector<HTMLInputElement>('input[aria-label="Pages used"]')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(field,pageNumbers);field.dispatchEvent(new Event('input',{bubbles:true}));});
}
async function openPassage(){await click('Review a passage for the current visit');await wait(()=>expect(passage()?.querySelector('textarea')?.matches(':disabled')).toBe(false));}
async function confirmPassage(){await wait(()=>expect(passage()?.querySelector('fieldset input')?.matches(':disabled')).toBe(false));for(const field of passage()!.querySelectorAll<HTMLInputElement>('fieldset input'))await act(async()=>field.click());}
it.each(['conversation','sources'] as const)('keeps the captured %s origin across acquisition and a privately saved passage, then returns the exact draft and focus',async origin=>{
 await openChat();await type('The same Chief draft must survive fax passage review.');
 const scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:1100});Object.defineProperty(scroll,'clientHeight',{configurable:true,value:200});await act(async()=>{scroll.scrollTop=230;scroll.dispatchEvent(new Event('scroll'));});
 if(origin==='sources'){await click('Details');await click('Choose notes or sources');await click('Saved sources');await click('Review received fax');await wait(()=>expect(task()).toBeDefined());}
 await prepareAcquisition(origin==='conversation');await openPassage();const mark=vi.spyOn(conversationsApi,'mark'),ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append');
 const back=origin==='sources'?'‹ Back to saved sources':'‹ Back to Chief of Staff';await editPassage();await wait(()=>expect(button(back)?.disabled).toBe(true));expect(passage()?.textContent).toContain('Save passage draft privately before leaving.');
 await click('Save passage draft privately');await wait(()=>expect(button(back)?.disabled).toBe(false));expect(stats().reviews).toBe(0);await click(back);
 await wait(()=>expect(document.activeElement).toBe(origin==='sources'?button('Review received fax'):button('Details')));expect(question().value).toBe('The same Chief draft must survive fax passage review.');if(origin==='conversation')expect(scroll.scrollTop).toBe(230);
 expect(passage()).toBeUndefined();expect(mark).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('returns for durable unconfirmed passage review and resolves its exact request before preparing Chief without another save',async()=>{
 history.replaceState(null,'','/?scenario=received-fax-lost-review#cosmas/home');await openChat();await type('Keep existing Chief directions.');await prepareAcquisition();await openPassage();await editPassage();await confirmPassage();await click('Save reviewed fax passage for this visit');
 await wait(()=>expect(button('Check saved fax review')?.disabled).toBe(false));const review=stats().requests.find(row=>row.path.endsWith('/efax-inbound-source'))!;expect(stats().reviews).toBe(1);await click('‹ Back to Chief of Staff');expect(question().value).toBe('Keep existing Chief directions.');
 const resolveSource=vi.spyOn(efaxSourceApi,'resolve');await openTask();expect(button('Restore saved received-fax work')).toBeUndefined();await click('Check received-fax access');await click('Review a passage for the current visit');await wait(()=>expect(button('Check saved fax review')?.disabled).toBe(false));expect(stats().reviews).toBe(1);await click('Check saved fax review');await wait(()=>expect(button('Prepare a Chief request')?.disabled).toBe(false));
 const resolution=stats().requests.find(row=>row.path.endsWith('/efax-inbound-source/resolve'))!;expect(resolution.body).toEqual({idempotency_key:(review.body as {idempotency_key:string}).idempotency_key});expect(resolveSource.mock.calls[0][2]).toEqual(review.body);expect(stats().reviews).toBe(1);expect(passage()?.querySelector('pre')?.textContent).toBe(RECEIVED_FAX_PASSAGE);
 const ask=vi.spyOn(workspaceApi,'ask');await click('Prepare a Chief request');await wait(()=>expect(question().value).toContain('Review the human-selected received-fax passage'));expect(question().value).toMatch(/^Keep existing Chief directions\.\n\n/);expect(passage()).toBeUndefined();expect(ask).not.toHaveBeenCalled();expect(stats().acquisitions).toBe(1);expect(stats().reviews).toBe(1);
});

it('locks direct Back during original-PDF authorization/read, then closes and waits for cancellation cleanup without changing the saved private passage',async()=>{
 await openChat();await type('PDF review must preserve Chief directions.');await prepareAcquisition();await openPassage();await editPassage();await click('Save passage draft privately');await wait(()=>expect(button('‹ Back to Chief of Staff')?.disabled).toBe(false));
 let release!:(reason:Error)=>void,signal:AbortSignal|undefined;const documentRead=vi.spyOn(efaxInboundApi,'document').mockImplementation(async(_owner,_receipt,abort)=>{signal=abort;return new Promise<Uint8Array>((_resolve,reject)=>{release=reject;});});
 await click('Open original PDF');await wait(()=>expect(documentRead).toHaveBeenCalledOnce());expect(button('‹ Back to Chief of Staff')?.disabled).toBe(true);await click('Close original PDF');expect(signal?.aborted).toBe(true);expect(button('‹ Back to Chief of Staff')?.disabled).toBe(true);
 await act(async()=>release(new DOMException('Stopped','AbortError')));await wait(()=>expect(button('‹ Back to Chief of Staff')?.disabled).toBe(false));expect(passage()?.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe(RECEIVED_FAX_PASSAGE);expect(passage()?.querySelector('canvas')).toBeNull();expect(stats().reviews).toBe(0);await click('‹ Back to Chief of Staff');expect(question().value).toBe('PDF review must preserve Chief directions.');
});

it('retains the same fax passage task and explicit Saved-sources return in the Workspace layout',async()=>{
 await act(async()=>root.render(null));localStorage.setItem(PRESENTATION_KEY,'workspace');await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));
 await wait(()=>expect(host.querySelector<HTMLButtonElement>('.notebook-list-row .practice-home-note')?.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.notebook-list-row .practice-home-note')!.click());
 await wait(()=>expect(host.querySelector<HTMLButtonElement>('.team-roster button')?.disabled).toBe(false));await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(row=>row.textContent?.includes('Chief of Staff'))!.click());await wait(()=>expect(question()?.disabled).toBe(false));await type('Keep Workspace Chief draft.');await click('Sources');
 const origin=button('Review received fax')!;await click('Review received fax');await wait(()=>expect(task()).toBeDefined());await prepareAcquisition(false);await openPassage();await editPassage();await click('Save passage draft privately');await click('‹ Back to saved sources');await wait(()=>expect(document.activeElement).toBe(origin));expect(question().value).toBe('Keep Workspace Chief draft.');expect(passage()).toBeUndefined();expect(stats().reviews).toBe(0);expect(stats().acquisitions).toBe(1);
});

it('keeps settled acquisition work directly usable after passage Back and same-instance task reopen',async()=>{
 await openChat();await type('Keep the settled-task draft.');await prepareAcquisition();await openPassage();await click('‹ Back to Chief of Staff');await openTask();
 expect(button('Restore saved received-fax work')).toBeUndefined();expect(button('Check received-fax access')?.disabled).toBe(false);expect(stats().acquisitions).toBe(1);expect(stats().observations).toBe(1);expect(stats().reviews).toBe(0);expect(question().value).toBe('Keep the settled-task draft.');
});

it('cannot clear a shared session operation lock through a source callback retained after Shell unmount',async()=>{
 await openChat();await prepareAcquisition();await openPassage();const session=observedFax.session!,oldCallback=observedFax.operation!;expect(oldCallback).toBeTypeOf('function');await act(async()=>root.render(null));
 await act(async()=>session.setFaxSourceBusy(true));expect(session.getSnapshot().faxSourceBusy).toBe(true);await act(async()=>oldCallback(false));expect(session.getSnapshot().faxSourceBusy).toBe(true);
});


async function saveFaxForCard():Promise<{receipt:EFaxSourceReceipt;request:EFaxSourceReviewRequest}>{
 const review=vi.spyOn(efaxSourceApi,'review');await prepareAcquisition();await openPassage();await editPassage();await confirmPassage();await click('Save reviewed fax passage for this visit');await wait(()=>expect(button('Prepare a Chief request')?.disabled).toBe(false));
 const receipt=await review.mock.results[0].value,request=structuredClone(review.mock.calls[0][2]);expect(receipt.page_numbers).toEqual([1]);expect(receipt.document_sha256).toBe(request.document_sha256);expect(receipt.operation_id).toBe(request.operation_id);expect(request.passage).toBe(RECEIVED_FAX_PASSAGE);return {receipt,request};
}
it.each([{layout:'phone',clamped:false},{layout:'phone',clamped:true},{layout:'desktop',clamped:false}] as const)('opens a saved received-fax card and preserves exact source custody, draft, focus and reading position ($layout, clamped=$clamped)',async({layout,clamped})=>{
 vi.mocked(window.matchMedia).mockReturnValue({matches:layout==='phone',addEventListener:vi.fn(),removeEventListener:vi.fn()} as unknown as MediaQueryList);
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),marks=vi.spyOn(conversationsApi,'mark'),reads=vi.spyOn(conversationsApi,'read'),original='Keep these exact Chief directions while I reopen the selected fax passage.';
 await openChat();await type(original);const {receipt,request}=await saveFaxForCard();let oldReturn:FrameRequestCallback|undefined;vi.spyOn(window,'requestAnimationFrame').mockImplementationOnce(callback=>{oldReturn=callback;return 100022;});await click('‹ Back to Chief of Staff');expect(oldReturn).toBeTypeOf('function');
 const card=host.querySelector<HTMLElement>(`[data-entry-id="source:${receipt.entry_id}"]`);expect(card).not.toBeNull();expect(card!.getAttribute('aria-label')).toBe('Saved fax passage');expect(card!.textContent).toContain('Received eFax: human-reviewed passage');expect(card!.textContent).not.toContain(RECEIVED_FAX_PASSAGE);expect(card!.querySelectorAll('button')).toHaveLength(1);
 const saved=structuredClone(observedFax.session!.getSnapshot().workspace!.entries.find(entry=>entry.id===receipt.entry_id)!);expect(saved.content).toBe(request.passage);expect(saved.revision).toBe(receipt.entry_revision);expect(card!.querySelector('time')?.dateTime).toBe(saved.created_at);
 const control=card!.querySelector<HTMLButtonElement>('button')!,scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;Object.defineProperty(scroll,'clientHeight',{configurable:true,value:200});Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:1100});
 const doc=document.documentElement;Object.defineProperty(document,'scrollingElement',{configurable:true,value:doc});Object.defineProperty(doc,'scrollHeight',{configurable:true,value:1800});Object.defineProperty(doc,'clientHeight',{configurable:true,value:800});
 if(clamped){scroll.scrollTop=900;await act(async()=>scroll.dispatchEvent(new Event('scroll')));await wait(()=>expect(marks.mock.calls.some(([, , ,command])=>command?.watermark!==undefined&&command.manual_unread===undefined)).toBe(true));await act(async()=>{await Promise.all(marks.mock.results.map(result=>result.value));});}
 const readState=await conversationsApi.read(identity,null);if(layout==='phone')expect(readState.rows.find(row=>row.workspace_id===receipt.scope.workspace_id&&row.bot.role==='chief')?.unread).toBe(!clamped);
 scroll.scrollTop=230;await act(async()=>scroll.dispatchEvent(new Event('scroll')));doc.scrollTop=layout==='desktop'?693:0;
 const before=structuredClone(stats()),markCount=marks.mock.calls.length,readCount=reads.mock.calls.length,turnIds=[...host.querySelectorAll('.team-turn')].map(entry=>entry.getAttribute('data-entry-id')),documentTop=doc.scrollTop;
 await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe(`source-${receipt.entry_id}`));const exact=document.getElementById(`source-${receipt.entry_id}`)!;expect(exact.classList.contains('selected')).toBe(true);expect(exact.querySelector(':scope > p')?.textContent).toBe(request.passage);expect(question().value).toBe(original);
 if(clamped)Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:375});await click('‹ Back to Chief of Staff');await act(async()=>oldReturn!(0));await wait(()=>expect(document.activeElement).toBe(control));expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(document.activeElement).not.toBe(question());expect(scroll.scrollTop).toBe(clamped?175:230);expect(doc.scrollTop).toBe(documentTop);expect(question().value).toBe(original);
 expect(observedFax.session!.getSnapshot().workspace!.entries.find(entry=>entry.id===receipt.entry_id)).toEqual(saved);expect(receipt.page_numbers).toEqual(request.page_numbers);expect(stats()).toEqual(before);expect(stats().documents).toBe(0);expect(stats().acquisitions).toBe(1);expect(stats().reviews).toBe(1);expect(marks).toHaveBeenCalledTimes(markCount);expect(reads).toHaveBeenCalledTimes(readCount);expect([...host.querySelectorAll('.team-turn')].map(entry=>entry.getAttribute('data-entry-id'))).toEqual(turnIds);expect(host.querySelector('.messages-new-replies')).toBeNull();expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
it('opens an unavailable saved received-fax card through the existing placeholder without re-reading or exposing its passage',async()=>{
 const ask=vi.spyOn(workspaceApi,'ask'),append=vi.spyOn(workspaceApi,'append'),original='Keep these directions when my selected fax passage becomes unavailable.';await openChat();await type(original);const {receipt}=await saveFaxForCard();await click('Prepare a Chief request');
 // Preparation rechecks the saved source asynchronously; keep it available until Chief has actually opened.
 await wait(()=>{expect(question().value).toContain(`Review the human-selected received-fax passage ${receipt.entry_id}`);expect(question().value.startsWith(`${original}\n\n`)).toBe(true);expect(passage()).toBeUndefined();expect(button('‹ Messages')?.disabled).toBe(false);});const retained=question().value;
 await act(async()=>{(window as Window&{receivedFaxControls?:{withdraw:()=>void}}).receivedFaxControls!.withdraw();});await click('‹ Messages');await openChat();const card=()=>host.querySelector<HTMLElement>(`[data-entry-id="source:${receipt.entry_id}"]`);await wait(()=>expect(card()?.querySelector('h3')?.textContent).toBe('Unavailable fax passage'));expect(card()!.getAttribute('aria-label')).toBe('Saved fax passage');expect(card()!.textContent).not.toContain(RECEIVED_FAX_PASSAGE);expect(card()!.textContent).not.toContain('Received eFax: human-reviewed passage');
 const before=structuredClone(stats()),control=card()!.querySelector<HTMLButtonElement>('button')!;await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe(`source-${receipt.entry_id}`));const exact=document.getElementById(`source-${receipt.entry_id}`)!;expect(exact.textContent).toContain('This fax passage is unavailable');expect(exact.textContent).not.toContain(RECEIVED_FAX_PASSAGE);await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));expect(question().value).toBe(retained);expect(stats()).toEqual(before);expect(ask).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();
});
