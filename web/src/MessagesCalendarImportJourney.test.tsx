import {act} from 'react';
import {waitMessagesJourney as wait} from './messages-journey-wait';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_MESSAGES_ENABLED','true');vi.stubEnv('VITE_EHR_READ_ENABLED','true');vi.stubEnv('VITE_CALENDAR_IMPORT_ENABLED','true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi} from './workspace-api';
import {calendarImportApi,type CalendarReviewResponse} from './calendar-import-api';
import {conversationsApi} from './conversations-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const visibleButton=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(button=>!button.closest('[hidden]')&&(button.textContent?.trim()===name||button.getAttribute('aria-label')===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;

async function click(label:string){await wait(()=>expect(visibleButton(label)).toBeTruthy());await wait(()=>expect(visibleButton(label)!.disabled).toBe(false));await act(async()=>{visibleButton(label)!.focus();visibleButton(label)!.click();});}
async function draft(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question().dispatchEvent(new Event('input',{bubbles:true}));});}
async function openTask(){await click('Details');await click('Choose notes or sources');await click('Import calendar file');await wait(()=>expect(visibleButton('Check import access')??visibleButton('Restore saved calendar import')).toBeTruthy());}
async function file(){const input=host.querySelector<HTMLInputElement>('.calendar-import-panel input[type="file"]')!;await wait(()=>expect(input.disabled).toBe(false));const bytes=new TextEncoder().encode((window as unknown as {calendarImportRehearsalFile:string}).calendarImportRehearsalFile),value=new File([bytes],'never-retain-this-name.ics',{type:'text/calendar'});Object.defineProperty(value,'arrayBuffer',{value:async()=>bytes.buffer});await act(async()=>{Object.defineProperty(input,'files',{configurable:true,value:[value]});input.dispatchEvent(new Event('change',{bubbles:true}));});}
async function choose(){await wait(()=>expect(host.querySelector<HTMLButtonElement>('ul[aria-label="Imported calendar events"] button')).toBeTruthy());await wait(()=>expect(host.querySelector<HTMLButtonElement>('ul[aria-label="Imported calendar events"] button')!.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('ul[aria-label="Imported calendar events"] button')!.click());await wait(()=>expect(host.querySelector('.calendar-import-panel input[type="checkbox"]')?.closest('fieldset')?.disabled).toBe(false));for(const check of host.querySelectorAll<HTMLInputElement>('.calendar-import-panel input[type="checkbox"]'))await act(async()=>check.click());}
async function changeWeek(){const input=host.querySelector<HTMLInputElement>('.calendar-import-panel input[type="date"]')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,'2026-10-25');input.dispatchEvent(new Event('input',{bubbles:true}));});}
async function saveCalendar():Promise<CalendarReviewResponse>{const review=vi.spyOn(calendarImportApi,'review');await draft('Keep my original calendar directions.');await openTask();await click('Check import access');await changeWeek();await file();await click('Import selected file');await choose();await click('Save calendar summary');await wait(()=>expect(visibleButton('Prepare Chief draft')).toBeTruthy());await wait(()=>expect(visibleButton('Prepare Chief draft')!.disabled).toBe(false));const receipt=await review.mock.results[0].value;await click('Prepare Chief draft');await wait(()=>expect(question().value).toContain('human-selected imported calendar summary'));return receipt;}
const calendarStats=()=>(window as unknown as {calendarImportRehearsalStats:{uploads:number;reviews:number;resolves:number;inspects:number;revokes:number;externalCalls:number}}).calendarImportRehearsalStats;
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
 await wait(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')).toBeTruthy());await wait(()=>expect(host.querySelector<HTMLButtonElement>('.messages-row')!.disabled).toBe(false));await act(async()=>host.querySelector<HTMLButtonElement>('.messages-row')!.click());await wait(()=>expect(question()).toBeTruthy());await wait(()=>expect(question()!.disabled).toBe(false));
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});

it('returns from import to visible Details without opening the keyboard, preserving one mounted task and draft',async()=>{await draft('Retain my calendar directions.');const composer=question();await openTask();const panel=host.querySelector('.calendar-import-panel');await wait(()=>expect(document.activeElement).toBe(host.querySelector('.ehr-read-task h1')));expect(composer.closest('[hidden]')).not.toBeNull();await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(visibleButton('Details')));expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(document.activeElement).not.toBe(composer);expect(question()).toBe(composer);expect(composer.value).toBe('Retain my calendar directions.');await openTask();expect(host.querySelector('.calendar-import-panel')).toBe(panel);expect(workspaceApi.ask).not.toHaveBeenCalled();});
it('imports from Chief Details, recovers both lost replies, and prepares the retained draft without sending',async()=>{history.replaceState(history.state,'','?scenario=calendar-import-lost-replies'+location.hash);await draft('Keep original Chief directions.');await openTask();await click('Check import access');await changeWeek();await file();await click('Import selected file');await click('Check saved import result');await choose();await click('Save calendar summary');await click('‹ Back to Chief of Staff');await openTask();await click('Restore saved calendar import');await click('Check saved source result');await click('Check import access');await click('Prepare Chief draft');await wait(()=>expect(question().value).toContain('human-selected imported calendar summary'));expect(question().value).toContain('Keep original Chief directions.');expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();expect((window as unknown as {calendarImportRehearsalStats:object}).calendarImportRehearsalStats).toMatchObject({uploads:1,reviews:2,resolves:1,externalCalls:0});});
it('returns to the visible calendar launcher in Saved sources and retains unsent directions',async()=>{await draft('Retain source directions.');await click('Details');await click('Choose notes or sources');await click('Saved sources');await click('Import calendar file');await wait(()=>expect(visibleButton('Check import access')).toBeTruthy());await click('‹ Back to saved sources');await wait(()=>expect(document.activeElement).toBe(visibleButton('Import calendar file')));expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(question().value).toBe('Retain source directions.');expect(workspaceApi.ask).not.toHaveBeenCalled();});

