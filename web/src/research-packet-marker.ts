import {teamClosed,teamNatural,teamUuid} from './team-setup-request';
import type {WorkspaceEntry} from './workspace-api';

export const RESEARCH_PACKET_LABEL='Research · public source excerpts';

/** Saved-packet provenance supplied by the workspace; never live source availability. */
export function hasResearchPacketMarker(entry:WorkspaceEntry):boolean{
 const marker=entry.research_packet;
 return entry.kind==='evidence'&&teamUuid(entry.id)&&teamNatural(entry.revision)&&entry.revision>0&&
  teamClosed(marker,'contract,run_id,entry_id,entry_revision')&&marker.contract==='research.saved_packet_marker.v1'&&
  teamUuid(marker.run_id)&&marker.entry_id===entry.id&&marker.entry_revision===entry.revision;
}
