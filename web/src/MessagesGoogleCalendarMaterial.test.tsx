import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi,type Workspace,type WorkspaceEntry} from './workspace-api';
import {googleCalendarApi} from './google-calendar-api';
import {conversationsApi} from './conversations-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const source:WorkspaceEntry={id:'00000000-0000-4000-8000-000000009501',revision:1,kind:'google_calendar',content:'Invented saved calendar snapshot. Starts 2026-10-27T09:30:00-04:00; ends 2026-10-27T10:00:00-04:00. This does not verify current availability.',source_label:'Google calendar: Invented follow-up',calendar_source_state:'current',origin:'authenticated_human',ticket:null,created_at:'2026-10-26T12:15:00Z'};
let root:Root,host:HTMLDivElement,unavailable:boolean;
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
const composer=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
async function wait(check:()=>void){for(let n=0;n<300;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>{button(name)!.focus({preventScroll:true});button(name)!.click();});}
async function openChief(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(b=>visible(b)&&b.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()?.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(composer()?.disabled).toBe(false));}
function withSummary(workspace:Workspace):Workspace{return {...workspace,revision:workspace.revision+1,entries:[...workspace.entries,{...source,revision:workspace.revision+1,calendar_source_state:unavailable?'unavailable':'current',...(unavailable?{source_label:'Unavailable calendar source',content:''}:{})}]};}
beforeEach(async()=>{
 unavailable=false;vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 const open=workspaceApi.openExisting,read=workspaceApi.read;vi.spyOn(workspaceApi,'openExisting').mockImplementation(async(...args)=>{const value=await open(...args);return {...value,workspace:withSummary(value.workspace)};});vi.spyOn(workspaceApi,'read').mockImplementation(async(...args)=>withSummary(await read(...args)));
 for(const method of ['status','observe','resolve','inspect','review'] as const)vi.spyOn(googleCalendarApi,method);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));await openChief();
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it.each([{withdrawn:false,clamped:false},{withdrawn:false,clamped:true},{withdrawn:true,clamped:false}])('opens the exact saved calendar source and returns draft/focus/reading position without provider or read-marker changes ($withdrawn/$clamped)',async({withdrawn,clamped})=>{
 const draft='Keep these exact unsent Chief directions while I check my calendar summary.';await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(composer(),draft);composer().dispatchEvent(new Event('input',{bubbles:true}));});
 if(withdrawn){unavailable=true;await click('‹ Messages');await openChief();}
 const card=host.querySelector<HTMLElement>(`[data-entry-id="source:${source.id}"]`);expect(card).not.toBeNull();expect(card!.getAttribute('aria-label')).toBe('Saved Google Calendar summary');expect(card!.textContent).toContain('Event snapshot only');expect(card!.textContent).not.toContain(source.content);expect(card!.querySelector('h3')?.textContent).toBe(withdrawn?'Unavailable calendar summary':source.source_label);if(withdrawn)expect(card!.textContent).not.toContain('Invented follow-up');
 const control=card!.querySelector<HTMLButtonElement>('button')!,scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!,marks=vi.spyOn(conversationsApi,'mark'),reads=vi.spyOn(conversationsApi,'read');Object.defineProperty(scroll,'clientHeight',{configurable:true,value:200});Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:1100});
 if(clamped){scroll.scrollTop=900;await act(async()=>scroll.dispatchEvent(new Event('scroll')));await wait(()=>expect(marks.mock.calls.some(([, , ,command])=>command?.watermark!==undefined&&command.manual_unread===undefined)).toBe(true));await act(async()=>{await Promise.all(marks.mock.results.map(result=>result.value));});}
 scroll.scrollTop=230;await act(async()=>scroll.dispatchEvent(new Event('scroll')));const markCount=marks.mock.calls.length,readCount=reads.mock.calls.length,workspaceReads=vi.mocked(workspaceApi.read).mock.calls.length,turns=[...host.querySelectorAll('.team-turn')].map(e=>e.getAttribute('data-entry-id'));
 await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe('source-'+source.id));const selected=document.getElementById('source-'+source.id)!;expect(selected.classList.contains('selected')).toBe(true);
 if(withdrawn){expect(selected.textContent).toContain('This calendar summary is unavailable');expect(selected.textContent).not.toContain('Invented follow-up');expect(selected.textContent).not.toContain(source.content);}else expect(selected.querySelector(':scope > p')?.textContent).toBe(source.content);
 if(clamped)Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:375});await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));expect(scroll.scrollTop).toBe(clamped?175:230);expect(composer().value).toBe(draft);expect(document.activeElement).not.toBe(composer());expect(document.activeElement?.closest('[hidden]')).toBeNull();expect([...host.querySelectorAll('.team-turn')].map(e=>e.getAttribute('data-entry-id'))).toEqual(turns);
 expect(marks).toHaveBeenCalledTimes(markCount);expect(reads).toHaveBeenCalledTimes(readCount);expect(workspaceApi.read).toHaveBeenCalledTimes(workspaceReads);for(const method of ['status','observe','resolve','inspect','review'] as const)expect(googleCalendarApi[method]).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});
