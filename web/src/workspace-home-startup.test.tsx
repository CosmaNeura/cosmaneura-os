import {act,useEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {DraftJournal} from './draft-journal';
import {openDraftStore} from './draft-store';
import {PracticeAccessGate} from './PracticeAccessGate';
import {PracticeHome} from './PracticeHome';
import {practiceAccessApi} from './practice-access-api';
import {accessConnected} from './practice-access-test-fixture';
import {REQUIRED_WORKSPACE_CONTRACTS} from './workspace-protocol';
import {WorkspaceCompatibilityGate} from './WorkspaceCompatibilityGate';
import {WorkspaceHomeStartup} from './workspace-home-startup';
import {workspaceApi,type ProviderTeam} from './workspace-api';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const descriptor=()=>({contract_version:1 as const,workspace_protocol:1 as const,requests_require_protocol:true as const,contracts:{...REQUIRED_WORKSPACE_CONTRACTS}});
const identity={mode:'clerk_jwt' as const,getToken:async()=>'invented.token'};
const team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},configuration:{practice_context:'',bots:[{role:'chief',name:'Chief',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[]};
let root:Root,container:HTMLDivElement;

beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});
  vi.stubGlobal('crypto',webcrypto);
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);
  vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  container=document.createElement('div');document.body.append(container);root=createRoot(container);
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});

it('keeps Start waiting on recovery only',()=>{
  const base={recoveryReady:false,teamListed:false,visitsLoaded:false,notesLoaded:false,teamError:''};
  expect(WorkspaceHomeStartup.startEnabled({recoveryReady:false,busy:false,locked:false,pending:false,title:'Private note'})).toBe(false);
  expect(WorkspaceHomeStartup.startEnabled({recoveryReady:true,busy:false,locked:false,pending:false,title:'Private note'})).toBe(true);
  expect(WorkspaceHomeStartup.startEnabled({recoveryReady:true,busy:false,locked:true,pending:false,title:'Private note'})).toBe(false);
  expect(WorkspaceHomeStartup.status(base)).toBe('Checking your team… Visits and notes are loading in the background.');
  expect(WorkspaceHomeStartup.status({...base,recoveryReady:true,teamListed:true})).toBe('Loading visits and notes…');
  expect(WorkspaceHomeStartup.status({...base,recoveryReady:true,teamListed:true,visitsLoaded:true,notesLoaded:true})).toBe('');
  expect(WorkspaceHomeStartup.status({...base,teamError:'Your team list could not be loaded.'})).toBe('Your team list could not be loaded.');
});

it('shows the workspace shell before compatibility admission and still withholds Start',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','true');
  vi.stubEnv('VITE_API_BASE','https://api.example.invalid');
  vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN','https://api.example.invalid');
  vi.stubEnv('VITE_WORKSPACE_WEB_ORIGIN','https://workspace.example.invalid');
  vi.stubEnv('VITE_WORKSPACE_HOSTED_CLIENT','web');
  vi.stubEnv('VITE_WORKSPACE_DATA_MODE','synthetic');
  vi.stubEnv('VITE_COSMAS_ENV','early_adopter_beta');
  vi.stubEnv('VITE_WORKSPACE_ENABLED','true');
  vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');
  vi.stubGlobal('window',{location:{href:'https://workspace.example.invalid/'},setInterval:window.setInterval.bind(window),clearInterval:window.clearInterval.bind(window),setTimeout:window.setTimeout.bind(window),clearTimeout:window.clearTimeout.bind(window)});
  const started=performance.now();
  vi.spyOn(practiceAccessApi,'compatibility').mockImplementation(()=>new Promise(resolve=>{setTimeout(()=>resolve(descriptor()),300);}));
  const mounted=vi.fn();
  function Child(){useEffect(()=>{mounted();},[]);return <p>Private workspace</p>;}
  await act(async()=>root.render(<WorkspaceCompatibilityGate identity={identity} accountControls={<button>Account</button>}><Child/></WorkspaceCompatibilityGate>));
  const shellAt=performance.now()-started;
  expect(container.querySelector('[data-startup-shell="true"]')).not.toBeNull();
  expect(container.querySelector<HTMLButtonElement>('[data-startup-shell] .team-primary')?.disabled).toBe(true);
  expect(container.textContent).toContain('Checking workspace connection');
  expect(mounted).not.toHaveBeenCalled();
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,360));});
  const admittedAt=performance.now()-started;
  expect(mounted).toHaveBeenCalledOnce();
  expect(container.textContent).toContain('Private workspace');
  expect(shellAt).toBeLessThan(80);
  expect(admittedAt).toBeGreaterThan(280);
  console.info(`after-shell ms=${shellAt.toFixed(1)} after-admitted ms=${admittedAt.toFixed(1)}`);
});

