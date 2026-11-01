import {afterEach,expect,it,vi} from 'vitest';
import {observeWorkspaceEnrollment,workspaceEnrollmentHold,workspaceEnrollmentRevision,WORKSPACE_ENROLLMENT_HEADER,WORKSPACE_ENROLLMENT_USER_HEADER} from './workspace-enrollment-state';
import {workspaceFetch} from './workspace-protocol';

const identity=()=>({mode:'clerk_jwt' as const,getToken:async()=> 'invented.token'});
const denial=(status=403,user:string|null='new')=>new Response('opaque error body',{status,headers:{
  [WORKSPACE_ENROLLMENT_HEADER]:status===403?'workspace_enrollment_access_required':'workspace_enrollment_admission_unavailable',
  ...(user===null?{}:{[WORKSPACE_ENROLLMENT_USER_HEADER]:user}),
}});
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();});
it.each([403,503])('observes only a server-classified New denial with matching status %s',status=>{
  const id=identity();expect(observeWorkspaceEnrollment(id,denial(status))).toMatchObject({status});
  expect(workspaceEnrollmentHold(id)).toBe(status===403?'workspace_enrollment_access_required':'workspace_enrollment_admission_unavailable');expect(workspaceEnrollmentRevision(id)).toBe(1);
});
it.each([null,'existing','new_enrolled','unmanaged','NEW','new, existing'])('never creates a hold from generic errors or user marker %s',marker=>{
  const id=identity();for(const status of [403,503])expect(observeWorkspaceEnrollment(id,denial(status,marker))).toBeNull();
  expect(workspaceEnrollmentHold(id)).toBeNull();expect(workspaceEnrollmentRevision(id)).toBe(0);
});
it('keeps obsolete New-denial sessions from mutating the current hold',()=>{
  const id={...identity(),nativeSession:{revision:'invented-old-session',isCurrent:()=>false}};
  expect(observeWorkspaceEnrollment(id,denial())).toMatchObject({status:401});expect(workspaceEnrollmentHold(id)).toBeNull();expect(workspaceEnrollmentRevision(id)).toBe(0);
});
it('preserves the caller-owned unmanaged generic response and its unread body',async()=>{
  vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','false');const id=identity(),reply=denial(403,null);
  vi.stubGlobal('fetch',vi.fn(async()=>reply));
  const received=await workspaceFetch(id,'http://127.0.0.1:8000/workspaces',{method:'GET'});
  expect(received).toBe(reply);expect(reply.bodyUsed).toBe(false);expect(await received.text()).toBe('opaque error body');expect(workspaceEnrollmentHold(id)).toBeNull();
});
