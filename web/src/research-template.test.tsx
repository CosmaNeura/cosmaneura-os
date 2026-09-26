import {act,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {expect,it,vi} from 'vitest';
import {ProviderTeamSettings} from './ProviderTeamSettings';
import {BotAvatar} from './BotAvatar';
import {teamFixture} from './team-setup-test-fixture';
import {validProviderTeam} from './team-setup-validators';
import {normalizeTeamConfiguration,teamAddress,validTeamConfiguration} from './team-setup-request';
import {DraftJournal,teamDraft} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import type {BotTemplate,TeamConfiguration} from './workspace-api';
const template:BotTemplate={role:'research',agent_id:null,name:'Research',initials:'Re',description:'Compare dated public sources.',prompt:'Review a public research question.',capabilities:[]};
const sourceTeam=()=>{const t=teamFixture();return {...t,templates:[...t.members.filter(b=>b.role!=='chief'),template]};};
it('adds Research through the compact picker with a private UUID while preserving all four existing bots',async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);const element=document.createElement('div');document.body.append(element);const root=createRoot(element),team=sourceTeam();let current:TeamConfiguration=team.configuration;
 function Harness(){const [draft,setDraft]=useState(team.configuration),[selected,setSelected]=useState('scribe');current=draft;return <ProviderTeamSettings team={team} draft={draft} setDraft={setDraft} selected={selected} setSelected={setSelected} locked={false} onSave={()=>{}} onClose={()=>{}} view="add"/>;}
 try{await act(async()=>root.render(<Harness/>));const button=[...element.querySelectorAll('button')].find(b=>b.querySelector('strong')?.textContent==='Research')!;
 expect(button).toBeTruthy();expect(element.querySelectorAll('textarea,input,select')).toHaveLength(0);
 await act(async()=>button.click());await act(async()=>button.click());
 expect(current.bots.slice(0,4)).toEqual(team.configuration.bots);expect(new Set(current.bots.slice(4).map(b=>b.instance_id)).size).toBe(2);
 for(const bot of current.bots.slice(4)){expect(bot).toMatchObject({role:'research',include_notebook:false,include_evidence:false});expect(teamAddress(bot.instance_id)).toBe(true);}
 expect(validTeamConfiguration(current)).toBe(true);
 }finally{await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();}
});
it('requires UUID Research instances, preserves old normalization and verifies the server-owned template roster',()=>{
 const team=sourceTeam(),base=normalizeTeamConfiguration(team.configuration),research={...base.bots[0],role:'research' as const,name:'Research',instance_id:'00000000-0000-4000-8000-000000000005'};
 expect(normalizeTeamConfiguration(team.configuration)).toEqual(base);expect(validProviderTeam(team)).toBe(true);expect(teamAddress('research')).toBe(false);
 const bots=[...base.bots,research];expect(validTeamConfiguration({...base,bots})).toBe(true);expect(validTeamConfiguration({...base,bots:bots.map(b=>b===research?{...b,instance_id:null}:b)})).toBe(false);
 const raw={...research,include_notebook:undefined,include_evidence:undefined};expect(normalizeTeamConfiguration({...base,bots:[...base.bots,raw]}).bots.at(-1)).toMatchObject({include_notebook:false,include_evidence:false});
 expect(validTeamConfiguration({...base,bots:[...bots,{...research}]})).toBe(false);
});
it('recovers the exact fifth template settings with pause/retirement and stable identity without changing original team',async()=>{
 const team=sourceTeam(),factory=memoryDraftStorage(),scope={scope:'a'.repeat(64)},journal=new DraftJournal(await factory(scope));await journal.load('team');
 const configuration={...team.configuration,bots:[...team.configuration.bots,{...team.configuration.bots[0],role:'research' as const,instance_id:'00000000-0000-4000-8000-000000000005',name:'Literature partner',enabled:false,retired:true,include_notebook:false,include_evidence:false,job_focus:'Compare cited versions'}]};
 const draft=teamDraft(team,configuration,null)!;await journal.persist('team',draft);journal.close();const reopened=new DraftJournal(await factory(scope));expect(await reopened.load('team')).toEqual(draft);expect(configuration.bots.slice(0,4)).toEqual(team.configuration.bots);reopened.close();
});
it('uses a code-native Research portrait without claiming or fetching new motion assets',async()=>{
 vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);const element=document.createElement('div'),root=createRoot(element);
 try{await act(async()=>root.render(<BotAvatar role="research" active greeting/>));expect(element.querySelector('svg')).toBeTruthy();expect(element.querySelector('img')).toBeNull();expect(element.querySelector('[data-motion-phase]')?.getAttribute('data-motion-phase')).toBe('idle');}finally{await act(async()=>root.unmount());vi.unstubAllGlobals();}
});
