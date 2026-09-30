import {beforeEach,expect,it,vi} from 'vitest';
import {readConnectionSummary} from './connection-summary';
import {coreConnectionApi} from './core-connection-api';
import {googleConnectionRequest} from './google-connection-api';
import {microsoftConnectionRequest} from './microsoft-connection-api';
import {schedulingLoginRequest} from './scheduling-login-api';
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
vi.mock('./google-connection-api',()=>({googleConnectionRequest:vi.fn()}));
vi.mock('./microsoft-connection-api',()=>({microsoftConnectionRequest:vi.fn()}));
vi.mock('./scheduling-login-api',()=>({schedulingLoginRequest:vi.fn()}));
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
beforeEach(()=>vi.clearAllMocks());
it.each(['google','microsoft','scheduling'] as const)('uses only the %s status read and retains the connected account label',async id=>{
  const reader=id==='google'?googleConnectionRequest:id==='microsoft'?microsoftConnectionRequest:schedulingLoginRequest;
  vi.mocked(schedulingLoginRequest).mockResolvedValue({state:'connected',label:'Synthetic account',connected_at:null});
  vi.mocked(googleConnectionRequest).mockResolvedValue({state:'connected',account:{label:'Invented',email:'provider@example.invalid'},connected_at:null});
  vi.mocked(microsoftConnectionRequest).mockResolvedValue({state:'connected',account:{label:'Invented',email:'provider@example.invalid'},connected_at:null});
  const signal=new AbortController().signal;
  expect(await readConnectionSummary(identity,id,signal)).toMatchObject(id==='scheduling'?{label:'Connected',tone:'ready'}:{label:'Account connected',tone:'neutral',services:expect.arrayContaining([expect.objectContaining({name:'Email',label:'Not verified'}),expect.objectContaining({name:'Calendar',label:'Not verified'})])});
  expect(reader).toHaveBeenCalledExactlyOnceWith(identity,'status',signal);
});
it.each([['sign_in_required','Not connected'],['sign_in_pending','Sign-in pending'],['completing_sign_in','Finishing sign-in']] as const)('keeps %s distinct from connection success',async(state,label)=>{
  vi.mocked(microsoftConnectionRequest).mockResolvedValue({state,account:null,connected_at:null});
  expect(await readConnectionSummary(identity,'microsoft',new AbortController().signal)).toMatchObject({label});
});
it('preserves status-read failure instead of returning an optimistic badge',async()=>{
  vi.mocked(googleConnectionRequest).mockRejectedValue(new Error('offline'));
  await expect(readConnectionSummary(identity,'google',new AbortController().signal)).rejects.toThrow('offline');
});
it('marks a Gmail-only account as partly connected without reading calendar contents',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValue({state:'connected',account:{label:'Invented',email:'provider@example.invalid'},connected_at:null,capabilities:{mail:true,calendar:false}});
 expect(await readConnectionSummary(identity,'google',new AbortController().signal)).toMatchObject({label:'Partly connected',tone:'attention',services:expect.arrayContaining([expect.objectContaining({name:'Email',label:'Not verified'}),expect.objectContaining({name:'Calendar',label:'Permission needed'})]),action:'Add calendar access'});
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status']);
});
it('does not mark a practice review as connected or read encounter contents',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValue({connection_status:'review_required'} as never);
  expect(await readConnectionSummary(identity,'core',new AbortController().signal)).toMatchObject({label:'Needs review',tone:'attention'});
  expect(vi.mocked(coreConnectionApi.read).mock.calls[0][1]).toMatchObject({action:'connection'});
});
