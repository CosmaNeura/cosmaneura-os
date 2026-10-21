// @ts-expect-error Vitest supplies Node crypto; production uses browser types.
import {webcrypto} from 'node:crypto';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CreatorReviewError} from '../../clients/scribe-review/creator-review-api';
import {creatorReviewApi} from './creator-review-api';
import {captureFailureObservation,request} from './capture-api';
import {WorkspaceApiError} from './workspace-api';
import * as protocol from './workspace-protocol';

const workspace='00000000-0000-4000-8000-000000000002',session='00000000-0000-4000-8000-000000000003';
const identity={mode:'clerk_jwt' as const,getToken:async()=>'synthetic-token'};
const headers={'Content-Type':'application/json','Cache-Control':'no-store'};
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
async function failed(api:ReturnType<typeof creatorReviewApi>){try{await api.read();}catch(error){expect(error).toBeInstanceOf(CreatorReviewError);return error as CreatorReviewError;}throw Error('Expected synthetic failure');}

it.each([
 ['core_capture_identity_unavailable','core_identity_unavailable','context_exchange'],
 ['core_capture_context_invalid','core_context_invalid','context_resolution'],
 ['core_capture_receipt_invalid','core_receipt_invalid','binding_resolution'],
 ['core_capture_receipt_invalid','core_receipt_invalid','session_verification'],
 ['core_capture_request_unconfirmed','core_request_unconfirmed','review'],
]as const)('retains only known Core failure %s and closed hop %s',async(detail,reason,capture_phase)=>{
 const fetcher=vi.fn().mockResolvedValue(Response.json({detail,capture_phase,body:'private-marker',session_id:'private-marker'},{status:503,headers}));vi.stubGlobal('fetch',fetcher);
 const error=await failed(creatorReviewApi(workspace,session,identity));expect(error.failure).toEqual({phase:'read',reason,status:503,corePhase:capture_phase});
 expect(JSON.stringify(error)).not.toContain('private-marker');expect(fetcher).toHaveBeenCalledOnce();
 expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({session_id:session,operation:{kind:'creator_review'}});
});
it.each([
 ['private-marker','review','request_unavailable'],
 ['core_capture_receipt_invalid','private-marker','core_receipt_invalid'],
]as const)('strips unknown Core code or hop %s/%s',async(detail,capture_phase,reason)=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(Response.json({detail,capture_phase},{status:503,headers})));
 const error=await failed(creatorReviewApi(workspace,session,identity));expect(error.failure).toEqual({phase:'read',reason,status:503});expect(JSON.stringify(error)).not.toContain('private-marker');
});
it.each([403,409])('does not admit Core-hop metadata from an unsupportedHTTP%s response',async status=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(Response.json({detail:'core_capture_receipt_invalid',capture_phase:'review'},{status,headers})));
 expect((await failed(creatorReviewApi(workspace,session,identity))).failure).toEqual({phase:'read',reason:'request_unavailable',status});
});
it('distinguishes a transport failure from actualHTTP503 without changing the shared unconfirmed status',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new TypeError('private transport marker')));
 const body={session_id:session,idempotency_key:'same-read-key',operation:{kind:'creator_review'}};
 try{await request(workspace,'operations',identity,body);}catch(error){expect(error).toMatchObject({status:503,code:'capture_request_unconfirmed'});expect(captureFailureObservation(error)).toEqual({origin:'client_transport',status:null});}
 const error=await failed(creatorReviewApi(workspace,session,identity));expect(error.failure).toEqual({phase:'read',reason:'client_transport_unavailable',status:null});expect(JSON.stringify(error)).not.toContain('private transport marker');
});
function heldFetch(){const fetcher=vi.fn((_url:string,init:RequestInit)=>new Promise<Response>((_resolve,reject)=>{init.signal!.addEventListener('abort',()=>reject(new DOMException('private cancelled marker','AbortError')),{once:true});}));vi.stubGlobal('fetch',fetcher);return fetcher;}
it('identifies the existing30s client deadline with no invented server response status',async()=>{
 vi.useFakeTimers();const fetcher=heldFetch();const pending=failed(creatorReviewApi(workspace,session,identity));await vi.advanceTimersByTimeAsync(0);expect(fetcher).toHaveBeenCalledOnce();
 await vi.advanceTimersByTimeAsync(30000);expect((await pending).failure).toEqual({phase:'read',reason:'client_timeout',status:null});expect(vi.getTimerCount()).toBe(0);
});
it('distinguishes explicit cancellation while preserving the same session and no automatic retry',async()=>{
 vi.useFakeTimers();const fetcher=heldFetch(),controller=new AbortController();const pending=failed(creatorReviewApi(workspace,session,identity,controller.signal));await vi.advanceTimersByTimeAsync(0);controller.abort();
 expect((await pending).failure).toEqual({phase:'read',reason:'client_cancelled',status:null});expect(fetcher).toHaveBeenCalledOnce();expect(vi.getTimerCount()).toBe(0);
 expect(JSON.parse(String(fetcher.mock.calls[0][1].body)).session_id).toBe(session);
});
it('identifies a workspace protocol pause without claiming it was anHTTP503',async()=>{
 vi.spyOn(protocol,'workspaceFetch').mockRejectedValueOnce(new WorkspaceApiError(503,'workspace_protocol_required'));const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
 expect((await failed(creatorReviewApi(workspace,session,identity))).failure).toEqual({phase:'read',reason:'workspace_connection_paused',status:null});expect(fetcher).not.toHaveBeenCalled();
});
