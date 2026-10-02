import type {FaxStatus} from './fax-status-api';
import {vendorDigest} from './vendor-contract';
export const faxScope={box_id:'11111111-1111-4111-8111-111111111111',owner_id:'22222222-2222-4222-8222-222222222222',workspace_id:'33333333-3333-4333-8333-333333333333'};
export const faxTicket='44444444-4444-4444-8444-444444444444';
export async function faxFixture(changes:Partial<FaxStatus>={}):Promise<FaxStatus>{
  const value:FaxStatus={contract_version:1,scope:faxScope,ticket_id:faxTicket,
    operation_id:'55555555-5555-4555-8555-555555555555',revision_id:'66666666-6666-4666-8666-666666666666',payload_hash:'a'.repeat(64),
    provider:'documo',state:'approved',version:1,acceptance:'accepted',dispatch:'response_observed',transport:'pending',result:'none',verification:'pending',
    conflicting_evidence:false,source_current:true,original_account_available:true,responsible_id:faxScope.owner_id,status_label:'Submission accepted; delivery unconfirmed',
    next_step:{code:'check_existing_fax',label:'Check the existing fax status; checking does not send another fax',requires_human:true},external_outcome:'not_established',
    observation_head:{sequence:0,sha256:'b'.repeat(64)},evidence_sha256:'c'.repeat(64),last_recorded:null,pages:null,observed_at:'2026-10-02T12:00:00.000000Z',sha256:'',...changes};
  value.sha256=await vendorDigest('cosmas-fax-status.v1',Object.fromEntries(Object.entries(value).filter(([key])=>!['observed_at','sha256'].includes(key))));return value;
}
