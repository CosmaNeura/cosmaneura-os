import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {render, SECRET_NAMES} from './render.mjs';

import {candidate} from './fixtures.mjs';
import {resolveBetaFeatureProfile} from '../../../clients/shared/beta-feature-profile.mjs';

test('two reserved Boxes preserve canonical UUID5, isolated Org/routing and existing web profile',()=>{
  const files=render(candidate()),d=files['deployment.json'];
  assert.equal(d.deployed,false);assert.equal(d.workspace_ready,false);
  for(const slot of ['a','b']) {
    const p=d.practices[slot],env=p.api_env,web=files[`web-${slot}.env.json`];
    assert.equal(env.BETA_BOX_ID,p.plan.box_id);assert.equal(env.CLERK_ORGANIZATION_ID,p.plan.organization_id);
    assert.equal(env.CLERK_SESSION_POLICY,'enrollment_default');assert.equal(env.CLERK_AUDIENCE,'');
    assert.equal(env.WORKSPACE_ENROLLMENT_ACCOUNT_ORIGIN,'https://onboarding.staging.cosmas.ai');
    assert.equal(env.CORS_ALLOWED_ORIGINS,`${d.account.app_origin},${p.web_origin}`);
    assert.equal(env.WORKSPACE_ENROLLMENT_MANAGED,'true');assert.equal(env.DATA_MODE,'synthetic');
    assert.equal(web.VITE_API_BASE,p.plan.api_origin);assert.equal(web.VITE_WORKSPACE_ORGANIZATION_ID,p.plan.organization_id);
    assert.equal(web.VITE_COSMANEURA_WEB_ORIGIN,'');assert.equal(web.VITE_WORKSPACE_CAPTURE_MODE,'disabled');
    assert.equal(resolveBetaFeatureProfile(web).manifest.organizationId,p.plan.organization_id);
    assert.equal(web.VITE_ENROLLMENT_ENABLED,undefined);
    assert.equal(createHash('sha256').update(JSON.stringify(files[`owner-${slot}.json`],null,2)+'\n').digest('hex'),p.owner_manifest_sha256);
    assert(!Object.keys(env).some(name=>name.includes('SECRET')||name==='DATABASE_URL'||name.includes('CORE')));
  }
  assert.notEqual(d.practices.a.plan.box_id,d.practices.b.plan.box_id);
});

test('Central US foundation preserves the same owned two-practice origins and closed gates',()=>{
  const baseline=render(candidate()),input=candidate();input.foundation.location='centralus';
  const files=render(input),d=files['deployment.json'];
  assert.equal(d.foundation.location,'centralus');
  assert.deepEqual({...d,foundation:{...d.foundation,location:'eastus2'}},baseline['deployment.json']);
  for(const slot of ['a','b']) {
    assert.deepEqual(files[`web-${slot}.env.json`],baseline[`web-${slot}.env.json`]);
    assert.deepEqual(files[`owner-${slot}.json`],baseline[`owner-${slot}.json`]);
  }
  assert.equal(d.deploy_workloads,false);assert.equal(d.bind_domains,false);
  assert.equal(d.deployed,false);assert.equal(d.workspace_ready,false);
});

test('foundation region is limited to exact East US 2 or Central US values',()=>{
  for(const location of ['eastus','westus2','canadacentral','westeurope','centralus ','CENTRALUS',null]) {
    const input=candidate();input.foundation.location=location;assert.throws(()=>render(input),/independent staging foundation required/);
  }
});

test('production, foreign destinations, stale release and colliding immutable practice rejected',()=>{
  for(const mutate of [x=>x.environment='production',x=>x.synthetic_only=false,x=>x.account.api_origin='https://api.cosmas.ai',x=>x.practices[0].plan.api_origin='https://other.staging.cosmas.ai',x=>x.practices[0].plan.box_id=x.practices[1].plan.box_id,x=>x.practices[0].plan.source_commit='f'.repeat(40),x=>x.practices[1].plan.organization_id=x.practices[0].plan.organization_id,x=>x.foundation.vnet_id=x.foundation.vnet_id.replace('rg-cosmabot-enrollment-staging-mock1234','rg-existing-beta')]) {
    const input=candidate();mutate(input);assert.throws(()=>render(input));
  }
  for(const app_origin of ['https://staging.cosmas.ai','https://accounts.staging.cosmas.ai']) {
    const input=candidate();input.account.app_origin=app_origin;assert.throws(()=>render(input));
  }
  for(const host of ['practice-a.nested.staging.cosmas.ai','enrollment-api.staging.cosmas.ai','api.staging.cosmas.ai']) {
    const input=candidate();input.practices[0].plan.workspace_url=`https://${host}/chief`;input.practices[0].plan.api_origin=`https://api.${host}`;assert.throws(()=>render(input));
  }
});

test('no runtime or reservation starts before qualified migration and reference-only per-Box credentials',()=>{
  const beforeBuild=candidate();beforeBuild.practices[0].web_image=null;
  beforeBuild.release.job_image=null;
  assert.equal(render(beforeBuild)['deployment.json'].practices.a.web_image,null);
  beforeBuild.deploy_workloads=true;assert.throws(()=>render(beforeBuild));
  const input=candidate();input.deploy_workloads=true;assert.throws(()=>render(input));
  input.deploy_workloads=false;input.create_migration_jobs=true;assert.throws(()=>render(input));
  for(const p of input.practices) p.secret_references=Object.fromEntries(Object.entries(SECRET_NAMES).map(([name,secret])=>[name,`https://kv-cews-${input.namespace}-${p.key}.vault.azure.net/secrets/${secret}/${'e'.repeat(32)}`]));
  assert.equal(render(input)['deployment.json'].create_migration_jobs,true);
  input.create_owner_reservation_jobs=true;assert.throws(()=>render(input));
  for(const p of input.practices)p.migration_receipt_sha256='f'.repeat(64);
  assert.equal(render(input)['deployment.json'].create_owner_reservation_jobs,true);
  input.deploy_workloads=true;assert.throws(()=>render(input));
  for(const p of input.practices)p.reservation_receipt_sha256='0'.repeat(64);
  assert.equal(render(input)['deployment.json'].workspace_ready,false);
  input.bind_domains=true;assert.throws(()=>render(input));
  for(const p of input.practices)p.dns_ownership_qualified=true;
  assert.equal(render(input)['deployment.json'].bind_domains,true);
  input.practices[0].secret_references.DATABASE_URL=input.practices[1].secret_references.DATABASE_URL;
  assert.throws(()=>render(input));
  input.practices[0].secret_references.DATABASE_URL='postgresql://invented:never-live@127.0.0.1/db';assert.throws(()=>render(input));
});
