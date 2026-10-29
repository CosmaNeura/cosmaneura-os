import {act,useEffect,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {SettingsHub} from './SettingsHub';
import {EhrReadTask} from './EhrReadTask';
import {readConnectionCatalog,type ConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {readinessFixture} from './connection-readiness-fixture';
import {WorkspaceApiError} from './workspace-api';
vi.mock('./connection-catalog-api',async original=>({...await original<typeof import('./connection-catalog-api')>(),readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async original=>({...await original<typeof import('./connection-summary')>(),readConnectionSummary:vi.fn()}));
let host:HTMLDivElement,root:Root;
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
const visible=(e:Element|null|undefined)=>!!e&&!e.closest('[hidden]');
const button=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(e=>visible(e)&&e.textContent===label);
const chrome=()=>host.querySelector('.settings-hub-nav');
async function wait(check:()=>void){for(let i=0;i<150;i++){let pass=false;await act(async()=>{await new Promise(r=>setTimeout(r,1));try{check();pass=true;}catch{}});if(pass)return;}check();}
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.mocked(readConnectionCatalog).mockResolvedValue(readinessFixture());vi.mocked(readConnectionSummary).mockResolvedValue({label:'Connected',reason:'Invented account connected',action:'Open',tone:'ready'});});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('gives an actually shown Gmail task one Back navigation and keeps the same editor across permission and task return',async()=>{
 const mounted=vi.fn(),unmounted=vi.fn(),outerFocus=vi.spyOn(HTMLElement.prototype,'focus');
 function Editor({open,onBack}:{open:boolean;onBack:()=>void}){useEffect(()=>{mounted();return unmounted;},[]);return <><div hidden={open}><button>Connect Google for email</button></div><EhrReadTask open={open} title="Review Gmail email" context="Invented task" returnLabel="Back to Chief" returnBlocked={false} onReturn={onBack}><input aria-label="Retained email draft" defaultValue="Invented retained value"/></EhrReadTask></>;}
 function App(){const [task,setTask]=useState(true);return <><button onClick={()=>setTask(true)}>Reopen Gmail task</button><SettingsHub {...{googleTaskPresentation:task}} open initialScreen="google" google={<Editor open={task} onBack={()=>setTask(false)}/>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/></>;}
 await act(async()=>root.render(<App/>));await wait(()=>expect(document.activeElement).toBe(host.querySelector('.ehr-read-task h1')));
 expect(visible(chrome())).toBe(false);expect(visible(host.querySelector('.settings-hub-heading'))).toBe(false);expect(host.querySelector('[aria-label="Settings"]')).toBeNull();expect(button('‹ Back to Chief')).toBeDefined();
 const field=host.querySelector<HTMLInputElement>('[aria-label="Retained email draft"]')!;field.value='Keep this local selection';expect(outerFocus.mock.contexts).not.toContain(host.querySelector('.settings-hub-heading h1'));
 await act(async()=>button('‹ Back to Chief')!.click());expect(visible(chrome())).toBe(true);expect(button('Done')).toBeDefined();expect(button('Connect Google for email')).toBeDefined();expect(document.activeElement).toBe(host.querySelector('.settings-hub-heading h1'));
 await act(async()=>button('Reopen Gmail task')!.click());await wait(()=>expect(document.activeElement).toBe(host.querySelector('.ehr-read-task h1')));expect(visible(chrome())).toBe(false);expect(host.querySelector('[aria-label="Retained email draft"]')).toBe(field);expect(field.value).toBe('Keep this local selection');expect(mounted).toHaveBeenCalledOnce();expect(unmounted).not.toHaveBeenCalled();expect(readConnectionCatalog).not.toHaveBeenCalled();
});

it.each(['pending','setup','denied'] as const)('keeps outer escape and exact availability/setup states while the requested Gmail editor is hidden (%s)',async state=>{
 let finish!:(value:ConnectionCatalog)=>void,deny!:(value:unknown)=>void;vi.mocked(readConnectionCatalog).mockReturnValueOnce(new Promise((resolve,reject)=>{finish=resolve;deny=reject;}));const mounted=vi.fn(),lost=vi.fn();
 function Editor(){useEffect(()=>{mounted();},[]);return <EhrReadTask open title="Review Gmail email" context="Invented task" returnLabel="Back to Chief" returnBlocked={false} onReturn={()=>{}}><p>Saved email details</p></EhrReadTask>;}
 await act(async()=>root.render(<SettingsHub {...{googleTaskPresentation:true}} open initialScreen="google" connectionIdentity={identity} onConnectionAccessLost={lost} google={<Editor/>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 if(state==='setup'){const catalog=readinessFixture();catalog.google=false;await act(async()=>finish(catalog));await wait(()=>expect(host.textContent).toContain('Needs setup'));}
 if(state==='denied'){await act(async()=>deny(new WorkspaceApiError(403)));await wait(()=>expect(lost).toHaveBeenCalledOnce());}
 expect(visible(chrome())).toBe(true);expect(button('Done')).toBeDefined();expect(button('← All connections')).toBeDefined();expect(mounted).not.toHaveBeenCalled();expect([...host.querySelectorAll('.ehr-read-task')].some(visible)).toBe(false);
 if(state==='pending')expect(host.textContent).toContain('Checking whether this service is enabled');if(state==='denied')expect(host.textContent).toContain('Sign in to CosmasOS again');
});

it.each(['denied','setup'] as const)('switches only the chrome when the exact existing catalog gate reveals or later hides a retained Gmail editor (%s)',async fallback=>{
 let finish!:(value:ConnectionCatalog)=>void;vi.mocked(readConnectionCatalog).mockReturnValueOnce(new Promise(resolve=>{finish=resolve;}));const mounted=vi.fn(),unmounted=vi.fn();
 function Editor(){useEffect(()=>{mounted();return unmounted;},[]);return <EhrReadTask open title="Review Gmail email" context="Invented task" returnLabel="Back to Chief" returnBlocked={false} onReturn={()=>{}}><input defaultValue="Retained source"/></EhrReadTask>;}
 const render=(open:boolean)=>act(async()=>root.render(<SettingsHub {...{googleTaskPresentation:true}} open={open} initialScreen="google" connectionIdentity={identity} google={<Editor/>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 await render(true);expect(visible(chrome())).toBe(true);await act(async()=>finish(readinessFixture()));await wait(()=>expect(visible(chrome())).toBe(false));const field=host.querySelector('[data-settings-screen="google"] input');expect(field).not.toBeNull();expect(mounted).toHaveBeenCalledOnce();expect(readConnectionCatalog).toHaveBeenCalledOnce();
 await render(false);if(fallback==='denied')vi.mocked(readConnectionCatalog).mockRejectedValueOnce(new WorkspaceApiError(403));else{const removed=readinessFixture();removed.google=false;vi.mocked(readConnectionCatalog).mockResolvedValueOnce(removed);}await render(true);await wait(()=>expect(host.textContent).toContain(fallback==='denied'?'Sign in to CosmasOS again':'Needs setup'));expect(visible(chrome())).toBe(true);expect(host.querySelector('[data-settings-screen="google"]')?.hasAttribute('hidden')).toBe(true);expect(host.querySelector('[data-settings-screen="google"] input')).toBe(field);expect(unmounted).not.toHaveBeenCalled();expect(readConnectionCatalog).toHaveBeenCalledTimes(2);
});

it('keeps an existing catalog-recovery warning visible when the editor gate permits its task',async()=>{
 vi.mocked(readConnectionCatalog).mockRejectedValueOnce(new WorkspaceApiError(502));
 await act(async()=>root.render(<SettingsHub {...{googleTaskPresentation:true}} open initialScreen="google" connectionIdentity={identity} google={<EhrReadTask open title="Review Gmail email" context="Invented task" returnLabel="Back to Chief" returnBlocked={false} onReturn={()=>{}}><p>Check private saved work</p></EhrReadTask>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 await wait(()=>expect(visible(chrome())).toBe(false));expect(visible(host.querySelector('[aria-label="Connection availability"]'))).toBe(true);expect(button('Check availability again')).toBeDefined();expect(button('‹ Back to Chief')).toBeDefined();expect(host.textContent).toContain('Service availability could not be confirmed');
});

it.each(['missing-editor','different-screen'] as const)('never hides ordinary Settings navigation for an inapplicable task request (%s)',async mode=>{
 await act(async()=>root.render(<SettingsHub {...{googleTaskPresentation:true}} open initialScreen={mode==='different-screen'?'microsoft':'google'} google={mode==='missing-editor'?undefined:<p>Gmail</p>} microsoft={<button>Open Outlook</button>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 expect(visible(chrome())).toBe(true);expect(button('Done')).toBeDefined();if(mode==='different-screen')expect(button('Open Outlook')).toBeDefined();
});
