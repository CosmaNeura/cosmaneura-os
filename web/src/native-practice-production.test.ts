import {describe,expect,it} from 'vitest';
import {validateRegisteredNativeProfile} from '../../clients/shared/native-practice-profile.mjs';

const practice='0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d',host=`${practice}.workspace.cosmas.ai`;
const live='pk_live_'+btoa('clerk.cosmas.ai$');
/** Invented public profile for a real-data production practice; no credential or signed proof. */
function production(change:(value:any)=>void=()=>{}){
  const stamp=1700000000,value:any={contract_version:'cosmas-native-workspace-profile.v1',client:'apple',
    nonce:'00000000-0000-4000-8000-000000000002',native_origin:'capacitor://localhost',data_mode:'authorized_beta',
    nativeIdentity:{version:1,profile:'operational-beta-v1',client:'apple',apiOrigin:`https://api.${host}`,publishableKey:live,
      frontendOrigin:'https://clerk.cosmas.ai',organizationId:'org_invented',audience:'cosmabot-practice-api'},
    session:{issuer:'https://clerk.cosmas.ai',subject:'user_invented',session_id:'sess_invented'},
    practice:{practice_id:practice,box_id:'00000000-0000-4000-8000-000000000004'},
    workspace:{url:`https://${host}/chief`,source_commit:'1'.repeat(40),image_sha256:'2'.repeat(64),
      workspace_proof_sha256:'3'.repeat(64),member_proof_sha256:'4'.repeat(64),native_qualification_sha256:'5'.repeat(64)},
    issued_at:stamp,expires_at:stamp+120};
  change(value);return value;
}

describe('registered native profile for a real-data production practice',()=>{
  it('accepts only the production realm, its own practice UUID host and real data mode',()=>{
    const value=validateRegisteredNativeProfile(production());
    expect(value.data_mode).toBe('authorized_beta');
    expect(value.workspace.url).toBe(`https://${host}/chief`);
  });
  it.each([
    ['synthetic data mode',(v:any)=>{v.data_mode='synthetic';}],
    ['unknown data mode',(v:any)=>{v.data_mode='production';}],
    ['staging profile',(v:any)=>{v.nativeIdentity.profile='operational-staging-v1';}],
    ['development issuer',(v:any)=>{v.nativeIdentity.frontendOrigin='https://invented.clerk.accounts.dev';
      v.nativeIdentity.publishableKey='pk_live_'+btoa('invented.clerk.accounts.dev$');v.session.issuer=v.nativeIdentity.frontendOrigin;}],
    ['staging host',(v:any)=>{v.workspace.url=`https://${practice}.staging.cosmas.ai/chief`;v.nativeIdentity.apiOrigin=`https://api.${practice}.staging.cosmas.ai`;}],
    ['another practice host',(v:any)=>{const other='1a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d';
      v.workspace.url=`https://${other}.workspace.cosmas.ai/chief`;v.nativeIdentity.apiOrigin=`https://api.${other}.workspace.cosmas.ai`;}],
    ['non-UUID host',(v:any)=>{v.workspace.url='https://clinic.workspace.cosmas.ai/chief';v.nativeIdentity.apiOrigin='https://api.clinic.workspace.cosmas.ai';}],
    ['reserved host',(v:any)=>{v.workspace.url='https://api.workspace.cosmas.ai/chief';v.nativeIdentity.apiOrigin='https://api.api.workspace.cosmas.ai';}],
    ['unpaired API',(v:any)=>{v.nativeIdentity.apiOrigin='https://api.cosmas.ai';}],
    ['blank audience',(v:any)=>{v.nativeIdentity.audience='';}],
  ] as const)('refuses %s',(_name,change)=>{
    expect(()=>validateRegisteredNativeProfile(production(change))).toThrow();
  });
});
