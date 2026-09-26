import test from 'node:test';
import assert from 'node:assert/strict';
import {connectorApiRoute,CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath} from './workspace-auth-proxy.mjs';
test('admits only the bounded companion connection route with its own header',()=>{
  const path='/connections/cosmaneura/read';
  assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'POST'),path);
  assert.deepEqual(connectorApiRoute(path,'POST'),{header:'X-Cosmas-Connection-Contract',input:2048,output:69632,seconds:35,strictResponse:true,errorOutput:2048});
  assert.ok(CONNECTOR_HEADERS.includes('X-Cosmas-Connection-Contract'));
  for(const method of ['GET','DELETE','PUT'])assert.equal(connectorApiRoute(path,method),null);
  for(const ending of ['?tenant=anything','/','/connect','?'])assert.equal(connectorApiRoute(path+ending,'POST'),null);
});
