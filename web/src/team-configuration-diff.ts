import {normalizedProfile} from './practice-profile';
import {botAddress,type BotSettings,type TeamConfiguration} from './workspace-api';
import {teamCanonical,teamStrip} from './team-setup-request';
const text=(value:string|undefined)=>teamStrip(value??'');
function botFields(bot:BotSettings):Record<string,unknown>{return {
  name:text(bot.name),enabled:bot.enabled,response_style:bot.response_style??'brief',
  job_focus:text(bot.job_focus),working_preferences:text(bot.working_preferences),retired:bot.retired??false,
  include_notebook:bot.include_notebook??bot.role!=='research',include_evidence:bot.include_evidence??bot.role!=='research',
  skills:[...(bot.skills??[])].sort(),blocked_capabilities:[...(bot.blocked_capabilities??[])].sort(),
  resources:bot.resources?{version:1,allowed:[...bot.resources.allowed].sort((a,b)=>a.purpose.localeCompare(b.purpose))}:null,
};}
const otherFields=(value:TeamConfiguration)=>({practice_context:text(value.practice_context??'Direct Primary Care'),
  practice_profile:normalizedProfile(value.practice_profile)??null,presets:[...(value.presets??[])].sort((a,b)=>a.preset_id.localeCompare(b.preset_id)),model_work:value.model_work??null});
export type TeamFieldChange={field:string;before:unknown;after:unknown};
export function teamConfigurationDiff(saved:TeamConfiguration,draft:TeamConfiguration){
  const bots=draft.bots.flatMap(bot=>{const old=saved.bots.find(item=>botAddress(item)===botAddress(bot)),before=old?botFields(old):{},after=botFields(bot);
    const fields=Object.keys(after).filter(key=>teamCanonical(before[key]??null)!==teamCanonical(after[key])).map(field=>({field,before:before[field],after:after[field]}));
    return fields.length?[{address:botAddress(bot),name:bot.name||'Unnamed coworker',added:!old,fields}]:[];});
  const before=otherFields(saved),after=otherFields(draft),settings=Object.keys(after).filter(key=>teamCanonical(before[key as keyof typeof before])!==teamCanonical(after[key as keyof typeof after])).map(field=>({field,before:before[field as keyof typeof before],after:after[field as keyof typeof after]}));
  return {bots,settings,count:bots.reduce((count,bot)=>count+bot.fields.length,0)+settings.length};
}
export const teamConfigurationChanged=(saved:TeamConfiguration,draft:TeamConfiguration)=>teamConfigurationDiff(saved,draft).count>0;
