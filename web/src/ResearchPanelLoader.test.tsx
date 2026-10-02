import {act,useEffect,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {ResearchPanelLoader,type ResearchPanelImport,type ResearchPanelModule} from './ResearchPanelLoader';
import {ResearchWorkspace} from './ResearchWorkspace';
import {EditorRecoveryContext,type EditorRecoveryAccess,editorDraft} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {openDraftStore} from './draft-store';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {researchCatalog,researchIdentity,researchWorkspaceId,researchBotId,researchObservation,researchSaved} from './research-test-fixture';
import type {ResearchPort} from './research-api';
import type {ResearchSearch} from './research-contract';
import type {Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
type Props=Parameters<typeof ResearchWorkspace>[0];
let root:Root,host:HTMLDivElement,access:EditorRecoveryAccess,journal:DraftJournal,port:ResearchPort,imports:ReturnType<typeof vi.fn<ResearchPanelImport>>;
const workspace:Workspace={id:researchWorkspaceId,appointment_id:researchWorkspaceId,label:'Invented encounter',revision:2,entries:[],work_candidates:[]};
const mounts=vi.fn(),unmounts=vi.fn(),received:Props[]=[],denied=vi.fn();
const baseProps=()=>({identity:researchIdentity,workspaceId:researchWorkspaceId,workspaceRevision:2,
  bot:{address:researchBotId,team_revision:1},enabled:true,locked:false,port,onDenied:denied}) satisfies Props;
function deferred(){let resolve!:(value:ResearchPanelModule)=>void,reject!:(error:unknown)=>void;const promise=new Promise<ResearchPanelModule>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function Probe(props:Props){const [draft,setDraft]=useState('Retained panel input');received.push(props);useEffect(()=>{mounts();return()=>unmounts();},[]);return <label>Panel draft<input aria-label="Panel draft" value={draft} onChange={event=>setDraft(event.target.value)}/></label>;}
function Harness({props=baseProps(),visible=true,keyed=true}:{props?:Props;visible?:boolean;keyed?:boolean}){
  const [note,setNote]=useState('Unsent notebook'),[question,setQuestion]=useState('Unsent Chief question');
  return <EditorRecoveryContext.Provider value={access}><label>Notebook<textarea aria-label="Notebook" value={note} onChange={e=>setNote(e.target.value)}/></label>
    <label>Chief<textarea aria-label="Chief" value={question} onChange={e=>setQuestion(e.target.value)}/></label>
    {visible&&<ResearchPanelLoader key={keyed?props.workspaceId+':'+props.bot.address:undefined} {...props} loadPanel={imports}/>}
  </EditorRecoveryContext.Provider>;
}
async function render(props:Partial<Parameters<typeof Harness>[0]>={}){await act(async()=>root.render(<Harness {...props}/>));}
async function wait(check:()=>void){for(let attempt=0;attempt<100;attempt++){let complete=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));try{check();complete=true;}catch{}});if(complete)return;}check();}
async function input(selector:string,value:string){const field=host.querySelector<HTMLInputElement|HTMLTextAreaElement>(selector)!;await act(async()=>{Object.getOwnPropertyDescriptor(field instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function click(label:string){const b=[...host.querySelectorAll('button')].find(value=>value.textContent===label)!;expect(b,label).toBeTruthy();expect(b.disabled).toBe(false);await act(async()=>b.click());}
function noEffects(){expect(port.search).not.toHaveBeenCalled();expect(port.save).not.toHaveBeenCalled();expect(port.resolve).not.toHaveBeenCalled();expect(port.resolveSave).not.toHaveBeenCalled();}
beforeEach(async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);
 vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
 mounts.mockClear();unmounts.mockClear();received.splice(0);denied.mockClear();imports=vi.fn<ResearchPanelImport>();
 journal=new DraftJournal(await openDraftStore({scope:'f'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto:webcrypto}));
 access={journal,workspaceId:researchWorkspaceId,authorize:async()=>workspace,denied};
 port={catalog:vi.fn(async()=>researchCatalog()),history:vi.fn(async()=>({contract:'research.history.v1' as const,runs:[]})),
   savedHistory:vi.fn(async()=>({contract:'research.saved_history.v1' as const,workspace_id:researchWorkspaceId,bot:researchBotId,packets:[]})),
   search:vi.fn(async(_i,_w,request)=>researchObservation(request)),resolve:vi.fn(async(_i,_w,request)=>researchObservation(request)),
   save:vi.fn(async(_i,_w,_run,request)=>researchSaved(request)),resolveSave:vi.fn(async(_i,_w,_run,request)=>researchSaved(request))};
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());journal.close();host.remove();vi.unstubAllGlobals();});
it('does not import code or read Research until the existing selected view mounts',async()=>{await render({visible:false});expect(imports).not.toHaveBeenCalled();expect(port.catalog).not.toHaveBeenCalled();expect(host.querySelector('[aria-busy]')).toBeNull();noEffects();});
it('delayed opening preserves notebook, Chief text and focus and uses exact latest props',async()=>{
 const loading=deferred();imports.mockReturnValue(loading.promise);await render();await input('[aria-label="Notebook"]','Typed while opening');await input('[aria-label="Chief"]','Existing question');const chief=host.querySelector<HTMLTextAreaElement>('[aria-label="Chief"]')!;chief.focus();
 expect(host.querySelector('[role="status"]')?.textContent).toBe('Opening Research…');expect(host.querySelector('[aria-busy]')?.getAttribute('aria-busy')).toBe('true');expect(imports).toHaveBeenCalledOnce();expect(port.catalog).not.toHaveBeenCalled();noEffects();
 const updated={...baseProps(),workspaceRevision:9,bot:{address:researchBotId,team_revision:4},locked:true};await render({props:updated});expect(imports).toHaveBeenCalledOnce();
 await act(async()=>loading.resolve({ResearchWorkspace:Probe}));await wait(()=>expect(host.querySelector('[aria-label="Panel draft"]')).toBeTruthy());
 expect(received.at(-1)).toEqual(updated);expect(document.activeElement).toBe(chief);expect(chief.value).toBe('Existing question');expect(host.querySelector<HTMLTextAreaElement>('[aria-label="Notebook"]')!.value).toBe('Typed while opening');noEffects();
});
it('failure and explicit fresh import retry retain text and do not dispatch lookup or model work',async()=>{
 imports.mockRejectedValueOnce(new Error('Synthetic code transport unavailable')).mockResolvedValueOnce({ResearchWorkspace:Probe});
 await render();await wait(()=>expect(host.querySelector('[role="alert"]')?.textContent).toContain('could not open'));expect(host.querySelector('[aria-busy]')?.getAttribute('aria-busy')).toBe('false');
 await input('[aria-label="Chief"]','Question retained after failure');const chief=host.querySelector<HTMLTextAreaElement>('[aria-label="Chief"]')!;chief.focus();await click('Retry opening Research');await wait(()=>expect(mounts).toHaveBeenCalledOnce());
 expect(imports).toHaveBeenCalledTimes(2);expect(document.activeElement).toBe(chief);expect(chief.value).toBe('Question retained after failure');noEffects();
});
it('keeps loaded component state and mount across current revision updates',async()=>{
 imports.mockResolvedValue({ResearchWorkspace:Probe});await render();await wait(()=>expect(mounts).toHaveBeenCalledOnce());await input('[aria-label="Panel draft"]','Earlier panel text');
 await render({props:{...baseProps(),workspaceRevision:12,locked:true}});expect(host.querySelector<HTMLInputElement>('[aria-label="Panel draft"]')!.value).toBe('Earlier panel text');expect(mounts).toHaveBeenCalledOnce();expect(unmounts).not.toHaveBeenCalled();expect(imports).toHaveBeenCalledOnce();noEffects();
});
it('continues keyboard focus in the Research region after its explicitly focused retry button disappears',async()=>{
 const loading=deferred();imports.mockRejectedValueOnce(new Error('Synthetic unavailable chunk')).mockReturnValueOnce(loading.promise);
 await render();await wait(()=>expect(host.querySelector('[role="alert"]')).toBeTruthy());
 const retry=[...host.querySelectorAll('button')].find(button=>button.textContent==='Retry opening Research')!;retry.focus();await click('Retry opening Research');
 expect(document.activeElement).toBe(document.body);await act(async()=>loading.resolve({ResearchWorkspace:Probe}));
 await wait(()=>expect(document.activeElement).toBe(host.querySelector('[role="region"][aria-label="Research"]')));noEffects();
});
it('does not reclaim retry focus after the clinician moves to a different field while loading',async()=>{
 const loading=deferred();imports.mockRejectedValueOnce(new Error('Synthetic unavailable chunk')).mockReturnValueOnce(loading.promise);
 await render();await wait(()=>expect(host.querySelector('[role="alert"]')).toBeTruthy());
 [...host.querySelectorAll('button')].find(button=>button.textContent==='Retry opening Research')!.focus();await click('Retry opening Research');
 const notebook=host.querySelector<HTMLTextAreaElement>('[aria-label="Notebook"]')!;notebook.focus();await input('[aria-label="Notebook"]','Still typing while retry opens');
 await act(async()=>loading.resolve({ResearchWorkspace:Probe}));await wait(()=>expect(mounts).toHaveBeenCalledOnce());
 expect(document.activeElement).toBe(notebook);expect(notebook.value).toBe('Still typing while retry opens');noEffects();
});
it('fences a late old actor module result even without relying on the parent key',async()=>{
 const old=deferred(),next=deferred();imports.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);await render({keyed:false});
 const changed={...baseProps(),identity:{mode:'clerk_jwt' as const,getToken:async()=> 'other-invented-token'}};await render({props:changed,keyed:false});
 await act(async()=>old.resolve({ResearchWorkspace:Probe}));expect(mounts).not.toHaveBeenCalled();await act(async()=>next.resolve({ResearchWorkspace:Probe}));await wait(()=>expect(mounts).toHaveBeenCalledOnce());expect(received.at(-1)?.identity).toBe(changed.identity);noEffects();
});
it('fences delayed code on workspace switch and unmount without mounting the prior private panel',async()=>{
 const old=deferred();imports.mockReturnValue(old.promise);await render();await render({visible:false});await act(async()=>old.resolve({ResearchWorkspace:Probe}));expect(mounts).not.toHaveBeenCalled();expect(host.querySelector('[aria-label="Panel draft"]')).toBeNull();noEffects();
});
it('changes workspace and bot ownership before a delayed module can mount its previous props',async()=>{
 const old=deferred(),next=deferred();imports.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);await render();
 const changed={...baseProps(),workspaceId:'00000000-0000-4000-8000-000000009991',bot:{address:'research',team_revision:3}};
 await render({props:changed});await act(async()=>old.resolve({ResearchWorkspace:Probe}));expect(mounts).not.toHaveBeenCalled();
 await act(async()=>next.resolve({ResearchWorkspace:Probe}));await wait(()=>expect(mounts).toHaveBeenCalledOnce());expect(received.at(-1)?.workspaceId).toBe(changed.workspaceId);expect(received.at(-1)?.bot).toEqual(changed.bot);noEffects();
});
it('loads actual Research with an encrypted uncertain request and resolves only its original reviewed key',async()=>{
 const request:ResearchSearch={contract_version:1,idempotency_key:crypto.randomUUID(),expected_revision:2,team_revision:1,bot:researchBotId,
   topic:'literature',sources:['pubmed'],query:'Invented general public question',public_query_confirmed:true};
 await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`));await journal.persist(editorAddress(researchWorkspaceId,`research:${researchBotId}`),editorDraft(researchWorkspaceId,`research:${researchBotId}`,{version:1,bot:researchBotId,topic:'literature',query:request.query,sources:['pubmed'],pending:{kind:'search',request}},request.idempotency_key));
 const loading=deferred();imports.mockReturnValue(loading.promise);await render();expect((await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`)))?.pending).toBe(request.idempotency_key);noEffects();
 await act(async()=>loading.resolve({ResearchWorkspace}));await wait(()=>expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Restore research draft')).toBe(true));expect(port.catalog).toHaveBeenCalledOnce();noEffects();
 await click('Restore research draft');await wait(()=>expect(host.textContent).toContain('Research request retained'));noEffects();await click('Check saved result');await wait(()=>expect(host.textContent).toContain('Sources retrieved'));
 expect(port.resolve).toHaveBeenCalledOnce();expect(vi.mocked(port.resolve).mock.calls[0][2]).toEqual(request);expect(port.search).not.toHaveBeenCalled();expect(port.save).not.toHaveBeenCalled();expect((await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`)))?.pending).toBeNull();
});
