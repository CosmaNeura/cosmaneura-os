import assert from 'node:assert/strict';
import test from 'node:test';
import net from 'node:net';
import {createServer,request as httpRequest} from 'node:http';
import {once} from 'node:events';
import {readFile} from 'node:fs/promises';
import {proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

// This file guards its own sockets even when invoked outside the full guarded
// qualification runner. Only this process's fresh loopback listener is allowed.
function guardNetwork(){
  const listen=net.Server.prototype.listen,connect=net.Socket.prototype.connect,ports=new Set();
  const options=args=>{const a=Array.isArray(args[0])?args[0]:args;return typeof a[0]==='object'&&a[0]!==null?a[0]:{port:a[0],host:typeof a[1]==='string'?a[1]:'localhost'};};
  net.Server.prototype.listen=function(...args){
    const value=options(args);assert.equal(value.port,0,'Only ephemeral listeners');assert.equal(value.host,'127.0.0.1','Only loopback listeners');
    this.once('listening',()=>{const port=this.address().port;ports.add(port);this.once('close',()=>ports.delete(port));});
    return Reflect.apply(listen,this,args);
  };
  net.Socket.prototype.connect=function(...args){
    const value=options(args);
    if((value.host??value.hostname)!=='127.0.0.1'||!ports.has(Number(value.port)))throw Error('Unowned test socket denied');
    return Reflect.apply(connect,this,args);
  };
  return()=>{net.Server.prototype.listen=listen;net.Socket.prototype.connect=connect;};
}

test('membership retirement transports actual backend vectors only through an owned guarded ephemeral socket',async t=>{
  const restore=guardNetwork();let server;
  try{
    assert.throws(()=>httpRequest({host:'127.0.0.1',port:8046,path:'/workspaces'}),/Unowned test socket denied/);
    const fixture=JSON.parse(await readFile(new URL('../../web/src/__fixtures__/membership/actual-membership-retirement-http.json',import.meta.url),'utf8'));
    assert.equal(fixture.external_operations_created,0);assert.equal(fixture.retired.outcome,'retired');assert.equal(fixture.retired.effect,null);
    const id='00000000-0000-4000-8000-000000000001',header='X-Cosmas-Membership-Contract';
    const base=`/workspaces/${fixture.scope.workspace_id}/membership-work`,retire=base+'/retire';
    const winning={command_kind:'propose',request:fixture.fresh_request,request_sha256:fixture.fresh_receipt.request_sha256};
    const resolver={command_kind:fixture.retired.command_kind,idempotency_key:fixture.retired.idempotency_key,request_sha256:fixture.retired.request_sha256};
    const seen=[];let mode='normal',entered;
    server=createServer(async(req,res)=>{
      const chunks=[];for await(const chunk of req)chunks.push(chunk);
      const row={path:req.url,method:req.method,headers:req.headers,body:Buffer.concat(chunks)};seen.push(row);
      if(mode==='hold'){entered?.();return;}
      if(mode==='lostreply'){res.destroy();return;}
      if(mode==='redirect'){res.writeHead(302,{Location:'https://outside.example.invalid/never-requested'});res.end();return;}
      res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'invented=withheld'});
      if(mode==='oversize'){res.write('"'+'x'.repeat(4096));res.end('x'.repeat(4096)+'"');return;}
      const body=JSON.parse(row.body.toString('utf8'));let reply;
      if(req.url===retire){
        if(body.request.idempotency_key===winning.request.idempotency_key){assert.deepEqual(body,winning);reply=fixture.fresh_receipt;}
        else{assert.deepEqual(body,fixture.retire_request);reply=fixture.retired;}
      }else if(req.url===base+'/resolve'){assert.deepEqual(body,resolver);reply=fixture.resolved;}
      else{assert.equal(req.url,base);assert.deepEqual(body,fixture.old_request);reply=fixture.late_original;}
      res.end(JSON.stringify(reply));
    });
    server.listen(0,'127.0.0.1');await once(server,'listening');const port=server.address().port;assert.notEqual(port,8046);
    let sockets=0;
    const transport=(url,options)=>local(url,options,(address,callback)=>{
      sockets++;assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);assert.equal(address.agent,false);
      return httpRequest({...address,port},callback);
    });
    function auth(){let state={phase:'ready',revision:id,identity:{userId:'invented',sessionId:'invented',organizationId:'invented'}};const listeners=new Set();return {getState:async()=>state,snapshot:()=>state,getToken:async()=>'invented.local.token',subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},revoke(){state={phase:'signedOut',revision:id,identity:null};for(const fn of listeners)fn(state);}};}
    const request=(path=retire,body=JSON.stringify(fixture.retire_request),extra={},signal)=>new Request('app://cosmas/api'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':id,[header]:'1',...extra},body,signal});
    await t.test('preserves exact typed wrapper and retired receipt with no renderer identity or cookies',async()=>{
      const body=JSON.stringify(fixture.retire_request),response=await proxy(request(retire,body),auth(),transport);
      assert.equal(response.status,200);assert.deepEqual(await response.json(),fixture.retired);assert.equal(sockets,1);
      assert.equal(seen[0].method,'POST');assert.equal(seen[0].path,retire);assert.deepEqual(seen[0].body,Buffer.from(body));
      assert.equal(seen[0].headers[header.toLowerCase()],'1');assert.equal(seen[0].headers.authorization,'Bearer invented.local.token');assert.equal(seen[0].headers['x-cosmas-desktop-session'],undefined);assert.equal(response.headers.get('set-cookie'),null);
    });
    await t.test('preserves the recorded response variant when the original command won',async()=>{
      const response=await proxy(request(retire,JSON.stringify(winning)),auth(),transport);assert.equal(response.status,200);assert.deepEqual(await response.json(),fixture.fresh_receipt);assert.equal(fixture.fresh_receipt.outcome,'recorded');
    });
    await t.test('existing resolve and explicitly tested late-original routes preserve the retired union',async()=>{
      for(const [path,body,expected]of [[base+'/resolve',resolver,fixture.resolved],[base,fixture.old_request,fixture.late_original]]){
        const before=sockets,response=await proxy(request(path,JSON.stringify(body)),auth(),transport);assert.equal(response.status,200);assert.equal(sockets,before+1);assert.deepEqual(await response.json(),expected);
      }
    });
    await t.test('a lost retirement reply is never automatically resent; explicit resolve returns retained receipt bytes',async()=>{
      mode='lostreply';const before=sockets,start=seen.length;
      assert.equal((await proxy(request(),auth(),transport)).status,503);assert.equal(sockets,before+1);
      mode='normal';const response=await proxy(request(base+'/resolve',JSON.stringify(resolver)),auth(),transport);
      assert.equal(response.status,200);assert.deepEqual(await response.json(),fixture.resolved);assert.equal(sockets,before+2);assert.deepEqual(seen.slice(start).map(r=>r.path),[retire,base+'/resolve']);
    });
    await t.test('invalid route, negotiation, credentials and oversized wrapper open no socket',async()=>{
      const before=sockets;
      for(const path of [retire+'?cursor=x',base+'/'+id+'/retire',retire+'/extra'])assert.equal((await proxy(request(path),auth(),transport)).status,404);
      assert.equal((await proxy(request(retire,undefined,{'X-Cosmas-Vendor-Contract':'1'}),auth(),transport)).status,426);
      assert.equal((await proxy(request(retire,undefined,{Authorization:'Bearer invented-renderer'}),auth(),transport)).status,401);
      assert.equal((await proxy(request(retire,'"'+'x'.repeat(16383)+'"'),auth(),transport)).status,503);assert.equal(sockets,before);
    });
    await t.test('chunked receipt beyond 8 KiB is withheld without retry or partial bytes',async()=>{
      mode='oversize';const before=sockets,response=await proxy(request(),auth(),transport);assert.equal(response.status,503);assert.equal(sockets,before+1);assert.ok((await response.text()).length<256);
    });
    await t.test('redirect cannot open a second socket or leave the owned listener',async()=>{
      mode='redirect';const before=sockets;assert.equal((await proxy(request(),auth(),transport)).status,503);assert.equal(sockets,before+1);
    });
    await t.test('caller cancellation and sign-out withhold held responses without replay',async()=>{
      mode='hold';let accepted=new Promise(resolve=>{entered=resolve;});const controller=new AbortController(),before=sockets;
      let pending=proxy(request(retire,undefined,{},controller.signal),auth(),transport);await accepted;controller.abort();assert.equal((await pending).status,503);assert.equal(sockets,before+1);
      accepted=new Promise(resolve=>{entered=resolve;});const session=auth();pending=proxy(request(),session,transport);await accepted;session.revoke();assert.equal((await pending).status,401);assert.equal(sockets,before+2);
    });
  }finally{
    if(server){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
    restore();
  }
});
