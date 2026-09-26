import { settingsNavigation } from "./settings-test-navigation";
import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_VENDOR_SETUP_ENABLED','true');vi.stubEnv('VITE_FINANCE_SETUP_ENABLED','false');vi.stubEnv('VITE_PORTAL_SETUP_ENABLED','false');});
import {EncounterWorkspace} from './EncounterWorkspace';
import {workspaceApi,WorkspaceApiError} from './workspace-api';
import {teamFixture} from './team-setup-test-fixture';
import {teamSetupApi} from './team-setup-api';
import {vendorSetupApi} from './vendor-setup-api';
import {setupFixture} from './vendor-setup-test-fixture';
import {memoryDraftStorage} from './draft-test-fixture';
import {DraftJournal,accountEditorAddress} from './draft-journal';
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};});
// Renderer wiring only; real encryption and namespace bounds are tested separately.
vi.mock('./draft-store',async original=>({...await original<typeof import('./draft-store')>(),privateDraftScope:async(scope:string)=>scope}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-team-owner-token'};
let root:Root,container:HTMLDivElement,f:Awaited<ReturnType<typeof setupFixture>>,factory:ReturnType<typeof memoryDraftStorage>;
const team=teamFixture();
const button=(text:string)=>Array.from(container.querySelectorAll('button')).find(b=>b.textContent===text);
const until=async(check:()=>void|Promise<void>)=>{for(let i=0;i<150;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{await check();done=true;}catch{}});if(done)return;}await check();};
beforeEach(async()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);f=await setupFixture();factory=memoryDraftStorage();vi.mocked(teamSetupApi.read).mockRejectedValue(new WorkspaceApiError(404));vi.spyOn(workspaceApi,'team').mockResolvedValue(team);vi.spyOn(workspaceApi,'saveTeam');vi.spyOn(vendorSetupApi,'catalog').mockResolvedValue(f.catalogPending);vi.spyOn(vendorSetupApi,'command');vi.spyOn(vendorSetupApi,'resolve');container=document.createElement('div');document.body.append(container);root=createRoot(container);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={factory}/>));});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
async function open(){const navigation=settingsNavigation(container);await navigation.click('Team settings');expect(vendorSetupApi.catalog).not.toHaveBeenCalled();await navigation.click('Connections');expect(vendorSetupApi.catalog).not.toHaveBeenCalled();await navigation.click('Messaging & fax');await until(()=>expect(button('Refresh connector settings')?.matches(':disabled')).toBe(false));}
it('mounts messaging and fax settings within Team settings using the existing private account journal',async()=>{expect(vendorSetupApi.catalog).not.toHaveBeenCalled();await open();expect(container.textContent).toContain('Messaging and fax connections');expect(container.querySelector('.team-configuration-flow')).toBeNull();expect(vendorSetupApi.catalog).toHaveBeenCalledWith(identity,expect.any(AbortSignal));expect(Array.from(container.querySelectorAll('input,select,textarea')).filter(e=>!e.closest('[hidden]'))).toHaveLength(0);await settingsNavigation(container).click('New account configuration');await until(()=>expect(container.querySelector('.vendor-setup input')?.matches(':disabled')).toBe(false));const label=Array.from(container.querySelectorAll('label')).find(n=>n.firstChild?.textContent==='Configuration name')!.querySelector('input')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(label,'Invented saved connector choice');label.dispatchEvent(new Event('input',{bubbles:true}));});const reader=new DraftJournal(await factory({scope:team.recovery_scope!}));await until(async()=>{const d=await reader.load(accountEditorAddress('vendor-setup'));expect(d?.kind==='account-editor'&&(d.data as {draft:{label:string}}).draft.label).toBe('Invented saved connector choice');});reader.close();expect(vendorSetupApi.command).not.toHaveBeenCalled();expect(vendorSetupApi.resolve).not.toHaveBeenCalled();expect(workspaceApi.saveTeam).not.toHaveBeenCalled();});
it('hides the mounted connector controls when the account recovery authority is revoked',async()=>{await open();vi.mocked(workspaceApi.team).mockRejectedValueOnce(new WorkspaceApiError(403));await act(async()=>button('Refresh connector settings')!.click());await until(()=>expect(container.querySelector('.vendor-setup input')).toBeNull());expect(vendorSetupApi.command).not.toHaveBeenCalled();expect(vendorSetupApi.resolve).not.toHaveBeenCalled();});
