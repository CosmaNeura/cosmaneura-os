import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {connectionHealth,connectionReadScope,connectionReadFailed,connectionServices,observeConnectionStatus,observeConnectionRead,invalidateConnectionHealth,connectionCheckFailed} from './connection-operation-health';
const owner=()=>({mode:'clerk_jwt' as const,getToken:async()=>null});
const status={state:'connected',account:{email:'invented@example.invalid'},connected_at:'2026-09-30T10:00:00Z',capabilities:{mail:true,calendar:true}};
const read={kind:'mail' as const,account:status.account,observed_at:'2026-09-30T10:05:00Z'};
beforeEach(()=>{vi.useFakeTimers();vi.setSystemTime(new Date('2026-09-30T10:10:00Z'));});
afterEach(()=>vi.useRealTimers());
it('does not confuse account checks, grants and successful reads, even for an empty inbox',()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-09-30T10:10:00Z'));const identity=owner();observeConnectionStatus(identity,'google',status);
 expect(connectionServices('google',connectionHealth(identity,'google')).map(row=>row.label)).toEqual(['Not verified','Not verified']);
 expect(observeConnectionRead(identity,'google',connectionReadScope(identity,'google'),read)).toBe(true);
 const before=connectionHealth(identity,'google');expect(before.mail).toEqual({latest:'succeeded',lastSuccessAt:read.observed_at});expect(before.calendar.lastSuccessAt).toBeNull();
 vi.setSystemTime(new Date('2026-09-30T10:15:00Z'));observeConnectionStatus(identity,'google',status);
 const after=connectionHealth(identity,'google');expect(after.checkedAt).toBeGreaterThan(before.checkedAt!);expect(after.mail).toEqual(before.mail);
});
it.each(['account','connection','permission'] as const)('invalidates prior and in-flight proof after %s changes',change=>{
 const identity=owner();observeConnectionStatus(identity,'google',status);const scope=connectionReadScope(identity,'google');expect(observeConnectionRead(identity,'google',scope,read)).toBe(true);
 const changed=structuredClone(status);if(change==='account')changed.account.email='other@example.invalid';if(change==='connection')changed.connected_at='2026-09-30T10:06:00Z';if(change==='permission')changed.capabilities.calendar=false;
 observeConnectionStatus(identity,'google',changed);expect(connectionHealth(identity,'google').mail.lastSuccessAt).toBeNull();expect(observeConnectionRead(identity,'google',scope,read)).toBe(false);
});
it('isolates identities and providers and clears proof on reconnect/disconnect',()=>{
 const identity=owner(),other=owner();observeConnectionStatus(identity,'google',status);const scope=connectionReadScope(identity,'google');observeConnectionRead(identity,'google',scope,read);
 expect(connectionHealth(other,'google').mail.lastSuccessAt).toBeNull();expect(connectionHealth(identity,'microsoft').mail.lastSuccessAt).toBeNull();
 invalidateConnectionHealth(identity,'google');expect(observeConnectionRead(identity,'google',scope,read)).toBe(false);expect(connectionHealth(identity,'google').mail.lastSuccessAt).toBeNull();
});
it('keeps historical success separate from a failed, cancelled or unconfirmed current operation',()=>{
 const identity=owner();observeConnectionStatus(identity,'microsoft',status);const scope=connectionReadScope(identity,'microsoft');observeConnectionRead(identity,'microsoft',scope,read);
 connectionReadFailed(identity,'microsoft',scope,'mail');let health=connectionHealth(identity,'microsoft');expect(health.mail.lastSuccessAt).toBe(read.observed_at);expect(connectionServices('microsoft',health)[0]).toMatchObject({label:'Last read failed',tone:'attention'});
 connectionReadFailed(identity,'microsoft',scope,'mail',true);expect(connectionHealth(identity,'microsoft').mail.latest).toBe('cancelled');
 connectionCheckFailed(identity,'microsoft');health=connectionHealth(identity,'microsoft');expect(health.mail.lastSuccessAt).toBe(read.observed_at);expect(connectionReadScope(identity,'microsoft')).toBeNull();expect(connectionServices('microsoft',health)[0].tone).not.toBe('ready');
});
it('rejects mismatched accounts, pre-connection timestamps and ungranted reads without accepting content',()=>{
 const identity=owner();observeConnectionStatus(identity,'google',{...status,capabilities:{mail:true,calendar:false}});const scope=connectionReadScope(identity,'google');
 for(const result of [{...read,account:{email:'other@example.invalid'}},{...read,observed_at:'2026-09-30T09:59:00Z'},{...read,kind:'calendar' as const}])expect(observeConnectionRead(identity,'google',scope,result)).toBe(false);
 expect(connectionHealth(identity,'google').mail.lastSuccessAt).toBeNull();
});
it('does not grant calendar readiness to legacy Google status or Outlook readiness to Microsoft sign-in',()=>{
 const identity=owner();const {capabilities:_,...legacy}=status;observeConnectionStatus(identity,'google',legacy);observeConnectionStatus(identity,'microsoft',status);
 expect(connectionServices('google',connectionHealth(identity,'google'))[1]).toMatchObject({label:'Not verified',tone:'neutral'});
 expect(connectionServices('microsoft',connectionHealth(identity,'microsoft')).every(row=>row.label==='Not verified')).toBe(true);
});
