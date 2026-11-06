import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_MESSAGES_ENABLED','true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');});
const observed=vi.hoisted(()=>({session:null as import('./session/workspace-session').WorkspaceSession|null}));
vi.mock('./session/use-workspace-session',async importOriginal=>{
  const original=await importOriginal<typeof import('./session/use-workspace-session')>();
  return {...original,useWorkspaceSession:(...args:Parameters<typeof original.useWorkspaceSession>)=>{observed.session=args[0];return original.useWorkspaceSession(...args);}};
});
import {EncounterWorkspace} from './EncounterWorkspace';
import {identity,installFixtures} from '../ux-acceptance/fixtures';
import {memoryDraftStorage} from './draft-test-fixture';
import {practicePageFromRoute,readWorkspaceRoute,workspaceRouteHash} from './workspace-route';
import {WorkspaceSession} from './session/workspace-session';
import {workspaceApi} from './workspace-api';
import {teamFixture} from './team-setup-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const notebookId='00000000-0000-4000-8000-000000000071';
const notebookHash=workspaceRouteHash({page:'notebook',workspaceId:notebookId,helper:'chief',material:'Conversation'});

let root:Root,host:HTMLDivElement;

beforeEach(async()=>{
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  localStorage.clear();sessionStorage.clear();observed.session=null;
  window.matchMedia=vi.fn().mockReturnValue({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()});
  window.scrollTo=vi.fn();HTMLElement.prototype.scrollIntoView=vi.fn();
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();history.replaceState(null,'','/');});

it('seeds the notebook practice page from the hash before Home can paint',()=>{
  const route=readWorkspaceRoute(notebookHash);
  expect(route).toEqual({page:'notebook',workspaceId:notebookId,helper:'chief',material:'Conversation'});
  expect(practicePageFromRoute(route,'home')).toBe('notebook');
  expect(practicePageFromRoute(readWorkspaceRoute('#cosmas/home'),'visits')).toBe('home');
  expect(practicePageFromRoute(readWorkspaceRoute('#cosmas/settings'),'home')).toBe('home');
  const session=new WorkspaceSession({initialPage:practicePageFromRoute(route,'home'),navigation:{initialRoute:route}});
  expect(session.getSnapshot().practicePage).toBe('notebook');
  expect(session.navigation.ready.current).toBe(false);
});

it('renders the notebook route from a hash without painting Home first',async()=>{
  history.replaceState(null,'',notebookHash);
  await installFixtures(true);
  let releaseTeam!:(value:ReturnType<typeof teamFixture>)=>void;
  const team=teamFixture();
  vi.spyOn(workspaceApi,'team').mockImplementation(()=>new Promise(resolve=>{releaseTeam=resolve;}));
  await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
  expect(observed.session).not.toBeNull();
  expect(observed.session!.getSnapshot().practicePage).toBe('notebook');
  expect(observed.session!.getSnapshot().team).toBeNull();
  const shell=host.querySelector('.team-workspace');
  expect(shell?.getAttribute('data-page')).toBe('notebook');
  const homes=[...host.querySelectorAll('[aria-label="Practice Home"]')];
  expect(homes.length).toBeGreaterThan(0);
  expect(homes.every(home=>home.closest('[hidden]'))).toBe(true);
  expect([...host.querySelectorAll('.practice-home-status')].every(status=>status.closest('[hidden]'))).toBe(true);
  await act(async()=>releaseTeam(team));
  expect(observed.session!.getSnapshot().practicePage).not.toBe('visits');
});
