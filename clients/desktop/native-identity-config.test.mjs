import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile, writeFile, realpath, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {validateOperationalNativeIdentity, operationalNativeAuthSettings, operationalNativeBundle} from './native-identity-config.mjs';
import {prepareDesktopState} from './installation-state.mjs';

const identity = {version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.invalid',
  frontendOrigin:'https://clerk.example.invalid',publishableKey:'pk_live_'+btoa('clerk.example.invalid$'),
  organizationId:'org_invented_beta',audience:'cosmas-os-beta'};
const config = {mode:'hosted-beta-authenticated',dataMode:'authorized_beta',apiOrigin:identity.apiOrigin,nativeIdentity:identity,
  installation:{version:1,profile:'beta',bundleIdentifier:'com.cosmasos.beta.desktop',storageGeneration:1,
    electronVersion:'43.4.1',rendererPartition:'persist:cosmasos-operational-beta',authHelperBundleIdentifier:'com.cosmasos.beta.desktop.auth'}};

test('operational identity binds the decoded production frontend, client and API',()=>{
  assert.deepEqual(validateOperationalNativeIdentity(identity,'desktop',identity.apiOrigin),identity);
  assert.equal(operationalNativeBundle('desktop'),'com.cosmasos.beta.desktop.auth');
  assert.equal(operationalNativeBundle('apple'),'com.cosmasos.beta.ios');
  assert.equal(operationalNativeAuthSettings(identity).enabled,true);
  for (const changed of [
    {...identity,client:'apple'}, {...identity,apiOrigin:'https://other.example.invalid'},
    {...identity,publishableKey:'pk_test_'+btoa('clerk.example.invalid$')},
    {...identity,frontendOrigin:'https://other.example.invalid'},
    {...identity,frontendOrigin:'https://clerk.example.invalid:443'},
    {...identity,publishableKey:'pk_live_'+btoa('invented.clerk.accounts.dev$'),frontendOrigin:'https://invented.clerk.accounts.dev'},
    {...identity,publishableKey:identity.publishableKey+' '}, {...identity,audience:'with spaces'},
    {...identity,organizationId:''}, {...identity,secret:'forbidden'}, {...identity,version:true},
  ]) assert.throws(()=>validateOperationalNativeIdentity(changed,'desktop',identity.apiOrigin));
});

test('stable operational installation preserves data and refuses changed account/backend or synthetic storage',async()=>{
  const base = await realpath(await mkdtemp(join(tmpdir(),'cosmas-native-identity-')));
  const dir = await prepareDesktopState(config,base,'43.4.1');
  assert.equal(dir,join(base,'CosmasOS Beta','com.cosmasos.beta.desktop'));
  await writeFile(join(dir,'retained-encrypted-draft'), 'invented ciphertext');
  const marker = await readFile(join(dir,'cosmas-installation.json'),'utf8');
  assert.equal(await prepareDesktopState({...config,appVersion:'0.9.0'},base,'43.4.1'),dir);
  for (const changed of [
    {...config,nativeIdentity:{...identity,organizationId:'org_other'}},
    {...config,apiOrigin:'https://other.example.invalid',nativeIdentity:{...identity,apiOrigin:'https://other.example.invalid'}},
    {...config,dataMode:'synthetic'}, {...config,installationRoot:base},
    {...config,installation:{...config.installation,bundleIdentifier:'com.cosmasos.synthetic.desktop.w60'}},
    {...config,installation:{...config.installation,rendererPartition:'persist:cosmasos-authenticated-local'}},
    {...config,nativeIdentity:undefined},
  ]) await assert.rejects(prepareDesktopState(changed,base,'43.4.1'));
  assert.equal(await readFile(join(dir,'cosmas-installation.json'),'utf8'),marker);
  assert.equal(await readFile(join(dir,'retained-encrypted-draft'),'utf8'),'invented ciphertext');
});

test('synthetic data with operational identity preserves custody and rejects mode/account changes',async t=>{
  const base=await realpath(await mkdtemp(join(tmpdir(),'cosmas-operational-synthetic-')));
  t.after(()=>rm(base,{recursive:true,force:true}));
  const synthetic={...config,dataMode:'synthetic'};
  const directory=await prepareDesktopState(synthetic,base,'43.4.1');
  const marker=await readFile(join(directory,'cosmas-installation.json'),'utf8');
  assert.equal(JSON.parse(marker).dataMode,'synthetic');
  assert.match(JSON.parse(marker).identityBinding,/^[0-9a-f]{64}$/);
  await writeFile(join(directory,'retained-draft'),'invented private draft');
  assert.equal(await prepareDesktopState(synthetic,base,'43.4.1'),directory);
  for(const changed of [
    {...synthetic,dataMode:'authorized_beta'}, {...synthetic,dataMode:undefined},
    {...synthetic,nativeIdentity:undefined}, {...synthetic,nativeIdentity:null},
    {...synthetic,nativeIdentity:{...identity,organizationId:'org_other'}},
    {...synthetic,nativeIdentity:{...identity,apiOrigin:'https://other.example.invalid'}},
    {...synthetic,nativeIdentity:{...identity,publishableKey:'pk_test_invented'}},
  ]) await assert.rejects(prepareDesktopState(changed,base,'43.4.1'));
  assert.equal(await readFile(join(directory,'cosmas-installation.json'),'utf8'),marker);
  assert.equal(await readFile(join(directory,'retained-draft'),'utf8'),'invented private draft');
});
