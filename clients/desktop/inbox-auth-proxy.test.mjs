import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {PassThrough} from 'node:stream';
import {EventEmitter} from 'node:events';
import {connectorApiRoute} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';
import {permittedApiPath as syntheticPath,proxyWorkspaceRequest as syntheticProxy} from './api-proxy.mjs';

const id='00000000-0000-4000-8000-000000000001',origin='app://cosmas/api',tick=()=>new Promise(r=>setImmediate(r));
const ih='X-Cosmas-Inbox-Contract',hh='X-Cosmas-Inbox-Handoff-Contract';
const inbox={[ih]:'1'},handoff={[hh]:'1'},identity={'X-Cosmas-Team-Contract':'2','X-Cosmas-Draft-Recovery':'2'};
const ready={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
function auth(){let state=ready,reads=0,tokens=0;const listeners=new Set();return {getState:async()=>{reads++;return state;},snapshot:()=>state,getToken:async()=>{tokens++;return 'invented.local.token';},subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},counts:()=>({reads,tokens}),revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
const request=(path,method='GET',headers={},body,signal)=>new Request(origin+path,{method,headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,...headers},...(body===undefined?{}:{body,duplex:'half'}),signal});
const json=(body='{}',status=200,headers={})=>new Response(body,{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
const fixture=name=>JSON.parse(readFileSync(new URL('../../web/src/__fixtures__/'+name,import.meta.url),'utf8'));
const routes=[
 ['/inbox','GET',ih,0,131072],['/inbox/resolve','POST',ih,8192,8192],
 [`/inbox/${id}`,'GET',ih,0,65536],[`/inbox/${id}/history`,'GET',ih,0,2097152],
 [`/inbox/${id}/review-options`,'GET',ih,0,131072],[`/inbox/${id}/sources/${id}`,'GET',ih,0,65536],
 ...['review','triage','result','verify'].map(k=>[`/inbox/${id}/${k}`,'POST',ih,8192,8192]),
 ['/inbox-handoffs','GET',hh,0,131072],[`/inbox-handoffs/${id}`,'GET',hh,0,65536],
 ...['decide','handoff','result','verify','resolve'].map(k=>[`/inbox-handoffs/${id}/${k}`,'POST',hh,8192,16384]),
 ...['propose','resolve'].map(k=>[`/workspaces/${id}/inbox-handoffs/${k}`,'POST',hh,8192,16384]),
];

test('admits exactly the current Inbox and handoff methods with route-specific input/output/15s budgets',()=>{
 for(const [path,method,header,input,output] of routes){assert.equal(permittedAuthenticatedApiPath(origin+path,method),path);assert.deepEqual(connectorApiRoute(path,method),{header,input,output,seconds:15,strictResponse:true,errorOutput:2048});}
 assert.equal(permittedAuthenticatedApiPath(origin+'/provider-team/identity','GET'),'/provider-team/identity');
 for(const [path,method] of [...routes.map(([p,m])=>[p,m==='GET'?'POST':'GET']),['/inbox/ingest','POST'],['/inbox/grants','POST'],[`/inbox/${id}/read`,'POST'],[`/inbox/${id}/sources/${id}`,'POST'],[`/inbox-handoffs/${id}/propose`,'POST'],[`/workspaces/${id}/inbox-handoffs/decide`,'POST'],['/provider-team/identity','POST']])assert.equal(permittedAuthenticatedApiPath(origin+path,method),null);
 for(const path of ['/inbox','/inbox-handoffs','/provider-team/identity'])for(const suffix of ['?','?cursor=x','?actor_id='+id,'/','%2f','/../'+path.slice(1)])assert.equal(permittedAuthenticatedApiPath(origin+path+suffix,'GET'),null);
});

test('requires exact family negotiation and signed-only identity headers before native credential access',async()=>{
 for(const [path,headers] of [['/inbox',inbox],['/inbox-handoffs',handoff],['/provider-team/identity',identity]]){
   for(const bad of [{},Object.fromEntries(Object.entries(headers).map(([k,v])=>[k,v+', '+v])),{...headers,'X-Cosmas-Vendor-Contract':'1'},{...headers,'X-Actor-Principal-Id':id},{...headers,Authorization:'Bearer invented'}]){
     const session=auth(),response=await proxy(request(path,'GET',bad),session,()=>assert.fail('denied before network'));
     assert.ok([401,426].includes(response.status));assert.deepEqual(session.counts(),{reads:0,tokens:0});
   }
 }
 for(const h of [{'X-Cosmas-Team-Contract':'1','X-Cosmas-Draft-Recovery':'2'},{'X-Cosmas-Team-Contract':'2'},{'X-Cosmas-Team-Contract':'2','X-Cosmas-Draft-Recovery':'1'}])assert.equal((await proxy(request('/provider-team/identity','GET',h),auth(),()=>assert.fail())).status,426);
});

test('leaves every new private route unavailable through the retained raw synthetic transport',async()=>{
 for(const [path,method] of [...routes,['/provider-team/identity','GET']]){
   assert.equal(syntheticPath(origin+path,method),null);
   assert.equal((await syntheticProxy(request(path,method,{},method==='POST'?'{}':undefined),()=>assert.fail('no synthetic upstream'))).status,404);
 }
});

test('preserves actual previously signed identity, Inbox and handoff bytes through exact fresh-token transport',async()=>{
 const account=fixture('account-identity/actual-account-identity-http.json'),source=fixture('inbox/actual-inbox-process.json'),work=fixture('inbox-handoff/actual-signed-process.json');
 for(const [path,headers,body,status] of [['/provider-team/identity',identity,account.owner.body,200],['/provider-team/identity',identity,account.staff.body,200],['/inbox',inbox,source.catalog,200],[`/inbox/${id}/history`,inbox,source.history,200],[`/inbox-handoffs/${id}/resolve`,handoff,work.vectors[0],200]]){
   const method=path.endsWith('/resolve')?'POST':'GET',wire=JSON.stringify(body),session=auth();let calls=0;
   const result=await proxy(request(path,method,headers,method==='POST'?'{}':undefined),session,async(url,o)=>{calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(o.headers.Authorization,'Bearer invented.local.token');assert.equal(o.headers['X-Cosmas-Desktop-Session'],undefined);for(const [k,v] of Object.entries(headers))assert.equal(o.headers[k],v);return json(wire,status,{'Content-Length':String(Buffer.byteLength(wire)),'Set-Cookie':'withheld'});});
   assert.equal(await result.text(),wire);assert.equal(calls,1);assert.equal(result.headers.get('Set-Cookie'),null);assert.deepEqual(session.counts(),{reads:2,tokens:1});
 }
});

test('enforces each new successful-response ceiling and the 2KiB error ceiling',async()=>{
 for(const [path,method,header,_input,maximum] of routes.filter(([,m])=>m==='GET')){
   assert.equal((await proxy(request(path,method,{[header]:'1'}),auth(),async()=>json('x'.repeat(maximum)))).status,200);
   assert.equal((await proxy(request(path,method,{[header]:'1'}),auth(),async()=>json('x'.repeat(maximum+1)))).status,503);
   assert.equal((await proxy(request(path,method,{[header]:'1'}),auth(),async()=>json('x'.repeat(2049),409))).status,503);
 }
 assert.equal((await proxy(request('/provider-team/identity','GET',identity),auth(),async()=>json('x'.repeat(1024)))).status,200);
 assert.equal((await proxy(request('/provider-team/identity','GET',identity),auth(),async()=>json('x'.repeat(1025)))).status,503);
});

test('bounds exact UTF8 command bytes and rejects malformed JSON before acquiring a token',async()=>{
 for(const [path,headers] of [[`/inbox/${id}/triage`,inbox],[`/workspaces/${id}/inbox-handoffs/propose`,handoff]]){
   const body='"'+'é'.repeat(4095)+'"';assert.equal(Buffer.byteLength(body),8192);
   assert.equal((await proxy(request(path,'POST',headers,body),auth(),async()=>json())).status,200);
   for(const bad of [body+' ','{']){const session=auth();assert.equal((await proxy(request(path,'POST',headers,bad),session,()=>assert.fail())).status,503);assert.equal(session.counts().tokens,0);}
 }
});

test('rejects encoded, mismatched-length and redirected new responses without disclosing private bytes',async()=>{
 for(const [path,headers] of [['/inbox',inbox],['/inbox-handoffs',handoff],['/provider-team/identity',identity]]){
   for(const bad of [{'Content-Encoding':'gzip'},{'Content-Length':'1'},{'Content-Length':'01'}]){const response=await proxy(request(path,'GET',headers),auth(),async()=>json('{"private":"do not disclose"}',200,bad));assert.equal(response.status,502);assert.doesNotMatch(await response.text(),/do not disclose/);}
   const response=await proxy(request(path,'GET',headers),auth(),async()=>{const r=json('{"private":"hidden"}');Object.defineProperty(r,'redirected',{value:true});return r;});assert.equal(response.status,502);
 }
});

test('retains generic authority denial even when upstream identity denial metadata is malformed',async()=>{
 for(const status of [401,403,404]){const response=await proxy(request('/provider-team/identity','GET',identity),auth(),async()=>json('x'.repeat(1100),status,{'Content-Encoding':'gzip'}));assert.equal(response.status,status);assert.doesNotMatch(await response.text(),/xxx/);}
});

test('all new 15s deadlines include pending credentials and forbid late dispatch',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 for(const [path,headers] of [['/inbox',inbox],['/inbox-handoffs',handoff],['/provider-team/identity',identity]]){
   let release;const session=auth();session.getToken=()=>new Promise(r=>{release=r;});const pending=proxy(request(path,'GET',headers),session,()=>assert.fail('no late dispatch'));
   await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,504);release('invented.local.token');await tick();
 }
});

test('clears a dispatched response on session loss and cancels its late private body without retry',async()=>{
 const session=auth();let release,cancelled=0,calls=0;
 const pending=proxy(request('/inbox','GET',inbox),session,()=>{calls++;return new Promise(r=>{release=r;});});
 await tick();session.revoke();assert.equal((await pending).status,401);
 release(new Response(new ReadableStream({cancel(){cancelled++;}}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));await tick();assert.equal(cancelled,1);assert.equal(calls,1);
});

test('returns a lost command response without retry and preserves a later explicit exact resolver body',async()=>{
 const command=`/inbox-handoffs/${id}/handoff`,resolve=`/inbox-handoffs/${id}/resolve`,original='{"invented":"retained original command"}',query='{"command_kind":"handoff","idempotency_key":"retained-original-key","request_sha256":"'+'a'.repeat(64)+'"}';
 const calls=[];const dropped=await proxy(request(command,'POST',handoff,original),auth(),async(url,o)=>{calls.push([url,new TextDecoder().decode(o.body)]);throw Error('Owned simulated response lost after dispatch');});
 assert.equal(dropped.status,503);assert.deepEqual(calls,[['http://127.0.0.1:8046'+command,original]]);
 const proof=JSON.stringify(fixture('inbox-handoff/actual-signed-process.json').vectors[0]);
 const recovered=await proxy(request(resolve,'POST',handoff,query),auth(),async(url,o)=>{calls.push([url,new TextDecoder().decode(o.body)]);return json(proof);});
 assert.equal(await recovered.text(),proof);assert.deepEqual(calls,[['http://127.0.0.1:8046'+command,original],['http://127.0.0.1:8046'+resolve,query]]);
});

test('keeps the whole 15s budget while reading a stalled private response and after caller cancellation',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 let cancelled=0;const stalled=()=>new Response(new ReadableStream({pull(){return new Promise(()=>{});},cancel(){cancelled++;}}),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 const pending=proxy(request('/provider-team/identity','GET',identity),auth(),async()=>stalled());await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,504);assert.equal(cancelled,1);
 const abort=new AbortController();const second=proxy(request('/inbox-handoffs','GET',handoff,undefined,abort.signal),auth(),async()=>stalled());await tick();abort.abort();assert.equal((await second).status,503);assert.equal(cancelled,2);
});

test('direct local adapter preserves new response length/encoding for the main-process validator without opening a socket',async()=>{
 for(const [path,headers] of [['/inbox',inbox],['/inbox-handoffs',handoff],['/provider-team/identity',identity]]){
   let endpoint;const result=await local('http://127.0.0.1:8046'+path,{method:'GET',headers},(options,reply)=>{
     endpoint=options;const req=new EventEmitter();req.write=()=>assert.fail('GET body');req.end=()=>{const res=new PassThrough();res.statusCode=200;res.headers={'content-type':'application/json','cache-control':'no-store','content-length':'2','content-encoding':'gzip','set-cookie':'withheld'};reply(res);res.end('{}');};return req;
   });
   assert.equal(endpoint.host,'127.0.0.1');assert.equal(endpoint.port,8046);assert.equal(endpoint.agent,false);assert.equal(result.headers.get('content-length'),'2');assert.equal(result.headers.get('content-encoding'),'gzip');assert.equal(result.headers.get('set-cookie'),null);assert.equal(await result.text(),'{}');
 }
});
