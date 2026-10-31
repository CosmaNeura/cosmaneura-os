import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {render,SECRET_NAMES} from './render.mjs';

export function candidate() {
  const subscription='00000000-0000-4000-8000-000000000001',tenant='00000000-0000-4000-8000-000000000002';
  const rg='rg-cosmabot-enrollment-staging-mock1234',scope=`/subscriptions/${subscription}/resourceGroups/${rg}/providers/`,registry='acrcbotenrstgmock1234.azurecr.io';
  const issuer='https://example-instance.clerk.accounts.dev',key='pk_test_'+Buffer.from('example-instance.clerk.accounts.dev$').toString('base64');
  const source='1'.repeat(40), image='a'.repeat(64);
  return {version:1,environment:'staging',synthetic_only:true,namespace:'mock5678',release_operator_object_id:'00000000-0000-4000-8000-000000000003',
    foundation:{contract_version:'enrollment-foundation.v1',environment:'staging',subscription_id:subscription,tenant_id:tenant,resource_group_name:rg,location:'eastus2',vnet_id:scope+'Microsoft.Network/virtualNetworks/enrollment',container_app_environment_id:scope+'Microsoft.App/managedEnvironments/enrollment',container_registry_id:scope+'Microsoft.ContainerRegistry/registries/acrcbotenrstgmock1234',registry_server:registry,postgres_subnet_id:scope+'Microsoft.Network/virtualNetworks/enrollment/subnets/postgres',private_endpoint_subnet_id:scope+'Microsoft.Network/virtualNetworks/enrollment/subnets/endpoints',vault_private_dns_zone_id:scope+'Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net'},
    account:{app_origin:'https://onboarding.staging.cosmas.ai',api_origin:'https://enrollment-api.staging.cosmas.ai',issuer,publishable_key:key},
    release:{source_commit:source,api_image:`${registry}/cosmabot@sha256:${image}`,job_image:`${registry}/workspace-job@sha256:${'b'.repeat(64)}`},
    practices:['a','b'].map((slot,index)=>({key:slot,
      plan:{practice_id:`10000000-0000-4000-8000-00000000000${index+1}`,box_id:index===0?'8861fcf6-f76a-5b56-afff-aa57711d23f7':'c2b2b51d-79b2-5bdc-ac6c-71031b0fd0af',organization_id:`org_example${slot}`,owner_subject:'user_exampleowner',issuer,api_origin:`https://api.practice-${slot}.staging.cosmas.ai`,workspace_url:`https://practice-${slot}.staging.cosmas.ai/chief`,source_commit:source,image_sha256:image},
      owner_display_name:'Example Owner',practice_display_name:`Example Practice ${slot.toUpperCase()}`,reviewed_by:'Synthetic release reviewer',evidence_ref:`synthetic:practice-${slot}`,web_image:`${registry}/web-${slot}@sha256:${(index===0?'c':'d').repeat(64)}`,secret_references:{},migration_receipt_sha256:null,reservation_receipt_sha256:null,dns_ownership_qualified:false})),
    create_migration_jobs:false,create_owner_reservation_jobs:false,deploy_workloads:false,bind_domains:false};
}

if(process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const dir=new URL('./tests/',import.meta.url);mkdirSync(dir,{recursive:true});
  const input=candidate();
  const write=name=>writeFileSync(new URL(`.generated-${name}.json`,dir),JSON.stringify(render(input)['deployment.json'],null,2)+'\n');
  write('stores');
  for(const p of input.practices)p.secret_references=Object.fromEntries(Object.entries(SECRET_NAMES).map(([name,secret])=>[name,`https://kv-cews-${input.namespace}-${p.key}.vault.azure.net/secrets/${secret}/${'e'.repeat(32)}`]));
  input.create_migration_jobs=true;write('migrate');
  for(const p of input.practices){p.migration_receipt_sha256='f'.repeat(64);p.reservation_receipt_sha256='0'.repeat(64);}
  input.create_owner_reservation_jobs=true;input.deploy_workloads=true;write('workloads');
}
