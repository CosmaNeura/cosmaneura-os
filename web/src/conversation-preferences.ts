import {teamAddress,teamClosed,teamUuid} from './team-setup-request';

export type ConversationPreference={workspace_id:string;bot:string;pinned:boolean;hidden:boolean};
export type ConversationPreferences={contract:'conversation-preferences.v1';items:ConversationPreference[]};
export const conversationPreferenceKey=(workspaceId:string,bot:string)=>`${workspaceId}:${bot}`;
export const emptyConversationPreferences=():ConversationPreferences=>({contract:'conversation-preferences.v1',items:[]});
export function parseConversationPreferences(value:unknown):ConversationPreferences {
  if(!teamClosed(value,'contract,items')||value.contract!=='conversation-preferences.v1'||!Array.isArray(value.items)||value.items.length>500)throw new Error('Invalid conversation preferences');
  const seen=new Set<string>();
  for(const item of value.items){
    if(!teamClosed(item,'workspace_id,bot,pinned,hidden')||!teamUuid(item.workspace_id)||!teamAddress(item.bot)||typeof item.pinned!=='boolean'||typeof item.hidden!=='boolean'||!item.pinned&&!item.hidden)throw new Error('Invalid conversation preference');
    const key=conversationPreferenceKey(item.workspace_id,item.bot);if(seen.has(key))throw new Error('Duplicate conversation preference');seen.add(key);
  }
  return value as ConversationPreferences;
}
