import assert from 'node:assert/strict';
import test from 'node:test';
import {once} from 'node:events';
import {createServer, request as httpRequest} from 'node:http';
import {connectorApiRoute, CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath, proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

const id = '00000000-0000-4000-8000-000000000051';
const base = `/workspaces/${id}/agent-research`;
const paths = [[base, 'GET', 'X-Cosmas-Research-Contract', 0, 131072, 35],
  [base + `/${id}/review`, 'POST', 'X-Cosmas-Research-Contract', 8192, 131072, 35],
  ['/connections/plugins', 'GET', 'X-Cosmas-Connection-Contract', 0, 1048576, 15]];
const tick = () => new Promise(resolve => setImmediate(resolve));
const sized = size => '"' + 'x'.repeat(size - 2) + '"';
function auth() {
  let state = {phase:'ready', revision:id, identity:{userId:'invented', sessionId:'invented', organizationId:'invented'}};
  let tokens = 0;
  const listeners = new Set();
  return {getState:async()=>state, snapshot:()=>state, getToken:async()=>{tokens++;return 'invented.current.session';},
    subscribe:callback=>{listeners.add(callback);return()=>listeners.delete(callback);}, count:()=>tokens,
    revoke(){state={phase:'signedOut',revision:id,identity:null};for(const callback of listeners)callback(state);}};
}
function request(path, method, header, body='{}') {
  return new Request('app://cosmas/api' + path, {method,
    headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1'},
    ...(method==='POST'?{body,duplex:'half'}:{})});
}
const response = (content='{}',status=200,extra={})=>new Response(content,{status,
  headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});

test('agent Research review and plugin discovery have exact negotiated methods and bounded plans',()=>{
  for(const [path,method,header,input,output,seconds] of paths){
    assert.deepEqual(connectorApiRoute(path,method),{header,input,output,seconds,strictResponse:true,errorOutput:2048});
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),path);
    assert.equal(CONNECTOR_HEADERS.filter(value=>value===header).length,1);
    for(const wrong of ['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','get'])if(wrong!==method)
      assert.equal(connectorApiRoute(path,wrong),null);
    for(const suffix of ['?','?bot='+id,'?url=https://outside.invalid','/','/search','/execute']){
      assert.equal(connectorApiRoute(path+suffix,method),null);
      assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path+suffix,method),null);
    }
    for(const url of ['app://outside/api'+path,'https://outside.invalid'+path,'app://cosmas/api'+path+'#fragment',
      'app://cosmas/api'+path.replace('/workspaces','/extra/../workspaces'),
      'app://cosmas/api'+path.replace('agent-research','%61gent-research'),
      'app://cosmas/api'+path.replace('connections','%63onnections')])
      if(url!=='app://cosmas/api'+path)assert.equal(permittedAuthenticatedApiPath(url,method),null);
  }
  for(const path of [base+'/review',base+'/'+id,base+'/'+id+'/review/resolve',base.replace(id,'NOT-A-UUID')])
    assert.equal(connectorApiRoute(path,'POST'),null);
});

test('actual session proxy rejects missing or mixed contracts before credentials',async()=>{
  for(const [path,method,header] of paths){
    for(const value of [null,'','2','1, 1']){
      const session=auth(),req=request(path,method,header);
      if(value===null)req.headers.delete(header);else req.headers.set(header,value);
      assert.equal((await proxy(req,session,()=>assert.fail('no dispatch'))).status,426);
      assert.equal(session.count(),0);
    }
    for(const other of CONNECTOR_HEADERS.filter(value=>value!==header)){
      const session=auth(),req=request(path,method,header);req.headers.set(other,'1');
      assert.equal((await proxy(req,session,()=>assert.fail('no mixed contract'))).status,426);
      assert.equal(session.count(),0);
    }
  }
});

