import assert from 'node:assert/strict';
import test from 'node:test';
import {createServer,request as httpRequest} from 'node:http';
import {once} from 'node:events';
import {connectorApiRoute} from './connector-api-routes.mjs';
import {fetchLocalAuthenticatedWorkspace} from './local-auth-http.mjs';
import {proxyAuthenticatedWorkspaceRequest as proxy,permittedAuthenticatedApiPath} from './workspace-auth-proxy.mjs';
const id='00000000-0000-4000-8000-000000000084',path='/practice-access/compatibility';
const ready={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};
const auth={getState:async()=>ready,snapshot:()=>ready,getToken:async()=> 'invented.local.token',subscribe:()=>()=>{}};
const request=(protocol='1',target=path)=>new Request('app://cosmas/api'+target,{headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,'X-Cosmas-Workspace-Protocol':protocol,...(target===path?{'X-Cosmas-Practice-Access-Contract':'1'}:{})}});
const response=(protocol='1',size=2)=>new Response(' '.repeat(size),{headers:{'Content-Type':'application/json','Cache-Control':'no-store',...(protocol===null?{}:{'X-Cosmas-Workspace-Protocol':protocol})}});
test('admits only the exact bounded handshake and forwards the protocol both ways',async()=>{
  assert.deepEqual(connectorApiRoute(path,'GET'),{header:'X-Cosmas-Practice-Access-Contract',input:0,output:4096,seconds:15,strictResponse:true,errorOutput:2048});
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'POST'),null);
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path+'?private=true','GET'),null);
  for(const target of [path,'/workspaces']){
    const result=await proxy(request('1',target),auth,async(url,init)=>{
      assert.equal(url,'http://127.0.0.1:8046'+target);assert.equal(init.headers['X-Cosmas-Workspace-Protocol'],'1');
      assert.equal(init.headers.Authorization,'Bearer invented.local.token');return response();
    });
    assert.equal(result.status,200);assert.equal(result.headers.get('X-Cosmas-Workspace-Protocol'),'1');
  }
});
test('rejects unsupported declarations before credentials or transport and withholds unidentified success',async()=>{
  for(const value of ['2','1, 1',''])assert.equal((await proxy(request(value),{getState:()=>assert.fail()},()=>assert.fail())).status,426);
  for(const value of [null,'2','1, 1'])assert.equal((await proxy(request(),auth,async()=>response(value))).status,426);
  assert.equal((await proxy(request(),auth,async()=>response('1',4097))).status,503);
});

test('actual HTTP metadata survives the desktop transport and proxy without admitting a missing or changed protocol',async()=>{
  let protocol='1';
  const server=createServer((incoming,outgoing)=>{
    assert.equal(incoming.headers['x-cosmas-workspace-protocol'],'1');
    assert.equal(incoming.headers.authorization,'Bearer invented.local.token');
    outgoing.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store',
      'Set-Cookie':'invented=discarded',...(protocol===null?{}:{'X-Cosmas-Workspace-Protocol':protocol})});
    outgoing.end('{"ok":true}');
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');
  const port=server.address().port;
  const transport=(url,options)=>fetchLocalAuthenticatedWorkspace(url,options,(address,callback)=>{
    assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);
    return httpRequest({...address,port},callback);
  });
  try{
    // Exercise both the strict compatibility response and ordinary workspace reads.
    for(const target of [path,'/workspaces']){
      const result=await proxy(request('1',target),auth,transport);
      assert.equal(result.status,200);
      assert.equal(result.headers.get('X-Cosmas-Workspace-Protocol'),'1');
      assert.equal(result.headers.get('Set-Cookie'),null);
      assert.deepEqual(await result.json(),{ok:true});
    }
    for(protocol of [null,'2',['1','1']]){
      const result=await proxy(request(),auth,transport);
      assert.equal(result.status,426);
      assert.equal(result.headers.get('X-Cosmas-Workspace-Protocol'),null);
    }
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
