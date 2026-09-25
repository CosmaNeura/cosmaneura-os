import type {AccessRequest,AccessStatus} from './practice-access-contract';
// Invented contract vectors; no actual account or identity-service acceptance.
export const accessFixture:AccessRequest={request_id:'873c4f63-2c89-4a51-a834-41574da371a9',display_name:'Ada Beta',review_sha256:'a'.repeat(64),state:'pending',created_at:'2026-09-24T09:00:00+00:00',expires_at:'2026-10-01T09:00:00+00:00'};
export const accessRequired:AccessStatus={contract_version:1,state:'request_required',role:null,request:null};
export const accessPending:AccessStatus={contract_version:1,state:'pending',role:null,request:accessFixture};
export const accessConnected:AccessStatus={contract_version:1,state:'connected',role:'member',request:null};