test('actual session proxy pins destination and human review bytes without forwarding renderer identity',async()=>{
  for(const [path,method,header] of paths){
    let calls=0;const body=JSON.stringify({revision_id:id,payload_hash:'a'.repeat(64),public_query_confirmed:true});
    const req=request(path,method,header,body);req.headers.set('X-Renderer-Url','https://outside.invalid');
    const result=await proxy(req,auth(),async(url,options)=>{
      calls++;assert.equal(url,'http://127.0.0.1:8046'+path);assert.equal(options.headers[header],'1');
      assert.equal(options.headers.Authorization,'Bearer invented.current.session');
      assert.equal(options.headers['X-Cosmas-Desktop-Session'],undefined);assert.equal(options.headers['X-Renderer-Url'],undefined);
      assert.equal(options.redirect,'error');assert.equal(options.credentials,'omit');
      assert.deepEqual(options.body,method==='POST'?new TextEncoder().encode(body):undefined);
      return response('{}',200,{'Set-Cookie':'private=never-forward'});
    });
    assert.equal(result.status,200);assert.equal(calls,1);assert.equal(result.headers.get('set-cookie'),null);
  }
});

test('request and response budgets bound discovery and exact Research review',async()=>{
  const [path,method,header,input]=paths[1];
  assert.equal((await proxy(request(path,method,header,sized(input)),auth(),async()=>response())).status,200);
  for(const body of [sized(input+1),'{']){
    const session=auth();assert.equal((await proxy(request(path,method,header,body),session,()=>assert.fail('no request'))).status,503);
    assert.equal(session.count(),0);
  }
  for(const [target,verb,family,,output] of paths){
    assert.equal((await proxy(request(target,verb,family),auth(),async()=>response(sized(output)))).status,200);
    assert.equal((await proxy(request(target,verb,family),auth(),async()=>response(sized(output+1)))).status,503);
    assert.equal((await proxy(request(target,verb,family),auth(),async()=>response(sized(2049),409))).status,503);
    assert.equal((await proxy(request(target,verb,family),auth(),async()=>response('{}',200,{'Cache-Control':'public'}))).status,502);
  }
});

test('sign-out during reviewed Research response cancels private disclosure without retry',async()=>{
  const session=auth();let calls=0,cancelled=0;
  const pending=proxy(request(base,'GET',paths[0][2]),session,async()=>{calls++;return response(new ReadableStream({
    pull(){return new Promise(()=>{});},cancel(){cancelled++;}}));});
  await tick();session.revoke();assert.equal((await pending).status,401);assert.equal(calls,1);assert.equal(cancelled,1);
});

test('Research deadline fences late credentials before dispatch',async t=>{
  t.mock.timers.enable({apis:['setTimeout']});
  const session=auth();let release,calls=0;session.getToken=()=>new Promise(resolve=>{release=resolve;});
  const pending=proxy(request(base,'GET',paths[0][2]),session,async()=>{calls++;return response();});
  await tick();t.mock.timers.tick(35000);assert.equal((await pending).status,504);
  release('invented.current.session');await tick();assert.equal(calls,0);
});

test('new catalog and reviewed Research routes exchange exact bytes through owned loopback sockets',async()=>{
  const seen=[];
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req)chunks.push(chunk);
    seen.push({method:req.method,path:req.url,headers:req.headers,body:Buffer.concat(chunks)});
    res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});
    res.end(req.url==='/connections/plugins'?JSON.stringify({tools:[],padding:'x'.repeat(5000)}):'{}');
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');const port=server.address().port;
  const transport=(url,options)=>local(url,options,(address,callback)=>{
    assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);
    return httpRequest({...address,port},callback);
  });
  try{
    const body=JSON.stringify({revision_id:id,payload_hash:'a'.repeat(64),public_query_confirmed:true});
    for(const [path,method,header] of paths){
      const result=await proxy(request(path,method,header,body),auth(),transport);
      assert.equal(result.status,200);
      const actual=seen.at(-1);assert.equal(actual.path,path);assert.equal(actual.method,method);
      assert.equal(actual.headers[header.toLowerCase()],'1');assert.equal(actual.headers.authorization,'Bearer invented.current.session');
      assert.equal(actual.headers['x-cosmas-desktop-session'],undefined);
      assert.equal(actual.body.toString(),method==='POST'?body:'');
      if(path==='/connections/plugins')assert.ok((await result.arrayBuffer()).byteLength>4096);
    }
    assert.equal(seen.length,3);
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
