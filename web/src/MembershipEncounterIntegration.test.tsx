import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {membershipApi} from './membership-api';
import {workspaceApi,type Workspace} from './workspace-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {teamFixture} from './team-setup-test-fixture';
import {membershipFixture,membershipFixtureOptions} from './membership-test-fixture';
import type {MembershipReviewBundle} from './membership-operation';
vi.mock('./MembershipWorkMount',async original=>{const actual=await original<typeof import('./MembershipWorkMount')>();return {...actual,MEMBERSHIP_WORK_BUILD:true,MembershipWorkspaceMount:(props:Parameters<typeof actual.MembershipWorkspaceMount>[0])=><actual.MembershipWorkspaceMount {...props} enabled/>};});
vi.mock('./VendorWorkMount',()=>({VendorWorkspaceMount:()=>null,VendorPracticeMount:()=>null}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
describe('membership in the signed encounter Work surface',()=>{
 let root:Root,container:HTMLDivElement,bundle:MembershipReviewBundle,workspace:Workspace;
 const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-membership-owner'};
 let storage:ReturnType<typeof memoryDraftStorage>;
 beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);bundle=await membershipFixture(3);storage=memoryDraftStorage();const wid=bundle.detail.scope.workspace_id;
  workspace={id:wid,appointment_id:wid,label:'Invented membership encounter',revision:1,entries:[],work_candidates:[]};const team=teamFixture();team.llm.enabled=false;team.capture=undefined;team.scheduling=undefined;
  vi.spyOn(workspaceApi,'catalog').mockResolvedValue([{appointment_id:wid,workspace_id:wid,label:workspace.label}]);vi.spyOn(workspaceApi,'open').mockResolvedValue({identity,workspace,team});vi.spyOn(workspaceApi,'team').mockResolvedValue(team);vi.spyOn(workspaceApi,'read').mockResolvedValue(workspace);vi.spyOn(workspaceApi,'append');
  vi.spyOn(membershipApi,'bootstrap').mockResolvedValue(membershipFixtureOptions(bundle.detail));vi.spyOn(membershipApi,'options').mockResolvedValue(membershipFixtureOptions(bundle.detail));vi.spyOn(membershipApi,'catalog').mockResolvedValue({contract_version:1,scope:bundle.detail.scope,items:[bundle.detail.summary]});vi.spyOn(membershipApi,'detail').mockResolvedValue(bundle);vi.spyOn(membershipApi,'execute');vi.spyOn(membershipApi,'recover');
  container=document.createElement('div');document.body.append(container);root=createRoot(container);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));
 });
 afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
 const until=async(check:()=>void)=>{for(let i=0;i<150;i++){let done=false;await act(async()=>{await new Promise(r=>setTimeout(r,5));try{check();done=true;}catch{}});if(done)return;}check();};
 const openWork=async()=>{
  const choose=Array.from(container.querySelectorAll('button')).find(b=>b.textContent?.startsWith('Choose an encounter'))!;await act(async()=>choose.click());await until(()=>expect(container.querySelector('.team-encounter-option')).not.toBeNull());await act(async()=>(container.querySelector('.team-encounter-option') as HTMLButtonElement).click());await until(()=>expect(container.querySelector('.team-encounter-heading')).not.toBeNull());
  const work=container.querySelector<HTMLButtonElement>('nav[aria-label="Mobile encounter view"] button:last-child')!;expect(work.textContent).toBe('Work');await act(async()=>work.click());await until(()=>expect(container.querySelector('[aria-label="Private membership review"] textarea')).not.toBeNull());
 };
 it('mounts owner review through real encounter recovery after explicit Work navigation',async()=>{expect(membershipApi.bootstrap).not.toHaveBeenCalled();await openWork();expect(membershipApi.bootstrap).toHaveBeenCalledWith(identity,workspace.id,expect.any(AbortSignal));expect(container.querySelector('.team-content')?.getAttribute('data-mobile-panel')).toBe('Work');expect(container.textContent).toContain('No membership service is selected');expect(membershipApi.execute).not.toHaveBeenCalled();expect(membershipApi.recover).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();});
 it('removes private membership content when the signed account changes',async()=>{await openWork();await act(async()=>(container.querySelector('.membership-list button') as HTMLButtonElement).click());await until(()=>expect(container.textContent).toContain(bundle.detail.latest_result!.request.evidence));await act(async()=>root.render(<EncounterWorkspace authenticated={{mode:'clerk_jwt',getToken:async()=> 'different-account'}} draftStorage={storage}/>));expect(container.textContent).not.toContain(bundle.detail.latest_result!.request.evidence);expect(container.querySelector('[aria-label="Private membership review"]')).toBeNull();expect(membershipApi.execute).not.toHaveBeenCalled();});
});
