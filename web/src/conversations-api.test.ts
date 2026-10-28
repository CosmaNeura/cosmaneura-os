// @vitest-environment node
import {afterEach,describe,expect,it,vi} from 'vitest';
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Content-Type':'application/json'})}));
vi.mock('./workspace-protocol',()=>({workspaceFetch:(_identity:unknown,url:string,init:RequestInit)=>fetch(url,init)}));
import {conversationsApi,validateConversationInbox} from './conversations-api';
import {teamUuid} from './team-setup-test-fixture';
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
const row={workspace_id:teamUuid(1),appointment_id:null,context_label:'Invented private note',bot:{address:'chief',role:'chief',name:'Chief',available:true},preview:'Invented response',preview_withheld:false,attention:'needs_review',last_activity_at:'2026-10-23T12:00:00Z',watermark:'r1'+'0'.repeat(16)+'e'+'0'.repeat(96),unread:true,manual_unread:false,marker_version:0};
const inbox=()=>({contract_version:1,as_of:row.last_activity_at,rows:[row],next_cursor:null});
const response=(value:unknown,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
afterEach(()=>vi.unstubAllGlobals());
describe('bounded private conversation transport',()=>{
  it('reads only the explicit owner-scoped endpoint with its contract header',async()=>{const fetcher=vi.fn(async()=>response(inbox()));vi.stubGlobal('fetch',fetcher);expect(await conversationsApi.read(identity)).toEqual(inbox());const [url,init]=fetcher.mock.calls[0] as unknown as [string,RequestInit];expect(url).toMatch(/\/workspaces\/conversations$/);expect(init).toMatchObject({method:'GET',cache:'no-store',credentials:'omit',redirect:'error'});expect(new Headers(init.headers).get('X-Cosmas-Conversations')).toBe('1');});
  it.each([undefined,'private'])('rejects a response without no-store (%s)',async cache=>{vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(inbox()),{headers:{'Content-Type':'application/json',...(cache?{'Cache-Control':cache}:{})}})));await expect(conversationsApi.read(identity)).rejects.toMatchObject({status:502});});
  it('rejects duplicate rows, unknown statuses and oversized previews',()=>{for(const value of [{...inbox(),rows:[row,row]},{...inbox(),rows:[{...row,attention:'complete'}]},{...inbox(),rows:[{...row,preview:'a'.repeat(181)}]}])expect(()=>validateConversationInbox(value)).toThrow();});
  it('rejects malformed manual-read commands before transport',async()=>{const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);for(const command of [{manual_unread:false,expected_version:0},{manual_unread:true},{manual_unread:true,expected_version:-1},{expected_version:0}])await expect(conversationsApi.mark(identity,row.workspace_id,'chief',command)).rejects.toMatchObject({status:422});expect(fetcher).not.toHaveBeenCalled();});
  it('keeps the observed watermark and version exact',async()=>{const fetcher=vi.fn(async()=>response({contract_version:1,marker_version:1,manual_unread:false,seen_watermark:row.watermark}));vi.stubGlobal('fetch',fetcher);const command={watermark:row.watermark,manual_unread:false,expected_version:0};await conversationsApi.mark(identity,row.workspace_id,'chief',command);expect((fetcher.mock.calls[0] as unknown as [string,RequestInit])[1].body).toBe(JSON.stringify(command));});
  it('does not dispatch for an already-aborted operation',async()=>{const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);const stop=new AbortController();stop.abort();await expect(conversationsApi.read(identity,null,stop.signal)).rejects.toMatchObject({status:503});expect(fetcher).not.toHaveBeenCalled();});
});