it('replays the startup order on current main with the same 300ms check',async()=>{
  // b1a76cc order: compatibility, then access+setup, then team, then a second team read inside private-draft recovery, then visit and note lists.
  const step=300,t0=performance.now(),wait=()=>new Promise(resolve=>setTimeout(resolve,step));
  await wait();
  const compat=performance.now()-t0;
  await Promise.all([wait(),wait()]);
  const workspace=performance.now()-t0;
  await wait();
  await wait();
  const start=performance.now()-t0;
  await Promise.all([wait(),wait()]);
  const lists=performance.now()-t0;
  console.info(`main-replay compat=${compat.toFixed(0)} workspace=${workspace.toFixed(0)} start=${start.toFixed(0)} lists=${lists.toFixed(0)}`);
  expect(compat).toBeGreaterThan(280);
  expect(workspace).toBeGreaterThan(compat+250);
  expect(start).toBeGreaterThan(workspace+550);
  expect(lists).toBeGreaterThan(start+250);
});

it('keeps the practice shell up while access is still being checked',async()=>{
  let release!:(value:typeof accessConnected)=>void;
  vi.spyOn(practiceAccessApi,'read').mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  vi.spyOn(practiceAccessApi,'setup').mockResolvedValue({contract_version:1,state:'member_ready',practice:{display_name:'Invented practice',specialty:null},display_name:'Ada Beta',can_start_practice:false});
  const mounted=vi.fn();
  await act(async()=>root.render(<PracticeAccessGate identity={identity} accountControls={<button>Account</button>}>{()=>{mounted();return <p>Private workspace</p>;}}</PracticeAccessGate>));
  expect(container.querySelector('[data-startup-shell="true"]')).not.toBeNull();
  expect(container.textContent).toContain('Checking practice access');
  expect(mounted).not.toHaveBeenCalled();
  expect(container.querySelector<HTMLButtonElement>('[data-startup-shell] .team-primary')?.disabled).toBe(true);
  await act(async()=>release(accessConnected));
  expect(mounted).toHaveBeenCalledOnce();
  expect(container.querySelector('[data-startup-shell="true"]')).toBeNull();
});

it('enables Start when recovery is ready and does not wait for a slow visit list',async()=>{
  const recovery={journal:new DraftJournal(await openDraftStore({scope:'a'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto:webcrypto})),authorize:vi.fn().mockResolvedValue(undefined)};
  let releaseVisits!:(value:never[])=>void;
  vi.spyOn(workspaceApi,'catalog').mockImplementation(()=>new Promise(resolve=>{releaseVisits=resolve;}));
  vi.spyOn(workspaceApi,'privateDraftSummaries').mockResolvedValue({contract_version:2,drafts:[],has_more:false});
  const props={identity,team,locked:false,onUseTeam:vi.fn(),onSettings:vi.fn(),onVisits:vi.fn(),onConnections:vi.fn(),onPracticeWork:vi.fn(),onOpened:vi.fn(),onAccessLost:vi.fn(),onBusyChange:vi.fn()};
  const started=performance.now();
  await act(async()=>root.render(<PracticeHome {...props} recovery={null}/>));
  expect(workspaceApi.catalog).toHaveBeenCalledOnce();
  expect(workspaceApi.privateDraftSummaries).toHaveBeenCalledOnce();
  const start=()=>[...container.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='Start a private note')!;
  const title=container.querySelector<HTMLInputElement>('.practice-quick-start input')!;
  expect(start().disabled).toBe(true);
  expect(title.disabled).toBe(false);
  expect(container.textContent).toContain('Checking your team');
  expect(container.textContent).not.toContain('Checking available visits');
  await act(async()=>root.render(<PracticeHome {...props} recovery={recovery}/>));
  await vi.waitFor(()=>expect(start().disabled).toBe(false));
  const enabledAt=performance.now()-started;
  expect(container.textContent).toContain('Loading visits');
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,30));});
  expect(start().disabled).toBe(false);
  await act(async()=>releaseVisits([]));
  await vi.waitFor(()=>expect(container.textContent).toContain('No supported visits'));
  expect(enabledAt).toBeLessThan(1000);
  console.info(`start-enabled ms=${enabledAt.toFixed(1)} while visits were still pending`);
  recovery.journal.close();
});
