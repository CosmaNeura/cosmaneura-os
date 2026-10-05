import type {FaxStatus} from './fax-inbound-api';
export const faxUuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
export const faxScope={box_id:faxUuid(1),owner_id:faxUuid(2)};
export const faxStatus:FaxStatus={contract_version:1,installations:[{connection_id:faxUuid(3),label:'Invented café inbox',vendor:'documo',metadata_available:true,image_available:true,image_block_reason:null}],grants:[{grant_id:faxUuid(4),label:'Invented café inbox',image_enabled:true,expires_at:'2026-10-06T18:00:00Z',state:'granted'}]};
