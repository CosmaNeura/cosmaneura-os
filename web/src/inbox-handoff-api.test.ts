import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {inboxHandoffApi} from './inbox-handoff-api';
import {inboxHandoffReceipts,inboxHandoffFixtureOperation,inboxHandoffSyntheticProposal,inboxHandoffMissing,inboxHandoffFixture,inboxHandoffFixtureCatalog,inboxHandoffIdentity as identity,inboxHandoffActor as actor,inboxHandoffTicketScope as scope,inboxHandoffStaffScope as staffScope,inboxHandoffWorkspaceScope as workspace} from './inbox-handoff-test-fixture';
import {vendorDigest} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const json=(value:unknown,status=200,headers?:Record<string,string>)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',vi.fn());vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');});
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
describe('bounded Inbox handoff transport',()=>{
  it('reads catalog under fresh signed credentials without inventing owner scope',async()=>{
    const catalog=await inboxHandoffFixtureCatalog(),getToken=vi.fn(async()=> 'invented-token');vi.mocked(fetch).mockResolvedValue(json(catalog));
    expect(await inboxHandoffApi.catalog({mode:'clerk_jwt',getToken},actor)).toEqual(catalog);expect(getToken).toHaveBeenCalledWith({skipCache:true});expect(fetch).toHaveBeenCalledTimes(1);
    const [url,init]=vi.mocked(fetch).mock.calls[0];expect(url).toBe('http://127.0.0.1:8000/inbox-handoffs');expect(new Headers(init?.headers).get('X-Cosmas-Inbox-Handoff-Contract')).toBe('1');
    expect(new Headers(init?.headers).get('X-Cosmas-Inbox-Contract')).toBeNull();expect(init).toMatchObject({method:'GET',credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});
  });
  it('binds owner and staff detail to their distinct current identities',async()=>{
    const owner=await inboxHandoffFixture(),staff=await inboxHandoffFixture('closed','staff');
    vi.mocked(fetch).mockResolvedValueOnce(json(owner)).mockResolvedValueOnce(json(staff));expect(await inboxHandoffApi.detail(identity,scope)).toEqual(owner);
    expect(await inboxHandoffApi.detail({boxId:scope.box_id,actorId:staffScope.actor_id},staffScope)).toEqual(staff);expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each(['decide','handoff','accept','result','verify'] as const)('sends the exact %s operation once and explicitly resolves the same request',async kind=>{
    const op=await inboxHandoffFixtureOperation(kind),receipt=inboxHandoffReceipts[{decide:1,handoff:2,accept:3,result:4,verify:5}[kind]],who={boxId:op.scope.box_id,actorId:op.scope.actor_id};
    vi.mocked(fetch).mockImplementation(async()=>json(receipt));expect(await inboxHandoffApi.execute(who,op)).toEqual(receipt);expect(await inboxHandoffApi.recover(who,op)).toEqual(receipt);
    const calls=vi.mocked(fetch).mock.calls;expect(calls).toHaveLength(2);expect(calls[0][0]).toBe(`http://127.0.0.1:8000/inbox-handoffs/${scope.id}/${op.kind}`);expect(JSON.parse(calls[0][1]!.body as string)).toEqual(op.request);
    expect(calls[1][0]).toBe(`http://127.0.0.1:8000/inbox-handoffs/${scope.id}/resolve`);expect(JSON.parse(calls[1][1]!.body as string)).toEqual({command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256});
  });
  it('uses distinct workspace proposal and resolver routes',async()=>{
    const {operation,receipt}=await inboxHandoffSyntheticProposal();vi.mocked(fetch).mockImplementation(async()=>json(receipt));
    await inboxHandoffApi.execute(identity,operation);await inboxHandoffApi.recover(identity,operation);
    expect(vi.mocked(fetch).mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8000/workspaces/${workspace.id}/inbox-handoffs/propose`,`http://127.0.0.1:8000/workspaces/${workspace.id}/inbox-handoffs/resolve`]);
  });
  it('accepts not_found only from the explicit recovery route and never retries it',async()=>{
    const op=await inboxHandoffFixtureOperation(),missing=inboxHandoffMissing(op);vi.mocked(fetch).mockImplementation(async()=>json(missing));
    expect(await inboxHandoffApi.recover(identity,op)).toEqual(missing);await expect(inboxHandoffApi.execute(identity,op)).rejects.toMatchObject({status:502});expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('returns an exact durable rejection independently of service errors',async()=>{
    const op=await inboxHandoffFixtureOperation(),{receipt_sha256:_,...body}={...inboxHandoffReceipts[1],outcome:'rejected',effect:null,rejection:'work_changed'};
    const rejected={...body,receipt_sha256:await vendorDigest('cosmas-inbox-handoff-receipt.v1',body)};vi.mocked(fetch).mockResolvedValue(json(rejected));expect(await inboxHandoffApi.execute(identity,op)).toEqual(rejected);
  });
  it('blocks invalid paths, wrong actor and untrusted origins before token retrieval or dispatch',async()=>{
    const getToken=vi.fn(async()=> 'invented-token'),signed={mode:'clerk_jwt' as const,getToken};
    await expect(inboxHandoffApi.detail(signed,{...scope,id:'../other'})).rejects.toMatchObject({status:502});
    await expect(inboxHandoffApi.detail(identity,staffScope)).rejects.toMatchObject({status:403});await expect(inboxHandoffApi.detail(identity,workspace)).rejects.toMatchObject({status:502});
    await expect(inboxHandoffApi.catalog(identity,{...actor,box_id:crypto.randomUUID()})).rejects.toMatchObject({status:403});
    vi.stubEnv('VITE_API_BASE','https://evil.invalid');await expect(inboxHandoffApi.catalog(signed,actor)).rejects.toMatchObject({status:503});expect(getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
  it.each([401,403,404,426])('cancels %s authority-denied private bytes without reading them',async status=>{
    const cancel=vi.fn(async()=>{}),read=vi.fn();vi.mocked(fetch).mockResolvedValue({status,body:{cancel,getReader:()=>({read})}} as unknown as Response);
    await expect(inboxHandoffApi.catalog(identity,actor)).rejects.toMatchObject({status});expect(cancel).toHaveBeenCalled();expect(read).not.toHaveBeenCalled();
  });
  it.each(['duplicate','invalid_utf8','no_store','wrong_type','extra_scope','wrong_actor_detail','private_source_leak'] as const)('fails closed on %s response',async fault=>{
    const catalog=await inboxHandoffFixtureCatalog(),owner=await inboxHandoffFixture();
    const response=fault==='duplicate'?new Response('{"contract_version":1,"contract_version":1}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):fault==='invalid_utf8'?new Response(new Uint8Array([255]),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):fault==='no_store'?json(catalog,200,{'Cache-Control':'private'}):fault==='wrong_type'?json(catalog,200,{'Content-Type':'text/html'}):fault==='extra_scope'?json({...catalog,scope:actor}):fault==='wrong_actor_detail'?json({...owner,originator_id:crypto.randomUUID()}):json(owner);
    vi.mocked(fetch).mockResolvedValue(response);
    if(fault==='private_source_leak')await expect(inboxHandoffApi.detail({boxId:scope.box_id,actorId:staffScope.actor_id},staffScope)).rejects.toMatchObject({status:502});
    else if(fault==='wrong_actor_detail')await expect(inboxHandoffApi.detail(identity,scope)).rejects.toMatchObject({status:502});else await expect(inboxHandoffApi.catalog(identity,actor)).rejects.toThrow();
  });
  it.each([['catalog',131072],['detail',65536],['execute',16384],['recover',16384]] as const)('caps declared and streamed %s bytes',async(kind,cap)=>{
    const op=await inboxHandoffFixtureOperation(),call=()=>kind==='catalog'?inboxHandoffApi.catalog(identity,actor):kind==='detail'?inboxHandoffApi.detail(identity,scope):inboxHandoffApi[kind](identity,op);
    for(const declared of [true,false]){vi.mocked(fetch).mockResolvedValue(new Response(new Uint8Array(cap+1),{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...(declared?{'Content-Length':String(cap+1)}:{})}}));await expect(call()).rejects.toMatchObject({status:503});}
  });
  it('rejects a corrupted receipt without issuing another mutation',async()=>{
    const op=await inboxHandoffFixtureOperation();vi.mocked(fetch).mockResolvedValue(json({...inboxHandoffReceipts[1],request_sha256:'0'.repeat(64)}));await expect(inboxHandoffApi.execute(identity,op)).rejects.toMatchObject({status:502});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('caps error bytes and exposes only the closed safe-code set',async()=>{
    vi.mocked(fetch).mockResolvedValueOnce(json({contract_version:1,error:{code:'inbox_handoff_changed'}},409));await expect(inboxHandoffApi.catalog(identity,actor)).rejects.toMatchObject({status:409,code:'inbox_handoff_changed'});
    vi.mocked(fetch).mockResolvedValueOnce(json({contract_version:1,error:{code:'private-untrusted-text'}},409));await expect(inboxHandoffApi.catalog(identity,actor)).rejects.toMatchObject({status:409,code:undefined});
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new Uint8Array(2049),{status:409,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));await expect(inboxHandoffApi.catalog(identity,actor)).rejects.toMatchObject({status:503});
  });
  it('includes stalled credentials in its 15-second deadline',async()=>{
    vi.useFakeTimers();let release!:(v:string)=>void;const promise=expect(inboxHandoffApi.catalog({mode:'clerk_jwt',getToken:()=>new Promise(r=>{release=r;})},actor)).rejects.toMatchObject({status:503});
    await vi.advanceTimersByTimeAsync(15001);await promise;release('late-invented-token');await vi.advanceTimersByTimeAsync(1);expect(fetch).not.toHaveBeenCalled();
  });
  it('includes uncooperative body reads and cancellation in the same deadline',async()=>{
    vi.useFakeTimers();const cancel=vi.fn(()=>new Promise(()=>{}));vi.mocked(fetch).mockResolvedValue({status:200,headers:new Headers({'Content-Type':'application/json','Cache-Control':'no-store'}),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel})}} as unknown as Response);
    const promise=expect(inboxHandoffApi.catalog(identity,actor)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(15001);await promise;expect(cancel).toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('honors caller cancellation before any I/O',async()=>{
    const controller=new AbortController();controller.abort();await expect(inboxHandoffApi.catalog(identity,actor,controller.signal)).rejects.toMatchObject({status:503});expect(fetch).not.toHaveBeenCalled();
  });
  function desktop(){
    vi.stubGlobal('window',{location:{href:'app://cosmas/index.html'}});vi.stubEnv('VITE_API_BASE','app://cosmas/api');
    for(const key of ['VITE_WORKSPACE_DESKTOP_AUTH_ENABLED','VITE_DESKTOP_SYNTHETIC_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_ENABLED'])vi.stubEnv(key,'true');vi.stubEnv('VITE_COSMAS_ENV','synth_os');
  }
  it('rechecks native session currency after receiving private bytes',async()=>{
    const catalog=await inboxHandoffFixtureCatalog();desktop();let current=true;const signed={mode:'desktop_native' as const,revision:crypto.randomUUID(),isCurrent:()=>current};
    vi.mocked(fetch).mockImplementation(async()=>{current=false;return json(catalog);});await expect(inboxHandoffApi.catalog(signed,actor)).rejects.toMatchObject({status:503});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('withholds detail if the native session changes during payload verification',async()=>{
    const detail=await inboxHandoffFixture();desktop();let current=true;const signed={mode:'desktop_native' as const,revision:crypto.randomUUID(),isCurrent:()=>current};
    vi.mocked(fetch).mockResolvedValue(json(detail));vi.stubGlobal('crypto',{subtle:{digest:async(algorithm:AlgorithmIdentifier,data:BufferSource)=>{const h=await webcrypto.subtle.digest(algorithm,data);current=false;return h;}}});
    await expect(inboxHandoffApi.detail(signed,scope)).rejects.toMatchObject({status:503});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('bounds stalled operation hashing before retrieving credentials',async()=>{
    const op=await inboxHandoffFixtureOperation(),getToken=vi.fn(async()=> 'invented-token');vi.useFakeTimers();vi.stubGlobal('crypto',{subtle:{digest:()=>new Promise(()=>{})}});
    const promise=expect(inboxHandoffApi.execute({mode:'clerk_jwt',getToken},op)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(15001);await promise;expect(getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
});