it.each([false,true])('opens the reviewed calendar summary from its Chief card and restores exact source, draft, focus and reading position (clamped=%s)',async clamped=>{
 const marks=vi.spyOn(conversationsApi,'mark'),reads=vi.spyOn(conversationsApi,'read'),receipt=await saveCalendar(),retained=question().value;
 expect(retained.startsWith('Keep my original calendar directions.\n\n')).toBe(true);
 const card=host.querySelector<HTMLElement>(`[data-entry-id="source:${receipt.entry_id}"]`);expect(card).not.toBeNull();
 expect(card!.getAttribute('aria-label')).toBe('Saved calendar file summary');expect(card!.textContent).toContain('File snapshot only');expect(card!.textContent).not.toContain('Invented calendar visit');expect(card!.textContent).not.toContain('Atlas.md');
 const control=card!.querySelector<HTMLButtonElement>('button')!,scroll=host.querySelector<HTMLElement>('.mobile-chat-scroll')!;
 Object.defineProperty(scroll,'clientHeight',{configurable:true,value:200});Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:1100});
 if(clamped){
  // A smaller viewport range may legitimately reveal the latest reply. Start
  // this clamp case with that reply already read, then move back to older text.
  // The non-clamping case deliberately leaves the lower reply unread.
  scroll.scrollTop=900;await act(async()=>scroll.dispatchEvent(new Event('scroll')));
  await wait(()=>expect(marks.mock.calls.some(([, , ,command])=>command?.watermark!==undefined&&command.manual_unread===undefined)).toBe(true);
  await act(async()=>{await Promise.all(marks.mock.results.map(result=>result.value));});
 }
 const initialReadState=await conversationsApi.read(identity,null);expect(initialReadState.rows.find(row=>row.workspace_id===receipt.workspace.id&&row.bot.role==='chief')?.unread).toBe(!clamped);
 scroll.scrollTop=230;await act(async()=>scroll.dispatchEvent(new Event('scroll')));
 const before=structuredClone(calendarStats()),markCount=marks.mock.calls.length,readCount=reads.mock.calls.length,turnIds=[...host.querySelectorAll('.team-turn')].map(x=>x.getAttribute('data-entry-id'));
 await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe('source-'+receipt.entry_id));
 const shown=document.getElementById('source-'+receipt.entry_id)!;expect(shown.classList.contains('selected')).toBe(true);expect(shown.textContent).toContain('Imported calendar summary · file snapshot only');expect(shown.querySelector(':scope > p')?.textContent).toBe(receipt.workspace.entries.find(x=>x.id===receipt.entry_id)!.content);expect(question().value).toBe(retained);
 if(clamped)Object.defineProperty(scroll,'scrollHeight',{configurable:true,value:375});
 await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));expect(document.activeElement?.closest('[hidden]')).toBeNull();expect(document.activeElement).not.toBe(question());await wait(()=>expect(scroll.scrollTop).toBe(clamped?175:230));expect(question().value).toBe(retained);
 expect(host.querySelector('.messages-new-replies')).toBeNull();expect([...host.querySelectorAll('.team-turn')].map(x=>x.getAttribute('data-entry-id'))).toEqual(turnIds);expect(calendarStats()).toEqual(before);expect(marks).toHaveBeenCalledTimes(markCount);expect(reads).toHaveBeenCalledTimes(readCount);expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});

it('updates the exact calendar card to unavailable after stopping its import and exposes only the source placeholder',async()=>{
 const receipt=await saveCalendar(),retained=question().value,card=()=>host.querySelector<HTMLElement>(`[data-entry-id="source:${receipt.entry_id}"]`);expect(card()).not.toBeNull();
 await openTask();if(visibleButton('Restore saved calendar import'))await click('Restore saved calendar import');await click('Check import access');await click('Stop using this import');await wait(()=>expect(visibleButton('Prepare Chief draft')?.disabled).toBe(true));await click('‹ Back to Chief of Staff');
 await wait(()=>expect(card()?.querySelector('h3')?.textContent).toBe('Unavailable calendar file summary');expect(card()!.textContent).not.toContain('Invented calendar visit');expect(card()!.textContent).not.toContain('Atlas.md');expect(card()!.textContent).toContain('Unavailable — check access');
 const before=structuredClone(calendarStats()),control=card()!.querySelector<HTMLButtonElement>('button')!;await act(async()=>control.click());await wait(()=>expect(document.activeElement?.id).toBe('source-'+receipt.entry_id));
 const shown=document.getElementById('source-'+receipt.entry_id)!;expect(shown.textContent).toContain('This imported calendar summary is unavailable');expect(shown.textContent).not.toContain('Invented calendar visit');await click('‹ Back to Chief of Staff');await wait(()=>expect(document.activeElement).toBe(control));expect(question().value).toBe(retained);expect(calendarStats()).toEqual(before);expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
});
