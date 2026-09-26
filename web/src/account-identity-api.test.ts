import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {accountIdentityApi,validateAccountIdentity} from './account-identity-api';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import * as contract from './vendor-contract';
import actual from './__fixtures__/account-identity/actual-account-identity-http.json';
import actualRaw from './__fixtures__/account-identity/actual-account-identity-http.json?raw';
const {createHash}=await vi.importActual<{createHash:(algorithm:string)=>{update:(input:string)=>{digest:(encoding:'hex')=>string}}}>('node:crypto');

// Exact offline signed main-app responses, not a claim of live identity-service acceptance.
// w36-account-identity-r1/public/actual-account-identity-http.json
const fixtureSha='fc9cb743463d85141eb4af126a9a05309e014c74b840d2fbf24af2554d0fc7f6';
const endpoint='http://127.0.0.1:8000/provider-team/identity';
const jsonHeaders={'Content-Type':'application/json','Cache-Control':'no-store'};
const json=(value:unknown,status=200,headers?:Record<string,string>)=>new Response(JSON.stringify(value),{status,headers:{...jsonHeaders,...headers}});
const wire=(body:BodyInit|null,status=200,headers?:Record<string,string>)=>new Response(body,{status,headers:{...jsonHeaders,...headers}});
const credentials=()=>({mode:'clerk_jwt' as const,getToken:vi.fn(async()=> 'invented-token')});
const read=(signal?:AbortSignal)=>accountIdentityApi.read(credentials(),signal);
beforeEach(()=>{
  vi.stubGlobal('fetch',vi.fn());vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');
  vi.stubEnv('VITE_DESKTOP_SYNTHETIC_ENABLED','false');vi.stubEnv('VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED','false');
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});

describe('closed signed account context',()=>{
  it('validates the byte-identical frozen owner, staff and peer vectors',()=>{
    expect(createHash('sha256').update(actualRaw).digest('hex')).toBe(fixtureSha);
    for(const role of ['owner','staff','peer'] as const)expect(validateAccountIdentity(actual[role].body)).toEqual(actual[role].body);
    expect(new Set([actual.owner.body,actual.staff.body,actual.peer.body].map(v=>v.actor_id)).size).toBe(3);
    expect(new Set([actual.owner.body,actual.staff.body,actual.peer.body].map(v=>v.recovery_scope)).size).toBe(3);
  });
  it('returns independent data and never fills in a missing actor or recovery scope',()=>{
    const value=structuredClone(actual.owner.body),parsed=validateAccountIdentity(value);
    value.actor_id=actual.staff.body.actor_id;value.recovery_scope=actual.staff.body.recovery_scope;
    expect(parsed).toEqual(actual.owner.body);
    for(const key of ['actor_id','recovery_scope']){
      const incomplete={...actual.owner.body} as Record<string,unknown>;delete incomplete[key];
      expect(()=>validateAccountIdentity(incomplete)).toThrow(WorkspaceApiError);
    }
  });
  it.each([
    null,[],{}, {...actual.owner.body,role:'owner'}, {...actual.owner.body,contract_version:'1'},
    {...actual.owner.body,contract_version:2}, {...actual.owner.body,box_id:null},
    {...actual.owner.body,box_id:actual.owner.body.box_id.toUpperCase()},
    {...actual.owner.body,actor_id:actual.owner.body.actor_id.replaceAll('-','')},
    {...actual.owner.body,actor_id:'urn:uuid:'+actual.owner.body.actor_id},
    {...actual.owner.body,recovery_scope:'A'.repeat(64)}, {...actual.owner.body,recovery_scope:'a'.repeat(63)},
    {...actual.owner.body,recovery_scope:'a'.repeat(65)}, {...actual.owner.body,recovery_scope:'g'.repeat(64)},
  ])('rejects noncanonical or open identity data %#',value=>{
    expect(()=>validateAccountIdentity(value)).toThrow(WorkspaceApiError);
  });
  it('rejects inherited data, symbols and accessors without invoking the accessor',()=>{
    const getter=vi.fn(()=>actual.owner.body.actor_id),accessor={...actual.owner.body};
    Object.defineProperty(accessor,'actor_id',{get:getter,enumerable:true});
    const hidden={...actual.owner.body};Object.defineProperty(hidden,'hidden',{value:'private'});
    for(const value of [Object.create(actual.owner.body),accessor,hidden,{...actual.owner.body,[Symbol('private')]:'private'}])expect(()=>validateAccountIdentity(value)).toThrow(WorkspaceApiError);
    expect(getter).not.toHaveBeenCalled();
  });
});

