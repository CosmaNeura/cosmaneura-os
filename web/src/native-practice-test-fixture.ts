import {validateActiveNativeWorkspace,type ActiveNativeWorkspace} from '../../clients/shared/native-practice-profile.mjs';

/** Public invented identity and proofs, never a credential or signed server proof. */
export function nativePracticeFixture(name='invented',revision='00000000-0000-4000-8000-000000000001'):ActiveNativeWorkspace {
  const issuer='https://invented.clerk.accounts.dev',stamp=1700000000;
  return validateActiveNativeWorkspace({contract_version:'cosmabot.native-active-workspace.v1',revision,
    profile:{contract_version:'cosmas-native-workspace-profile.v1',client:'apple',nonce:'00000000-0000-4000-8000-000000000002',
      native_origin:'capacitor://localhost',data_mode:'synthetic',nativeIdentity:{version:1,profile:'operational-staging-v1',client:'apple',
        apiOrigin:`https://api.${name}.staging.cosmas.ai`,publishableKey:'pk_test_'+btoa('invented.clerk.accounts.dev$'),
        frontendOrigin:issuer,organizationId:`org_${name}`,audience:''},session:{issuer,subject:`user_${name}`,session_id:`sess_${name}`},
      practice:{practice_id:'00000000-0000-4000-8000-000000000003',box_id:'00000000-0000-4000-8000-000000000004'},
      workspace:{url:`https://${name}.staging.cosmas.ai/chief`,source_commit:'1'.repeat(40),image_sha256:'2'.repeat(64),
        workspace_proof_sha256:'3'.repeat(64),member_proof_sha256:'4'.repeat(64),native_qualification_sha256:'5'.repeat(64)},
      issued_at:stamp,expires_at:stamp+120}});
}
