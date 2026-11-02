export const REGISTERED_NATIVE_PROFILE_CONTRACT: 'cosmas-native-workspace-profile.v1';
export const ACTIVE_NATIVE_WORKSPACE_CONTRACT: 'cosmabot.native-active-workspace.v1';
export type RegisteredNativeProfile = Readonly<{
  contract_version: typeof REGISTERED_NATIVE_PROFILE_CONTRACT;
  client:'apple'|'desktop'; nonce:string; native_origin:'capacitor://localhost'|'app://cosmas';data_mode:'synthetic';
  practice:Readonly<{practice_id:string;box_id:string}>;
  workspace:Readonly<{url:string;source_commit:string;image_sha256:string;workspace_proof_sha256:string;member_proof_sha256:string;native_qualification_sha256:string}>;
  issued_at:number;expires_at:number;
  nativeIdentity:Readonly<{version:1;profile:'operational-staging-v1';client:'apple'|'desktop';
    apiOrigin:string;publishableKey:string;frontendOrigin:string;organizationId:string;audience:string}>;
  session:Readonly<{issuer:string;subject:string;session_id:string}>;
}>;
export type ActiveNativeWorkspace = Readonly<{contract_version:typeof ACTIVE_NATIVE_WORKSPACE_CONTRACT;
  revision:string;profile:RegisteredNativeProfile}>;
export function validateRegisteredNativeProfile(value:unknown):RegisteredNativeProfile;
export function validateActiveNativeWorkspace(value:unknown):ActiveNativeWorkspace;