describe('bounded account identity transport',()=>{
  it.each(['owner','staff','peer'] as const)('reads actual %s context with fresh signed credentials and the exact fixed request',async role=>{
    const identity=credentials(),fixture=actual[role];vi.mocked(fetch).mockResolvedValue(json(fixture.body,fixture.status,fixture.headers));
    expect(await accountIdentityApi.read(identity)).toEqual(fixture.body);expect(identity.getToken).toHaveBeenCalledExactlyOnceWith({skipCache:true});expect(fetch).toHaveBeenCalledTimes(1);
    const [url,init]=vi.mocked(fetch).mock.calls[0],headers=new Headers(init?.headers);
    expect(url).toBe(endpoint);expect(init).toMatchObject({method:'GET',credentials:'omit',redirect:'error',cache:'no-store',referrerPolicy:'no-referrer'});
    expect(Object.hasOwn(init!,'body')).toBe(false);expect(init?.signal).toBeInstanceOf(AbortSignal);
    expect(headers.get('Authorization')).toBe('Bearer invented-token');expect(headers.get('X-Cosmas-Team-Contract')).toBe('2');expect(headers.get('X-Cosmas-Draft-Recovery')).toBe('2');
    for(const name of ['X-Box-Id','X-Actor-Principal-Id','Content-Encoding','Transfer-Encoding','Content-Length'])expect(headers.has(name)).toBe(false);
  });
  it('preserves the actual disabled-account denial',async()=>{
    const fixture=actual.disabled_identity;vi.mocked(fetch).mockResolvedValue(json(fixture.body,fixture.status,fixture.headers));
    await expect(read()).rejects.toMatchObject({status:403,code:'identity_access_denied'});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('reauthenticates every read and does not cache one actor as another',async()=>{
    const identity=credentials();vi.mocked(fetch).mockResolvedValueOnce(json(actual.owner.body)).mockResolvedValueOnce(json(actual.staff.body));
    expect(await accountIdentityApi.read(identity)).toEqual(actual.owner.body);expect(await accountIdentityApi.read(identity)).toEqual(actual.staff.body);expect(identity.getToken).toHaveBeenCalledTimes(2);
  });
  it('rejects raw synthetic and malformed identities before credentials or dispatch',async()=>{
    const getToken=vi.fn();
    for(const value of [{boxId:actual.owner.body.box_id,actorId:actual.owner.body.actor_id,getToken},{mode:'synthetic',getToken},{mode:'clerk_jwt'},{mode:'desktop_native',revision:actual.owner.body.actor_id},null]){
      await expect(accountIdentityApi.read(value as unknown as WorkspaceIdentity)).rejects.toMatchObject({status:401});
    }
    expect(getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
  it.each(['https://outside.invalid','http://outside.invalid','http://127.0.0.1:8000/other','http://127.0.0.1:8000?box=x','http://127.0.0.1:8000?','http://127.0.0.1:8000#','http://user:secret@127.0.0.1:8000','app://cosmas/api'])('rejects unqualified base %s before credentials',async base=>{
    const identity=credentials();vi.stubEnv('VITE_API_BASE',base);
    await expect(accountIdentityApi.read(identity)).rejects.toMatchObject({status:503});expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects an unqualified browser page before asking for credentials',async()=>{
    const identity=credentials();vi.stubGlobal('window',{location:{href:'https://outside.invalid/private'}});
    await expect(accountIdentityApi.read(identity)).rejects.toMatchObject({status:401});expect(identity.getToken).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
  });
  it.each([null,'','contains whitespace','x'.repeat(8193)])('rejects missing or malformed credentials %#',async token=>{
    await expect(accountIdentityApi.read({mode:'clerk_jwt',getToken:async()=>token})).rejects.toMatchObject({status:401});expect(fetch).not.toHaveBeenCalled();
  });
  it('does not expose credential or transport exception strings',async()=>{
    const secret='private credential or response text';
    const authError=await accountIdentityApi.read({mode:'clerk_jwt',getToken:async()=>{throw new Error(secret);}}).catch(e=>e);
    expect(authError).toMatchObject({status:401});expect(String(authError)).not.toContain(secret);expect(fetch).not.toHaveBeenCalled();
    vi.mocked(fetch).mockRejectedValue(new Error(secret));const transportError=await read().catch(e=>e);
    expect(transportError).toMatchObject({status:503});expect(String(transportError)).not.toContain(secret);expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([
    {'Cache-Control':'private'}, {'Cache-Control':'no-store=1'}, {'Content-Type':'text/html'},
    {'Content-Encoding':'gzip'}, {'Content-Encoding':'identity'}, {'Content-Encoding':''},
    ...['-1','+1','00','010','1.0','1e3','1, 1','1025','9007199254740993'].map(v=>({'Content-Length':v})),
  ] as Record<string,string>[])('rejects ambiguous, encoded or unbounded headers %#',async headers=>{
    vi.mocked(fetch).mockResolvedValue(json(actual.owner.body,200,headers));await expect(read()).rejects.toMatchObject({status:502});
  });
  it('rejects missing no-store and content-type before reading private bytes',async()=>{
    for(const headers of [{},{'Cache-Control':'no-store'},{'Content-Type':'application/json'}] as Record<string,string>[]){
      const cancel=vi.fn(async()=>{}),getReader=vi.fn();
      vi.mocked(fetch).mockResolvedValue({status:200,headers:new Headers(headers),body:{cancel,getReader}} as unknown as Response);
      await expect(read()).rejects.toMatchObject({status:502});expect(getReader).not.toHaveBeenCalled();expect(cancel).toHaveBeenCalled();
    }
  });
  it('accepts an exact 1024-byte body and rejects declared length mismatches',async()=>{
    const text=JSON.stringify(actual.owner.body).padEnd(1024,' ');vi.mocked(fetch).mockResolvedValue(wire(text,200,{'Content-Length':'1024','Cache-Control':'private, NO-STORE','Content-Type':'application/json; charset=utf-8'}));
    expect(await read()).toEqual(actual.owner.body);
    for(const length of ['0','1024']){vi.mocked(fetch).mockResolvedValue(json(actual.owner.body,200,{'Content-Length':length}));await expect(read()).rejects.toMatchObject({status:502});}
  });
  it.each([200,403,503])('caps unannounced streamed bytes for status %s',async status=>{
    const cancel=vi.fn(async()=>{}),reader={read:vi.fn().mockResolvedValueOnce({done:false,value:new Uint8Array(1024)}).mockResolvedValueOnce({done:false,value:new Uint8Array(1)}),cancel,releaseLock:vi.fn()};
    vi.mocked(fetch).mockResolvedValue({status,headers:new Headers(jsonHeaders),body:{getReader:()=>reader}} as unknown as Response);
    await expect(read()).rejects.toMatchObject({status:status===403?403:502,code:undefined});expect(reader.read).toHaveBeenCalledTimes(2);expect(cancel).toHaveBeenCalled();
  });
  it.each([
    '{"contract_version":1,"contract_version":1}',
    JSON.stringify(actual.owner.body).replace('"actor_id":','"actor_id":"'+actual.owner.body.actor_id+'","actor_\\u0069d":'),
    JSON.stringify(actual.owner.body).replace('"contract_version":1','"contract_version":1.0'),
    JSON.stringify(actual.owner.body).replace('"contract_version":1','"contract_version":1e0'),
    JSON.stringify(actual.owner.body)+' trailing',new Uint8Array([0xff]),new Uint8Array([0xc3]),
    new Uint8Array([0xef,0xbb,0xbf,...new TextEncoder().encode(JSON.stringify(actual.owner.body))]),
    null,
  ])('rejects ambiguous JSON, invalid UTF-8 or empty bodies %#',async body=>{
    vi.mocked(fetch).mockResolvedValue(wire(body));await expect(read()).rejects.toMatchObject({status:502});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each(['redirected','opaque','opaqueredirect','origin','path','query','status'] as const)('rejects a %s response without a second dispatch',async fault=>{
    const response=json(actual.owner.body,fault==='status'?302:200);
    if(fault==='redirected')Object.defineProperty(response,'redirected',{value:true});
    if(fault==='opaque'||fault==='opaqueredirect')Object.defineProperty(response,'type',{value:fault});
    if(['origin','path','query'].includes(fault))Object.defineProperty(response,'url',{value:fault==='origin'?'https://outside.invalid/provider-team/identity':fault==='path'?endpoint+'/other':endpoint+'?other=1'});
    vi.mocked(fetch).mockResolvedValue(response);await expect(read()).rejects.toMatchObject({status:502});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('accepts a returned URL only when it is the requested URL',async()=>{
    const response=json(actual.owner.body);Object.defineProperty(response,'url',{value:endpoint});vi.mocked(fetch).mockResolvedValue(response);expect(await read()).toEqual(actual.owner.body);
  });
  it.each([[401,'identity_authentication_required'],[403,'identity_access_denied'],[404,'identity_unavailable'],[405,'invalid_identity_request'],[422,'invalid_identity_request'],[426,'team_contract_required'],[426,'workspace_client_update_required'],[503,'identity_unavailable'],[504,'identity_timeout']] as const)('preserves closed server failure %s / %s',async(status,code)=>{
    vi.mocked(fetch).mockResolvedValue(json({detail:code},status));await expect(read()).rejects.toMatchObject({status,code});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([
    [403,{detail:'private external error text'}],[403,{detail:'identity_unavailable'}],
    [403,{detail:'identity_access_denied',extra:'private external error text'}],
    [500,{detail:'identity_unavailable'}],[201,actual.owner.body],
  ])('withholds unknown, open or mismatched server errors %#',async(status,value)=>{
    vi.mocked(fetch).mockResolvedValue(json(value,status as number));const error=await read().catch(e=>e);
    expect(error).toMatchObject({status:status===403?403:502,code:undefined});expect(String(error)).not.toContain('private external error text');
  });
  it('rejects duplicate error keys rather than choosing an authority result',async()=>{
    vi.mocked(fetch).mockResolvedValue(wire('{"detail":"identity_access_denied","detail":"identity_unavailable"}',403));await expect(read()).rejects.toMatchObject({status:403,code:undefined});
  });
  it.each([401,403,404,200,422])('rejects malformed status %s without retaining any private response text',async status=>{
    const secret='private external error text';
    const responses=[
      json({detail:secret},status),
      json({detail:'identity_access_denied',extra:secret},status),
      wire('{"detail":"'+secret+'",',status),
      wire('{"detail":"'+secret+'","detail":"identity_access_denied"}',status),
      json({detail:secret},status,{'Cache-Control':'private'}),
      json({detail:secret},status,{'Content-Type':'text/html'}),
      json({detail:secret},status,{'Content-Length':'01'}),
      wire(new Uint8Array([0xff]),status),
      wire(secret.repeat(100),status),
      json({detail:secret},status,{'Content-Length':'1025'}),
    ];
    for(const response of responses){
      vi.mocked(fetch).mockResolvedValue(response);const error=await read().catch(e=>e);
      expect(error).toMatchObject({status:[401,403,404].includes(status)?status:502,code:undefined});
      expect(String(error)).not.toContain(secret);expect(JSON.stringify(error)).not.toContain(secret);
    }
    expect(fetch).toHaveBeenCalledTimes(responses.length);
  });
});

describe('one account-identity deadline and current session',()=>{
  it('includes stalled credentials and never dispatches their late result',async()=>{
    vi.useFakeTimers();let release!:(v:string)=>void;
    const task=expect(accountIdentityApi.read({mode:'clerk_jwt',getToken:()=>new Promise(resolve=>{release=resolve;})})).rejects.toMatchObject({status:504,code:'identity_timeout'});
    await vi.advanceTimersByTimeAsync(15000);await task;release('late-invented-token');await vi.advanceTimersByTimeAsync(1);expect(fetch).not.toHaveBeenCalled();
  });
  it('keeps a late credential failure inside the same deadline',async()=>{
    let now=0;vi.spyOn(performance,'now').mockImplementation(()=>now);
    await expect(accountIdentityApi.read({mode:'clerk_jwt',getToken:async()=>{now=15000;throw new Error('private credential failure');}})).rejects.toMatchObject({status:504,code:'identity_timeout'});
    expect(fetch).not.toHaveBeenCalled();
  });
  it('includes stalled dispatch and cancels a late private response',async()=>{
    vi.useFakeTimers();let release!:(response:Response)=>void;vi.mocked(fetch).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
    const task=expect(read()).rejects.toMatchObject({status:504});await vi.advanceTimersByTimeAsync(15000);await task;
    const response=json(actual.owner.body),cancel=vi.spyOn(response.body!,'cancel');release(response);await vi.advanceTimersByTimeAsync(1);expect(cancel).toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([200,403])('keeps the deadline ahead of status %s for an uncooperative body and cancellation',async status=>{
    vi.useFakeTimers();const cancel=vi.fn(()=>new Promise(()=>{}));
    vi.mocked(fetch).mockResolvedValue({status,headers:new Headers(jsonHeaders),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel})}} as unknown as Response);
    const task=expect(read()).rejects.toMatchObject({status:504});await vi.advanceTimersByTimeAsync(15000);await task;expect(cancel).toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('shares 15 seconds across credentials, dispatch and body rather than restarting each phase',async()=>{
    vi.useFakeTimers();const cancel=vi.fn(async()=>{});
    const response={status:200,headers:new Headers(jsonHeaders),body:{getReader:()=>({read:()=>new Promise(resolve=>setTimeout(()=>resolve({done:false,value:new TextEncoder().encode(JSON.stringify(actual.owner.body))}),3000)),cancel})}} as unknown as Response;
    vi.mocked(fetch).mockImplementation(()=>new Promise(resolve=>setTimeout(()=>resolve(response),4000)));
    const task=expect(accountIdentityApi.read({mode:'clerk_jwt',getToken:()=>new Promise(resolve=>setTimeout(()=>resolve('invented-token'),9000))})).rejects.toMatchObject({status:504});
    await vi.advanceTimersByTimeAsync(14999);expect(cancel).not.toHaveBeenCalled();await vi.advanceTimersByTimeAsync(1);await task;expect(cancel).toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('checks the deadline after synchronous contract validation',async()=>{
    let now=0;vi.spyOn(performance,'now').mockImplementation(()=>now);
    const uuid=contract.vendorUuid;vi.spyOn(contract,'vendorUuid').mockImplementation((value:unknown):value is string=>{now=15000;return uuid(value);});
    vi.mocked(fetch).mockResolvedValue(json(actual.owner.body));await expect(read()).rejects.toMatchObject({status:504});
  });
  it('honors caller cancellation before credentials and while credentials are stalled',async()=>{
    const first=new AbortController(),identity=credentials();first.abort();
    await expect(accountIdentityApi.read(identity,first.signal)).rejects.toMatchObject({status:503});expect(identity.getToken).not.toHaveBeenCalled();
    const second=new AbortController();let release!:(value:string)=>void;
    const task=expect(accountIdentityApi.read({mode:'clerk_jwt',getToken:()=>new Promise(resolve=>{release=resolve;})},second.signal)).rejects.toMatchObject({status:503});
    second.abort();await task;release('late-invented-token');await Promise.resolve();expect(fetch).not.toHaveBeenCalled();
  });
  function desktop(){
    vi.stubGlobal('window',{location:{href:'app://cosmas/index.html'}});vi.stubEnv('VITE_API_BASE','app://cosmas/api');
    for(const key of ['VITE_WORKSPACE_DESKTOP_AUTH_ENABLED','VITE_DESKTOP_SYNTHETIC_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_ENABLED'])vi.stubEnv(key,'true');
    vi.stubEnv('VITE_COSMAS_ENV','synth_os');
    return {mode:'desktop_native' as const,revision:actual.owner.body.actor_id,isCurrent:()=>true};
  }
  it('uses the qualified native session header without a bearer or synthetic actor',async()=>{
    const identity=desktop();vi.mocked(fetch).mockResolvedValue(json(actual.owner.body));expect(await accountIdentityApi.read(identity)).toEqual(actual.owner.body);
    const [url,init]=vi.mocked(fetch).mock.calls[0],headers=new Headers(init?.headers);expect(url).toBe('app://cosmas/api/provider-team/identity');expect(headers.get('X-Cosmas-Desktop-Session')).toBe(identity.revision);
    expect(headers.get('X-Cosmas-Team-Contract')).toBe('2');expect(headers.get('X-Cosmas-Draft-Recovery')).toBe('2');expect(headers.has('Authorization')).toBe(false);expect(headers.has('X-Actor-Principal-Id')).toBe(false);
  });
  it.each(['flag','revision','stale'] as const)('rejects %s native authorization before dispatch',async fault=>{
    const identity=desktop();if(fault==='flag')vi.stubEnv('VITE_WORKSPACE_DESKTOP_AUTH_ENABLED','false');if(fault==='revision')identity.revision='invalid';if(fault==='stale')identity.isCurrent=()=>false;
    await expect(accountIdentityApi.read(identity)).rejects.toMatchObject({status:401});expect(fetch).not.toHaveBeenCalled();
  });
  it.each([200,403])('keeps the native session fence ahead of returned status %s',async status=>{
    const identity=desktop();let current=true;identity.isCurrent=()=>current;
    vi.mocked(fetch).mockImplementation(async()=>{current=false;return json(actual.owner.body,status);});await expect(accountIdentityApi.read(identity)).rejects.toMatchObject({status:401,code:'identity_authentication_required'});
  });
  it('rechecks the native session after contract validation and withholds its late result',async()=>{
    const identity=desktop();let current=true;identity.isCurrent=()=>current;
    const uuid=contract.vendorUuid;vi.spyOn(contract,'vendorUuid').mockImplementation((value:unknown):value is string=>{current=false;return uuid(value);});
    vi.mocked(fetch).mockResolvedValue(json(actual.owner.body));await expect(accountIdentityApi.read(identity)).rejects.toMatchObject({status:401});expect(fetch).toHaveBeenCalledTimes(1);
  });
});
