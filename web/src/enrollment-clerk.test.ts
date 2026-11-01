import {afterEach,expect,it,vi} from 'vitest';
import {prepareEnrollmentWorkspaceToken,type EnrollmentWorkspaceAccount} from './enrollment-clerk';
import {enrollmentStatus} from './enrollment-test-fixture';
afterEach(()=>vi.useRealTimers());
function account(){const status=enrollmentStatus('ready',6);let active:string|null=null;const events:string[]=[];
  const value:EnrollmentWorkspaceAccount={identity:{isCurrent:()=>true,getToken:async options=>{expect(options).toEqual({skipCache:true});events.push('token');return 'fresh.fixture';}},
    reload:async()=>{events.push('reload');},memberships:async()=>{events.push('membership');return {data:[{organization:{id:status.workspace.organization_id!}}],total_count:1};},
    activate:async target=>{events.push('activate');active=target;},activeOrganization:()=>active};return {value,status,events};}
it('reloads membership, activates the saved organization and observes it before requesting fresh proof',async()=>{
  const {value,status,events}=account();expect(await prepareEnrollmentWorkspaceToken(value,status)).toBe('fresh.fixture');expect(events).toEqual(['reload','membership','activate','token']);
});
it('uses account-only proof for membership preparation and cannot use that proof to open Chief',async()=>{
  const {value,status,events}=account();value.memberships=async()=>({data:[],total_count:0});
  expect(await prepareEnrollmentWorkspaceToken(value,status,undefined,true)).toBe('fresh.fixture');expect(events).toEqual(['reload','token']);
  await expect(prepareEnrollmentWorkspaceToken(value,status)).rejects.toMatchObject({status:403,code:'enrollment_membership_preparation_required'});
});
it('clears a different selected organization before obtaining account-only preparation proof',async()=>{
  const {value,status,events}=account();let active:string|null='org_other';value.activeOrganization=()=>active;value.activate=async target=>{active=target;events.push('clear');};value.memberships=async()=>({data:[],total_count:0});
  expect(await prepareEnrollmentWorkspaceToken(value,status,undefined,true)).toBe('fresh.fixture');expect(active).toBeNull();expect(events).toEqual(['reload','clear','token']);
});
it('does not obtain scoped proof when organization activation is not observed',async()=>{
  vi.useFakeTimers();const {value,status,events}=account();value.activate=async()=>{events.push('activate');};
  const result=prepareEnrollmentWorkspaceToken(value,status).catch(error=>error);await vi.advanceTimersByTimeAsync(10050);
  expect(await result).toMatchObject({status:403});expect(events).not.toContain('token');
});
it('fences an account change before activating or obtaining workspace proof',async()=>{
  const {value,status,events}=account();let live=true;value.identity.isCurrent=()=>live;value.reload=async()=>{live=false;};
  await expect(prepareEnrollmentWorkspaceToken(value,status)).rejects.toMatchObject({status:401});expect(events).toEqual([]);
});
