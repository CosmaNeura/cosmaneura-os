import {act} from 'react';
import {waitMessagesJourney as wait, MESSAGES_JOURNEY_TEST_TIMEOUT_MS} from './messages-journey-wait';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const key of ['VITE_MESSAGES_ENABLED','VITE_EHR_READ_ENABLED','VITE_CALENDAR_IMPORT_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi} from './workspace-api';
import {ehrReadApi} from './ehr-read-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');

// Journey waits may legitimately exceed Vitest's 5s default under CI load.
vi.setConfig({testTimeout: MESSAGES_JOURNEY_TEST_TIMEOUT_MS});
let root:Root,host:HTMLDivElement;
const visible=(element:Element)=>!element.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(item=>visible(item)&&(item.textContent?.trim()===name||item.getAttribute('aria-label')===name||item.querySelector('strong')?.textContent===name));
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question');
const task=()=>[...host.querySelectorAll<HTMLElement>('.ehr-read-task')].find(visible);
const pressed=(label:string)=>[...host.querySelectorAll<HTMLElement>('[role="group"]')].find(group=>visible(group)&&group.getAttribute('aria-label')===label)?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')?.textContent;

async function click(name:string){await wait(()=>expect(button(name)).toBeTruthy());await wait(()=>expect(button(name)!.disabled).toBe(false));await act(async()=>{button(name)!.focus({preventScroll:true});button(name)!.click();});}
async function openChat(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('.messages-row')].find(item=>visible(item)&&item.textContent?.includes('Chief of Staff'));await wait(()=>expect(row()).toBeTruthy());await wait(()=>expect(row()!.disabled).toBe(false));await act(async()=>row()!.click());await wait(()=>expect(question()).toBeTruthy());await wait(()=>expect(question()!.disabled).toBe(false));}
async function draft(value:string){await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question(),value);question()!.dispatchEvent(new Event('input',{bubbles:true}));});}
async function relay(provider:'Tebra'|'Athena'|'Atlas.MD',action:string){
 await openChat();await draft('Keep my original Chief directions.');await click('‹ Messages');await click('Settings');await click('EHR & Rx Relay');await click(provider);
 const relayStatus=[...host.querySelectorAll<HTMLElement>('[aria-label="Rx Relay"]')].find(visible);expect(relayStatus?.textContent).toContain('Not connected for sending.');
 await click(action);await wait(()=>expect(task()).toBeDefined());
}
async function confirm(reviewLabel:string,checksLabel:string){
 const details=()=>[...host.querySelectorAll<HTMLDetailsElement>(`[aria-label="${reviewLabel}"] details`)].find(visible);
 await wait(()=>expect(details()).toBeTruthy());await act(async()=>{details()!.open=true;details()!.dispatchEvent(new Event('toggle'));});
 const inputs=()=>[...host.querySelectorAll<HTMLInputElement>(`[aria-label="${checksLabel}"] input[type="checkbox"]`)].filter(visible);
 await wait(()=>{expect(inputs()).toHaveLength(3);expect(inputs().every(input=>!input.disabled&&!input.closest('fieldset')?.disabled)).toBe(true);});
 for(const input of inputs())await act(async()=>input.click());
}
async function patient(){const row=()=>[...host.querySelectorAll<HTMLButtonElement>('ul[aria-label="Authorized clinical patients"] button')].find(visible);await wait(()=>expect(row()).toBeTruthy());await wait(()=>expect(row()!.disabled).toBe(false));await act(async()=>row()!.click());}
async function returned(marker:string){
 await wait(()=>{const field=question();expect(field&&visible(field)).toBeTruthy();expect(field!.disabled).toBe(false);expect(field!.value.startsWith('Keep my original Chief directions.')).toBe(true);expect(field!.value).toContain(marker);});
 expect(task()).toBeUndefined();expect(button('Send prescription')).toBeUndefined();expect(host.textContent).not.toContain('Prescription sent');
 expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);vi.spyOn(workspaceApi,'ask');vi.spyOn(workspaceApi,'append');vi.spyOn(ehrReadApi,'execute');
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});

