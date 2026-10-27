import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{
 for(const key of ['VITE_MESSAGES_ENABLED','VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED'])vi.stubEnv(key,'true');
 for(const key of ['VITE_EHR_READ_ENABLED','VITE_CALENDAR_IMPORT_ENABLED'])vi.stubEnv(key,'false');
 vi.stubEnv('VITE_COSMAS_ENV','synth_os');
});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {workspaceApi} from './workspace-api';
import {ehrReadApi} from './ehr-read-api';
import {calendarImportApi} from './calendar-import-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {PRESENTATION_KEY} from './session/presentation';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let root:Root,host:HTMLDivElement;
const visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name||b.querySelector('strong')?.textContent===name));
async function wait(check:()=>void){for(let n=0;n<300;n++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();done=true;}catch{}});if(done)return;}check();}
async function click(name:string){await wait(()=>expect(button(name)?.disabled,name).toBe(false));await act(async()=>{button(name)!.focus({preventScroll:true});button(name)!.click();});}
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);localStorage.clear();sessionStorage.clear();localStorage.setItem(PRESENTATION_KEY,'messages');history.replaceState(null,'','#cosmas/home');
 window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();await installFixtures(true);
 host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));await wait(()=>expect(host.querySelector('.messages-row')).not.toBeNull());
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});
it('shows all four records systems with both hosted action flags off without offering a connection or making a records request',async()=>{
 const execute=vi.spyOn(ehrReadApi,'execute'),inspect=vi.spyOn(ehrReadApi,'inspect'),upload=vi.spyOn(calendarImportApi,'upload'),importInspect=vi.spyOn(calendarImportApi,'inspect'),append=vi.spyOn(workspaceApi,'append'),ask=vi.spyOn(workspaceApi,'ask');
 await click('Settings');await click('Connections');expect(host.querySelector('[aria-label="Practice records catalog"]')).toBeNull();await click('Add connection');
 const catalog=host.querySelector<HTMLElement>('[aria-label="Practice records catalog"]');expect(catalog).not.toBeNull();
 const rows=[...catalog!.querySelectorAll<HTMLButtonElement>('[data-practice-record-provider]')];expect(rows.map(row=>row.querySelector('strong')?.textContent)).toEqual(['Atlas.MD','Elation','Tebra','Athena']);
 for(const row of rows){expect(visible(row)).toBe(true);expect(row.disabled).toBe(true);expect(row.textContent).toContain('Not available in this app');expect(row.textContent).not.toContain('Connected');expect(row.textContent).not.toContain('Access checked when opened');await act(async()=>row.click());}
 expect(host.querySelector('.ehr-read-task')).toBeNull();expect(execute).not.toHaveBeenCalled();expect(inspect).not.toHaveBeenCalled();expect(upload).not.toHaveBeenCalled();expect(importInspect).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();
 await click('Back to connections');expect(host.querySelector('[aria-label="Practice records catalog"]')).toBeNull();expect(document.activeElement).toBe(button('Add connection'));await click('Choose your records system');expect(host.querySelectorAll('[data-practice-record-provider]')).toHaveLength(4);
});
