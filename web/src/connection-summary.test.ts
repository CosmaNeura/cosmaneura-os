import {beforeEach,expect,it,vi} from 'vitest';
import {readConnectionSummary,accountStatusSupported,faxConnectionSummary} from './connection-summary';
import {readFaxReadiness,type FaxReadiness,FAX_PROVIDERS} from './fax-readiness-api';
import {coreConnectionApi} from './core-connection-api';
import {googleConnectionRequest} from './google-connection-api';
import {microsoftConnectionRequest} from './microsoft-connection-api';
import {schedulingLoginRequest} from './scheduling-login-api';
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
vi.mock('./google-connection-api',()=>({googleConnectionRequest:vi.fn()}));
vi.mock('./microsoft-connection-api',()=>({microsoftConnectionRequest:vi.fn()}));
vi.mock('./scheduling-login-api',()=>({schedulingLoginRequest:vi.fn()}));
vi.mock('./fax-readiness-api',async importOriginal=>({...await importOriginal<typeof import('./fax-readiness-api')>(),readFaxReadiness:vi.fn()}));
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
beforeEach(()=>vi.clearAllMocks());
it.each(['google','microsoft','scheduling'] as const)('uses only the %s status read and retains the connected account label',async id=>{
  const reader=id==='google'?googleConnectionRequest:id==='microsoft'?microsoftConnectionRequest:schedulingLoginRequest;
  vi.mocked(schedulingLoginRequest).mockResolvedValue({state:'connected',label:'Synthetic account',connected_at:null});
  vi.mocked(googleConnectionRequest).mockResolvedValue({state:'connected',account:{label:'Invented',email:'provider@example.invalid'},connected_at:null});
  vi.mocked(microsoftConnectionRequest).mockResolvedValue({state:'connected',account:{label:'Invented',email:'provider@example.invalid'},connected_at:null});
  const signal=new AbortController().signal;
  expect(await readConnectionSummary(identity,id,signal)).toMatchObject(id==='scheduling'?{label:'Connected',tone:'neutral'}:{label:'Connected',tone:'neutral',services:expect.arrayContaining([expect.objectContaining({name:'Email',label:'Not verified'}),expect.objectContaining({name:'Calendar',label:'Not verified'})])});
  expect(reader).toHaveBeenCalledExactlyOnceWith(identity,'status',signal);
});
it.each([['sign_in_required','Needs setup'],['sign_in_pending','Needs setup'],['completing_sign_in','Not checked']] as const)('keeps %s distinct from connection success',async(state,label)=>{
  vi.mocked(microsoftConnectionRequest).mockResolvedValue({state,account:null,connected_at:null});
  expect(await readConnectionSummary(identity,'microsoft',new AbortController().signal)).toMatchObject({label});
});
it('preserves status-read failure instead of returning an optimistic badge',async()=>{
  vi.mocked(googleConnectionRequest).mockRejectedValue(new Error('offline'));
  await expect(readConnectionSummary(identity,'google',new AbortController().signal)).rejects.toThrow('offline');
});
it('marks a Gmail-only account as partly connected without reading calendar contents',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValue({state:'connected',account:{label:'Invented',email:'provider@example.invalid'},connected_at:null,capabilities:{mail:true,calendar:false}});
 expect(await readConnectionSummary(identity,'google',new AbortController().signal)).toMatchObject({label:'Needs attention',tone:'attention',services:expect.arrayContaining([expect.objectContaining({name:'Email',label:'Not verified'}),expect.objectContaining({name:'Calendar',label:'Permission needed'})]),action:'Review calendar access'});
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status']);
});
it('does not mark a practice review as connected or read encounter contents',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValue({connection_status:'review_required'} as never);
  expect(await readConnectionSummary(identity,'core',new AbortController().signal)).toMatchObject({label:'Needs attention',tone:'attention'});
  expect(vi.mocked(coreConnectionApi.read).mock.calls[0][1]).toMatchObject({action:'connection'});
});
const fax=():FaxReadiness=>({contract_version:1,scope:{box_id:'00000000-0000-4000-8000-000000000001',owner_id:'00000000-0000-4000-8000-000000000002'},enabled:true,work_enabled:true,delivery_enabled:true,credential_access_configured:true,document_storage_configured:true,providers:FAX_PROVIDERS.map(id=>({id,installed_accounts:0,active_accounts:0,review_required_accounts:0,unavailable_accounts:0,prepare_enabled_accounts:0}))});
it('uses only the account-only fax readiness read and retains its provider counts for the directory',async()=>{
  const value=fax();vi.mocked(readFaxReadiness).mockResolvedValue(value);const signal=new AbortController().signal;
  expect(accountStatusSupported('messaging')).toBe(true);
  expect(await readConnectionSummary(identity,'messaging',signal)).toMatchObject({label:'Needs setup',tone:'attention',faxReadiness:value});
  expect(readFaxReadiness).toHaveBeenCalledExactlyOnceWith(identity,signal);
  expect(coreConnectionApi.read).not.toHaveBeenCalled();expect(googleConnectionRequest).not.toHaveBeenCalled();expect(microsoftConnectionRequest).not.toHaveBeenCalled();
});
it('does not equate installed, reviewed, permitted or configured accounts with delivery verification',()=>{
  const value=fax(),provider=value.providers[1];provider.installed_accounts=1;
  expect(faxConnectionSummary(value).label).toBe('Needs setup');
  provider.active_accounts=1;
  expect(faxConnectionSummary(value).label).toBe('Needs setup');
  provider.prepare_enabled_accounts=1;value.credential_access_configured=false;
  expect(faxConnectionSummary(value)).toMatchObject({label:'Needs setup',tone:'attention',reason:expect.stringContaining('service access')});
  value.credential_access_configured=true;
  expect(faxConnectionSummary(value)).toMatchObject({label:'Available',tone:'neutral',proof:expect.stringContaining('Delivery is confirmed separately for each fax')});
});
it('keeps disabled setup and unavailable account evidence separate from missing installation',()=>{
  const value=fax();value.enabled=false;expect(faxConnectionSummary(value).label).toBe('Needs setup');
  value.enabled=true;value.providers[2].installed_accounts=1;value.providers[2].unavailable_accounts=1;
  expect(faxConnectionSummary(value)).toMatchObject({label:'Needs attention',tone:'attention'});
});
it('does not replace a failed fax readiness read with configured or ready status',async()=>{
  vi.mocked(readFaxReadiness).mockRejectedValue(new Error('unavailable'));
  await expect(readConnectionSummary(identity,'messaging',new AbortController().signal)).rejects.toThrow('unavailable');
});
it('names missing email access rather than sending the user to calendar setup',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValue({state:'connected',account:{label:'Invented',email:'provider@example.invalid'},connected_at:null,capabilities:{mail:false,calendar:true}});
 expect(await readConnectionSummary({...identity},'google',new AbortController().signal)).toMatchObject({label:'Needs attention',action:'Review email access',proof:'Sign-in confirmed. Email and calendar checks are separate.'});
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status']);
});
it('keeps scheduling sign-in separate from availability, saved appointments and calendar updates',async()=>{
 vi.mocked(schedulingLoginRequest).mockResolvedValue({state:'connected',label:'Invented practice',connected_at:null});
 const result=await readConnectionSummary({...identity},'scheduling',new AbortController().signal);
 expect(result).toMatchObject({label:'Connected',tone:'neutral',action:'Open scheduling connection'});
 expect(result.proof).toContain('Check available times from Follow-up in a visit');
 expect(result.proof).toContain('saved appointments and calendar updates have separate results');
 expect(schedulingLoginRequest).toHaveBeenCalledExactlyOnceWith(expect.anything(),'status',expect.any(AbortSignal));
});