it('saves invented Tebra medication records for Chief from EHR and Rx Relay without sending',async()=>{
 await relay('Tebra','Open Tebra records');await wait(()=>expect(pressed('Records system')).toBe('Tebra'));await wait(()=>expect(pressed('Tebra records')).toBe('Medication records'));
 await click('Check Tebra medication access');await click('Load authorized patients');await patient();await click('Read medication records');
 await wait(()=>expect(task()?.textContent).toContain('Invented Tebra medication'));expect(button('Save reviewed medication records')?.disabled).toBe(true);await confirm('Review Tebra medication records','Tebra medication review');
 const stats=()=>(window as unknown as {tebraMedicationRehearsalStats:{patientLists:number;medicationReads:number;reviews:number;externalCalls:number}}).tebraMedicationRehearsalStats;
 await click('Save reviewed medication records');await click('Prepare Chief draft');await returned('human-selected EHR source');
 expect(stats()).toMatchObject({patientLists:1,medicationReads:1,reviews:1,externalCalls:0});
});

it('saves invented Athena allergy records for Chief from EHR and Rx Relay without sending',async()=>{
 await relay('Athena','Open Athena records');await wait(()=>expect(pressed('Records system')).toBe('Athena'));await wait(()=>expect(pressed('Athena records')).toBe('Allergy records'));
 await click('Check Athena allergy access');await click('Load authorized patients');await patient();await click('Read allergy records');
 await wait(()=>expect(task()?.textContent).toContain('Invented Athena allergen'));expect(button('Save reviewed allergy records')?.disabled).toBe(true);await confirm('Review Athena allergy records','Athena allergy review');
 const stats=()=>(window as unknown as {athenaAllergyRehearsalStats:{patientLists:number;allergyReads:number;reviews:number;externalCalls:number}}).athenaAllergyRehearsalStats;
 await click('Save reviewed allergy records');await click('Prepare Chief draft');await returned('human-selected EHR source');
 expect(stats()).toMatchObject({patientLists:1,allergyReads:1,reviews:1,externalCalls:0});
});

it('saves an invented Atlas.MD calendar file for Chief from EHR and Rx Relay without a live chart',async()=>{
 await relay('Atlas.MD','Import Atlas.MD calendar file');expect(task()?.textContent).toContain('Import calendar file');expect(task()?.textContent).toContain('not a live chart');
 await click('Check import access');
 const date=()=>host.querySelector<HTMLInputElement>('.calendar-import-panel input[type="date"]');
 await wait(()=>expect(date()?.disabled).toBe(false));expect(host.querySelector<HTMLSelectElement>('.calendar-import-panel select[aria-label="Calendar source"]')?.value).toBe('atlas_md');
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(date(),'2026-10-25');date()!.dispatchEvent(new Event('input',{bubbles:true}));});
 await wait(()=>expect(date()?.value).toBe('2026-10-25'));
 const input=()=>host.querySelector<HTMLInputElement>('.calendar-import-panel input[type="file"]');await wait(()=>expect(input()?.disabled).toBe(false));
 const bytes=new TextEncoder().encode((window as unknown as {calendarImportRehearsalFile:string}).calendarImportRehearsalFile),value=new File([bytes],'never-retain-this-name.ics',{type:'text/calendar'});Object.defineProperty(value,'arrayBuffer',{value:async()=>bytes.buffer});
 await act(async()=>{Object.defineProperty(input()!,'files',{configurable:true,value:[value]});input()!.dispatchEvent(new Event('change',{bubbles:true}));});
 await click('Import selected file');await wait(()=>expect(task()?.textContent).toContain('Atlas.md'));await wait(()=>expect(task()?.textContent).toContain('Invented calendar visit'));
 const event=()=>[...host.querySelectorAll<HTMLButtonElement>('ul[aria-label="Imported calendar events"] button')].find(visible);await wait(()=>expect(event()?.disabled).toBe(false));await act(async()=>event()!.click());
 const checks=()=>[...host.querySelectorAll<HTMLInputElement>('.calendar-import-panel input[type="checkbox"]')].filter(visible);
 await wait(()=>{expect(checks()).toHaveLength(3);expect(checks().every(item=>!item.disabled&&!item.closest('fieldset')?.disabled)).toBe(true);});
 for(const item of checks())await act(async()=>item.click());
 const stats=()=>(window as unknown as {calendarImportRehearsalStats:{uploads:number;reviews:number;externalCalls:number}}).calendarImportRehearsalStats;
 await click('Save calendar summary');await click('Prepare Chief draft');await returned('human-selected imported calendar summary');
 expect(stats()).toMatchObject({uploads:1,reviews:1,externalCalls:0});expect(ehrReadApi.execute).not.toHaveBeenCalled();
});
