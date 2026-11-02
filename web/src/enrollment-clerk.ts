import { EnrollmentError, type EnrollmentStatus } from './enrollment-contract';
import type { EnrollmentIdentity } from './enrollment-api';

type MembershipPage = {data:{organization:{id:string}}[];total_count:number};
export type EnrollmentWorkspaceAccount = {
  identity:EnrollmentIdentity;reload:()=>Promise<unknown>;
  memberships:(page:number)=>Promise<MembershipPage>;
  activate:(organization:string|null)=>Promise<unknown>;activeOrganization:()=>string|null|undefined;
};

/** Obtain proof for the registry-selected practice. A fresh account proof can request membership preparation. */
export async function prepareEnrollmentWorkspaceToken(account:EnrollmentWorkspaceAccount,status:EnrollmentStatus,
  signal?:AbortSignal,allowPreparation=false):Promise<string> {
  const target=status.workspace.organization_id;
  const current=()=>{if(signal?.aborted||!account.identity.isCurrent())throw new EnrollmentError(401);};
  current();if(!target)throw new EnrollmentError(409);
  await account.reload();current();
  let member=false;
  for(let page=1;page<=10;page++){
    const memberships=await account.memberships(page);current();
    if(memberships.data.some(item=>item.organization.id===target)){member=true;break;}
    if(page*100>=memberships.total_count)break;
  }
  if(!member&&!allowPreparation)throw new EnrollmentError(403,'enrollment_membership_preparation_required');
  const wanted=member?target:null;
  if(member||account.activeOrganization()){
    await account.activate(wanted);current();
    const deadline=performance.now()+10000;
    while(!signal?.aborted&&account.identity.isCurrent()&&(account.activeOrganization()??null)!==wanted&&performance.now()<deadline)
      await new Promise(resolve=>setTimeout(resolve,50));
    current();if((account.activeOrganization()??null)!==wanted)throw new EnrollmentError(403);
  }
  const token=await account.identity.getToken({skipCache:true});current();
  if(!token)throw new EnrollmentError(401);return token;
}
