import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import wire from './__fixtures__/scheduling-enrollment-wire.json';
import {SchedulingEnrollmentPanel} from './SchedulingEnrollmentPanel';
import {SchedulingGoogleHandoff} from './SchedulingGoogleHandoff';
import {SchedulingConnectionPanel} from './SchedulingConnectionPanel';
import {schedulingLoginRequest} from './scheduling-login-api';
import {schedulingEnrollmentRequest,validateEnrollmentResponse,type EnrollmentCommand,type EnrollmentResponse,type EnrollmentReview} from './scheduling-enrollment-api';
import {coreDigest} from './core-connection-contract';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

vi.hoisted(()=>vi.stubEnv('VITE_WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED','true'));
vi.mock('./scheduling-login-api',async original=>({...await original<typeof import('./scheduling-login-api')>(),SCHEDULING_LOGIN_BUILD:true,schedulingLoginRequest:vi.fn()}));
vi.mock('./scheduling-enrollment-api',async original=>({...await original<typeof import('./scheduling-enrollment-api')>(),schedulingEnrollmentRequest:vi.fn()}));
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
let host:HTMLDivElement,root:Root;
const connected=vi.fn();
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();delete window.cosmasSchedulingNavigation;vi.restoreAllMocks();});
function fresh(value:unknown):unknown {
 if(Array.isArray(value))return value.map(fresh);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,key==='observed_at'?new Date().toISOString():key==='expires_at'&&item!==null?new Date(Date.now()+600000).toISOString():fresh(item)]));
 return value;
}
async function settle(){for(let i=0;i<12;i++)await act(async()=>{await new Promise(resolve=>setTimeout(resolve,1));});}
const mount=async(who=identity)=>{await act(async()=>root.render(<SchedulingEnrollmentPanel identity={who} onAuthenticationLost={()=>{}} onConnected={connected}/>));await settle();};
const button=(label:string)=>{const found=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(found).toBeDefined();return found!;};
const click=async(label:string)=>{await act(async()=>button(label).click());await settle();};
let lastReview:EnrollmentReview;
async function answer(_who:AuthenticatedWorkspaceIdentity,command:EnrollmentCommand):Promise<EnrollmentResponse>{
 let value:unknown;
 if(command.action==='enrollment_status')value=fresh(wire.choose.response);
 else if(command.action==='enrollment_review'){
  const candidate={...fresh(wire.review.response) as EnrollmentReview,command_key:command.command_key!};
  candidate.command_sha256=await coreDigest({...command,action:'enrollment_confirm',plan_sha256:candidate.plan_sha256,confirmed:true});
  lastReview=candidate;value=candidate;
 }else if(command.action==='enrollment_confirm'||command.action==='enrollment_result')value={...wire.confirm.response,command_key:command.command_key,command_sha256:lastReview.command_sha256};
 else throw new Error('Unexpected command');
 return validateEnrollmentResponse(value,command);
}
async function reviewAndAccept(){await mount();expect(host.textContent).toContain('Invited clinician');await click('Review practice connection');expect(button('Confirm practice connection').disabled).toBe(true);await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());}
it('accepts actual Python wire digests and rejects changed catalogs and mismatched receipts',async()=>{
 for(const name of ['not_connected','choose','review','confirm','receipt','cancel'] as const){const value=wire[name];await expect(validateEnrollmentResponse(fresh(value.response),value.command as EnrollmentCommand)).resolves.toBeDefined();}
 const changed=fresh(wire.choose.response) as typeof wire.choose.response;changed.catalog.practice.label='Another practice';await expect(validateEnrollmentResponse(changed,{action:'enrollment_status'})).rejects.toThrow();
 await expect(validateEnrollmentResponse({...wire.receipt.response,command_key:crypto.randomUUID()},wire.receipt.command as EnrollmentCommand)).rejects.toThrow();
});
it('requires review and consent before making exactly one account connection',async()=>{
 vi.mocked(schedulingEnrollmentRequest).mockImplementation(answer);const storage=vi.spyOn(Storage.prototype,'setItem');
 await reviewAndAccept();expect(vi.mocked(schedulingEnrollmentRequest).mock.calls.map(c=>c[1].action)).toEqual(['enrollment_status','enrollment_review']);
 await click('Confirm practice connection');expect(connected).toHaveBeenCalledOnce();expect(storage).not.toHaveBeenCalled();
 expect(vi.mocked(schedulingEnrollmentRequest).mock.calls.filter(c=>c[1].action==='enrollment_confirm')).toHaveLength(1);
});
it('recovers an uncertain confirmation with its exact saved receipt and no second write',async()=>{
 vi.mocked(schedulingEnrollmentRequest).mockImplementation(async(who,command)=>{if(command.action==='enrollment_confirm')throw new Error('lost reply');return answer(who,command);});
 await reviewAndAccept();await click('Confirm practice connection');expect(host.textContent).toContain('Your last confirmation needs to be checked.');expect(host.textContent).not.toContain('Confirm your Scheduling account');
 await click('Check saved connection result');expect(connected).toHaveBeenCalledOnce();
 const calls=vi.mocked(schedulingEnrollmentRequest).mock.calls.map(c=>c[1]);expect(calls.map(c=>c.action)).toEqual(['enrollment_status','enrollment_review','enrollment_confirm','enrollment_result']);expect(calls[3]).toEqual({action:'enrollment_result',attempt_ref:calls[2].attempt_ref,command_key:calls[2].command_key,command_sha256:lastReview.command_sha256});
});
it('hides an old account response after the current account changes',async()=>{
 let finish!:(v:EnrollmentResponse)=>void;
 vi.mocked(schedulingEnrollmentRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce(wire.not_connected.response as EnrollmentResponse);
 await mount();await mount({...identity});await act(async()=>finish(await validateEnrollmentResponse(fresh(wire.choose.response),{action:'enrollment_status'})));await settle();
 expect(host.textContent).not.toContain('Invited clinician');expect(button('Connect my Scheduling account')).toBeDefined();
});
it('uses the existing native Google handoff and refuses a replaced native session',async()=>{
 let current=true;const who:AuthenticatedWorkspaceIdentity={mode:'desktop_native',revision:crypto.randomUUID(),isCurrent:()=>current};window.cosmasSchedulingNavigation={version:1,available:true,mode:'trusted-click'};
 await act(async()=>root.render(<SchedulingGoogleHandoff identity={who} start={{authorization_url:'https://accounts.google.com/o/oauth2/v2/auth?invented',expires_at:new Date(Date.now()+600000).toISOString()}} onReturn={()=>{}} onMessage={()=>{}}/>));
 const link=host.querySelector<HTMLButtonElement>('[data-scheduling-sign-in]')!;expect(JSON.parse(link.dataset.schedulingSignIn!).expectedRevision).toBe(who.revision);current=false;const event=new MouseEvent('click',{bubbles:true,cancelable:true});await act(async()=>link.dispatchEvent(event));expect(event.defaultPrevented).toBe(true);
});
it('offers initial enrollment from Connections and returns to the established account view',async()=>{
 vi.mocked(schedulingLoginRequest).mockRejectedValueOnce(new WorkspaceApiError(409)).mockResolvedValueOnce({state:'connected',label:'My practice',connected_at:new Date().toISOString()});
 vi.mocked(schedulingEnrollmentRequest).mockImplementation(answer);
 await act(async()=>root.render(<SchedulingConnectionPanel identity={identity} onAuthenticationLost={()=>{}}/>));await settle();
 expect(host.textContent).toContain('Connect your practice account');await click('Review practice connection');await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());await click('Confirm practice connection');
 expect(host.textContent).toContain('Connected to Scheduling.');expect(host.textContent).not.toContain('Connect your practice account');
});
