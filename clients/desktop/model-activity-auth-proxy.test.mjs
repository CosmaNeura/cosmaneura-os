import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import {isModelActivityPath} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath,proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';
import {permittedApiPath as syntheticPath} from './api-proxy.mjs';
const revision='00000000-0000-4000-8000-000000000001',origin='app://cosmas/api';
const headers={'Content-Type':'application/json','X-Cosmas-Desktop-Session':revision,'X-Cosmas-Team-Contract':'2','X-Cosmas-Draft-Recovery':'2'};
const page='/provider-team/activity/attention',cursor='a1'+'a'.repeat(128);
const request=(path=page,more={},method='GET')=>new Request(origin+path,{method,headers:{...headers,...more}});
function auth(){let reads=0,tokens=0;const state={phase:'ready',revision,organizationId:'invented'};return {getState:async()=>{reads++;return {...state};},snapshot:()=>({...state}),getToken:async()=>{tokens++;return 'invented.local.token';},subscribe:()=>()=>{},counts:()=>({reads,tokens}),state};}
const response=(text='{}',status=200,extra={})=>new Response(text,{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});

test('forwards explicit source-time negotiation only on the activity read',async()=>{
 const result=await proxy(request(page,{'X-Cosmas-Activity-Contract':'2'}),auth(),async(_url,options)=>{
  assert.equal(options.headers['X-Cosmas-Activity-Contract'],'2');return response();
 });
 assert.equal(result.status,200);
 for(const path of ['/provider-team/identity','/provider-team']){
  assert.equal((await proxy(request(path,{'X-Cosmas-Activity-Contract':'2'}),auth(),()=>assert.fail('no dispatch'))).status,426);
 }
});

test('only exact readonly activity routes are admitted; synthetic bypass and rewritten paths are denied',()=>{
 for(const path of [page,'/provider-team/activity/recent',page+'/'+cursor]){assert.ok(isModelActivityPath(path));assert.equal(permittedAuthenticatedApiPath(origin+path,'GET'),path);assert.equal(permittedAuthenticatedApiPath(origin+path,'POST'),null);assert.equal(syntheticPath(origin+path,'GET'),null);}
 for(const suffix of ['?','?cursor=x','/','/a1','/'+cursor+'0','/%61'+cursor.slice(1),'/../attention'])assert.equal(permittedAuthenticatedApiPath(origin+page+suffix,'GET'),null);
 for(const path of ['/provider-team/activity','/provider-team/activity/all','/provider-team/activity/attention/resolve'])assert.equal(permittedAuthenticatedApiPath(origin+path,'GET'),null);
});

test('requires Team2 Recovery2 and current native session before token or network access',async()=>{
 for(const change of [{'X-Cosmas-Team-Contract':'1'},{'X-Cosmas-Team-Contract':'2, 2'},{'X-Cosmas-Draft-Recovery':'1'},{'X-Cosmas-Draft-Recovery':''},{'X-Cosmas-Desktop-Session':'bad'},{Authorization:'Bearer invented'},{'X-Cosmas-Vendor-Contract':'1'}]){
  const s=auth();const r=await proxy(request(page,change),s,()=>assert.fail('no dispatch'));
  assert.ok([401,426].includes(r.status));assert.deepEqual(s.counts(),{reads:0,tokens:0});
 }
});

test('exact actual signed page bytes and existing negotiation pass with no new authority',async()=>{
 const data=JSON.parse(readFileSync(new URL('../../web/src/__fixtures__/ai-activity/actual-activity-pages.json',import.meta.url),'utf8'));
 for(const key of ['empty','pending','recent']){
  const body=JSON.stringify(data[key]);const path=key==='recent'?'/provider-team/activity/recent':page;let calls=0;const s=auth();
  const r=await proxy(request(path),s,async(url,options)=>{calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.method,'GET');assert.equal(options.body,undefined);assert.equal(options.headers['X-Cosmas-Team-Contract'],'2');assert.equal(options.headers['X-Cosmas-Draft-Recovery'],'2');assert.equal(options.headers.Authorization,'Bearer invented.local.token');return response(body,200,{'Content-Length':String(Buffer.byteLength(body))});});
  assert.equal(await r.text(),body);assert.equal(calls,1);assert.deepEqual(s.counts(),{reads:2,tokens:1});
 }
});

test('strict 64KiB successful and1KiB error limits preserve explicit authority denials',async()=>{
 assert.equal((await proxy(request(),auth(),async()=>response('x'.repeat(65536)))).status,200);
 assert.equal((await proxy(request(),auth(),async()=>response('x'.repeat(65537)))).status,503);
 assert.equal((await proxy(request(),auth(),async()=>response('x'.repeat(1025),422))).status,503);
 for(const status of [401,403,404]){const r=await proxy(request(),auth(),async()=>response('PRIVATE'.repeat(12000),status,{'Content-Encoding':'gzip'}));assert.equal(r.status,status);assert.doesNotMatch(await r.text(),/PRIVATE/);}
 for(const extra of [{'Content-Length':'1'},{'Content-Length':'01'},{'Content-Encoding':'gzip'}])assert.equal((await proxy(request(),auth(),async()=>response('{"private":"hidden"}',200,extra))).status,502);
});

test('revoked native revision after response suppresses private activity',async()=>{
 const s=auth();const r=await proxy(request(),s,async()=>{s.state.revision='00000000-0000-4000-8000-000000000002';return response('{"private":"hidden"}');});
 assert.equal(r.status,401);assert.doesNotMatch(await r.text(),/hidden/);
});

test('whole native deadline is15s and aborts a pending credential before dispatch',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});const s=auth();s.getToken=()=>new Promise(()=>{});
 const promise=proxy(request(),s,()=>assert.fail('late credential must not dispatch'));
 await new Promise(r=>setImmediate(r));t.mock.timers.tick(15000);const r=await promise;
 assert.equal(r.status,504);t.mock.timers.reset();
});

test('direct HTTP family rejects malformed routes/negotiation before socket and retains strict headers',async()=>{
 for(const [path,method,h]of[[page,'POST',headers],[page+'?x=1','GET',headers],[page,'GET',{}],[page+'/bad','GET',headers]])await assert.rejects(local('http://127.0.0.1:8046'+path,{method,headers:h},()=>assert.fail()));
 const result=await local('http://127.0.0.1:8046'+page,{method:'GET',headers},(options,cb)=>{
  assert.equal(options.port,8046);assert.equal(options.path,page);const q=new EventEmitter();q.end=()=>{const stream=new PassThrough();stream.statusCode=200;stream.headers={'content-type':'application/json','cache-control':'no-store','content-length':'2','content-encoding':'gzip'};cb(stream);stream.end('{}');};return q;
 });assert.equal(result.headers.get('Content-Length'),'2');assert.equal(result.headers.get('Content-Encoding'),'gzip');
});
