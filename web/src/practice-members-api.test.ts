import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {practiceAccessApi} from './practice-access-api';
import {validateMembersPage,type MemberChange} from './practice-members-contract';
import {practiceMember as row,memberPage,memberCommand,memberReceipt} from './practice-members-test-fixture';
const json=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
const identity={mode:'clerk_jwt' as const,getToken:vi.fn(async()=> 'invented.fresh.token')};
beforeEach(()=>{vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','false');vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','false');vi.stubGlobal('fetch',vi.fn());identity.getToken.mockClear();});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllEnvs();vi.unstubAllGlobals();});
it('uses exact scoped page and reviewed-change bodies with fresh negotiated credentials',async()=>{
  vi.mocked(fetch).mockResolvedValueOnce(json(memberPage)).mockResolvedValueOnce(json(memberReceipt(memberCommand))).mockResolvedValueOnce(json({contract_version:1,members:[],next_after_id:null}));
  expect(await practiceAccessApi.members(identity,null)).toEqual(memberPage);
  expect(await practiceAccessApi.memberChange(identity,memberCommand)).toEqual(memberReceipt(memberCommand));
  await practiceAccessApi.members(identity,row.member_id);
  expect(vi.mocked(fetch).mock.calls.map(call=>call[0])).toEqual(['http://127.0.0.1:8000/practice-access/members','http://127.0.0.1:8000/practice-access/member-change','http://127.0.0.1:8000/practice-access/members']);
  expect(vi.mocked(fetch).mock.calls.map(call=>JSON.parse(call[1]!.body as string))).toEqual([{after_id:null},memberCommand,{after_id:row.member_id}]);
  for(const [,init] of vi.mocked(fetch).mock.calls){expect(init?.method).toBe('POST');const headers=new Headers(init?.headers);expect(headers.get('X-Cosmas-Practice-Access-Contract')).toBe('1');expect(headers.get('Authorization')).toBe('Bearer invented.fresh.token');}
  expect(identity.getToken).toHaveBeenCalledTimes(3);
  expect(()=>practiceAccessApi.memberChange(identity,{...memberCommand,subject:'user_other'} as MemberChange)).toThrow();
  expect(()=>practiceAccessApi.members(identity,'not-a-cursor')).toThrow();expect(fetch).toHaveBeenCalledTimes(3);
});
it('rejects unsafe roles/actions, duplicate rows, extra identity data and backward page cursors',()=>{
  for(const altered of [{...row,role:'owner'},{...row,action:'reactivate'},{...row,state:'unavailable'},
    {...row,clerk_subject:'user_private'},{...row,expires_at:'2026-09-24T11:00:00+00:00'}])expect(()=>validateMembersPage({...memberPage,members:[altered]},null)).toThrow();
  expect(()=>validateMembersPage({...memberPage,members:[row,row]},null)).toThrow();
  expect(()=>validateMembersPage(memberPage,row.member_id)).toThrow();
  expect(()=>validateMembersPage({...memberPage,next_after_id:row.member_id},null)).toThrow();
});
it('preserves historical replay receipts while rejecting mismatched result identity and action',async()=>{
  vi.mocked(fetch).mockResolvedValueOnce(json(memberReceipt(memberCommand,true)));
  expect((await practiceAccessApi.memberChange(identity,memberCommand)).replayed).toBe(true);
  const receipt=memberReceipt(memberCommand);
  for(const wrong of [{...receipt.receipt,member_id:memberCommand.idempotency_key},{...receipt.receipt,recorded_state:'active'}, {...receipt.receipt,review_sha256:'b'.repeat(64)}]){
    vi.mocked(fetch).mockResolvedValueOnce(json({...receipt,receipt:wrong}));await expect(practiceAccessApi.memberChange(identity,memberCommand)).rejects.toMatchObject({status:502});
  }
  vi.mocked(fetch).mockResolvedValueOnce(json({detail:'practice_access_conflict'},409));
  await expect(practiceAccessApi.memberChange(identity,memberCommand)).rejects.toMatchObject({status:409});
});
