import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_VENDOR_SETUP_ENABLED','true');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {accountIdentityApi} from './account-identity-api';
import {modelActivityApi} from './model-activity-api';
import {activityIdentity} from './model-activity-test-fixture';
import {teamFixture} from './team-setup-test-fixture';
import {teamSetupApi} from './team-setup-api';
import {vendorSetupApi} from './vendor-setup-api';
import {setupFixture} from './vendor-setup-test-fixture';
import {memoryDraftStorage} from './draft-test-fixture';
import {privateDraftScope} from './draft-store';
import {accountEditorAddress} from './draft-journal';
import {settingsNavigation} from './settings-test-navigation';
vi.mock('./team-setup-api',()=>({teamSetupApi:{read:vi.fn(),rehearse:vi.fn()}}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-context-navigation'};
let host:HTMLDivElement,root:Root,storage:ReturnType<typeof memoryDraftStorage>,reject:(reason:unknown)=>void,resolve:(value:typeof activityIdentity)=>void;
const team=teamFixture(),visible=(e:Element)=>!e.closest('[hidden]');
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&(b.textContent?.replace(/[←→›↗]/g,'').trim()===name||[...b.querySelectorAll('strong')].some(s=>s.textContent?.trim()===name)));
const wait=async(check:()=>void|Promise<void>)=>{for(let i=0;i<100;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{await check();done=true;}catch{}});if(done)return;}await check();};
const click=async(name:string)=>{await wait(()=>{expect(button(name),name).toBeTruthy();expect(button(name)!.matches(':disabled'),name).toBe(false);});await act(async()=>button(name)!.click());if(['Done','All settings'].includes(name)&&button('Keep draft and continue'))await act(async()=>button('Keep draft and continue')!.click());};
const input=async(field:HTMLInputElement|HTMLTextAreaElement,value:string)=>{await act(async()=>{Object.getOwnPropertyDescriptor(field.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});};
const configName=()=>[...host.querySelectorAll('label')].find(label=>visible(label)&&label.textContent?.startsWith('Configuration name'))?.querySelector('input') as HTMLInputElement;
async function saved(address:string){const scope=await privateDraftScope(team.recovery_scope!,'http://127.0.0.1:8000',webcrypto),store=await storage({scope});try{return (await store.read(address)).value?.body;}finally{store.close();}}
async function mount(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await click('Team settings');await wait(()=>expect(accountIdentityApi.read).toHaveBeenCalled());}
beforeEach(async()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_AI_ACTIVITY_ENABLED','true');storage=memoryDraftStorage();vi.mocked(teamSetupApi.read).mockRejectedValue(new WorkspaceApiError(404));vi.spyOn(workspaceApi,'team').mockResolvedValue(structuredClone(team));vi.spyOn(workspaceApi,'saveTeam');vi.spyOn(accountIdentityApi,'read').mockImplementationOnce(()=>new Promise((yes,no)=>{resolve=yes;reject=no;})).mockResolvedValue(activityIdentity);vi.spyOn(modelActivityApi,'read');const fixture=await setupFixture();vi.spyOn(vendorSetupApi,'catalog').mockResolvedValue(fixture.emptyCatalog);vi.spyOn(vendorSetupApi,'detail').mockResolvedValue(fixture.accountPending);vi.spyOn(vendorSetupApi,'command');vi.spyOn(vendorSetupApi,'resolve');host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
it('keeps unrelated connection configuration usable while optional activity context is deferred and after 503',async()=>{await mount();expect(host.querySelector('main')?.getAttribute('data-settings-navigation-locked')).toBe('false');await click('Connections');await click('Messaging & fax');await click('New account configuration');await wait(()=>expect(configName()?.matches(':disabled')).toBe(false));const field=configName();await input(field,'Retain unrelated connector draft');const address=accountEditorAddress('vendor-setup');await wait(async()=>expect(await saved(address)).toMatchObject({data:{draft:{label:'Retain unrelated connector draft'}}}));const before=await saved(address);await act(async()=>reject(new WorkspaceApiError(503)));await wait(()=>expect(button('Recheck AI activity access')).toBeTruthy());expect(configName()).toBe(field);expect(field.value).toBe('Retain unrelated connector draft');expect(await saved(address)).toEqual(before);expect(button('Done')?.matches(':disabled')).toBe(false);expect(vendorSetupApi.command).not.toHaveBeenCalled();expect(vendorSetupApi.resolve).not.toHaveBeenCalled();expect(modelActivityApi.read).not.toHaveBeenCalled();});
it('retains team edits through an optional context failure, close-settings and a fresh retry',async()=>{await mount();await click('Your team');await click('Team preferences');await click('Practice profile');const field=host.querySelector<HTMLTextAreaElement>('.team-practice-editor textarea')!;await input(field,'Keep current team instructions');await wait(async()=>expect(await saved('team')).toMatchObject({configuration:{practice_context:'Keep current team instructions'}}));await act(async()=>reject(new WorkspaceApiError(503)));await wait(()=>expect(button('Recheck AI activity access')).toBeTruthy());expect(field.value).toBe('Keep current team instructions');await click('Done');await click('Team settings');await click('Your team');await click('Team preferences');await click('Practice profile');expect(host.querySelector<HTMLTextAreaElement>('.team-practice-editor textarea')!.value).toBe(field.value);expect(field.value).toBe('Keep current team instructions');expect(workspaceApi.saveTeam).not.toHaveBeenCalled();expect(modelActivityApi.read).not.toHaveBeenCalled();});
it.each([401,403])('still clears private views on optional context denial %i while retaining saved team input',async status=>{await mount();await click('Your team');await click('Team preferences');await click('Practice profile');await input(host.querySelector<HTMLTextAreaElement>('.team-practice-editor textarea')!,'Retained before authority denial');await wait(async()=>expect(await saved('team')).toMatchObject({configuration:{practice_context:'Retained before authority denial'}}));const before=await saved('team');await act(async()=>reject(new WorkspaceApiError(status)));await wait(()=>expect(host.querySelector('.team-configuration-flow')).toBeNull());expect(host.textContent).toContain('Private content has been cleared');expect(await saved('team')).toEqual(before);expect(workspaceApi.saveTeam).not.toHaveBeenCalled();});
it('can close the notebook during an empty optional context read and ignores its late answer',async()=>{await mount();const signal=vi.mocked(accountIdentityApi.read).mock.calls[0][1]!;await click('Close notebook');expect(signal.aborted).toBe(true);expect(host.querySelector('.settings-hub')).not.toBeNull();expect(host.querySelector('.settings-hub')?.hasAttribute('hidden')).toBe(true);await act(async()=>resolve(activityIdentity));expect(host.querySelector('.ai-activity')).toBeNull();expect(modelActivityApi.read).not.toHaveBeenCalled();expect(host.querySelector('main')?.getAttribute('data-settings-navigation-locked')).toBe('false');});

it('keeps team text focused and exact while slow local storage saves the working copy',async()=>{
  const original=storage;let slow=false;const releases:Array<()=>void>=[];
  storage=async options=>{const store=await original(options);return {...store,write:async(...args)=>{
    if(slow&&args[0]==='team')await new Promise<void>(done=>releases.push(done));
    return store.write(...args);
  }};};
  try{
    await mount();await act(async()=>resolve(activityIdentity));
    await settingsNavigation(host).editSelected('Scribe');
    const field=[...host.querySelectorAll('label')].find(label=>visible(label)&&label.textContent?.startsWith('Working preferences'))!.querySelector('textarea')!;
    field.focus();slow=true;await input(field,'U');
    await act(async()=>{await new Promise(done=>setTimeout(done,250));});
    expect(field.matches(':disabled')).toBe(false);expect(document.activeElement).toBe(field);
    const text='Use SOAP format. Preserve the patient’s words and flag follow-ups I promised.';
    for(const char of text.slice(1)){await input(field,field.value+char);expect(field.matches(':disabled')).toBe(false);}
    expect(field.value).toBe(text);expect(document.activeElement).toBe(field);
    slow=false;await act(async()=>releases.splice(0).forEach(done=>done()));
    await wait(async()=>expect(await saved('team')).toMatchObject({configuration:{bots:expect.arrayContaining([expect.objectContaining({role:'scribe',working_preferences:text})])}}));
  }finally{slow=false;await act(async()=>releases.splice(0).forEach(done=>done()));}
});
