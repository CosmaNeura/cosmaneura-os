// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {ResearchChiefHandoff,researchChiefDirections,researchChiefUnavailable,type ResearchChiefSelection} from './research-chief';
import {WorkspaceSession} from './workspace-session';
import type {ConversationHost} from './conversations';
import {DraftJournal,editorAddress} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import {teamFixture,teamUuid} from '../team-setup-test-fixture';
import {analysisProofFixture} from '../research-analysis-test-fixture';
import {researchAnalysisPreview} from '../research-analysis-contract';
import type {DraftStore} from '../draft-store';

async function fixture(wrapStore:(store:DraftStore)=>DraftStore=store=>store){
 const proof=await analysisProofFixture(),identity={mode:'clerk_jwt' as const,getToken:async()=>null};
 const team=teamFixture();team.configuration.bots.push({role:'research',instance_id:proof.run.bot,name:'Research',enabled:true,response_style:'brief',include_notebook:false,include_evidence:true});
 const read=vi.fn(async()=>proof.workspace),api={read:vi.fn(async()=>({contract_version:1 as const,as_of:'2026-10-25T12:00:00Z',rows:[],next_cursor:null})),mark:vi.fn(async()=>({contract_version:1 as const,marker_version:1,manual_unread:false,seen_watermark:null}))};
 const session=new WorkspaceSession({conversationRead:read,conversations:api});session.setWorkspace(proof.workspace);session.setTeam(team);session.setIdentity(identity);session.setSelected('chief');session.setPracticePage('notebook');
 const storage=memoryDraftStorage(),journal=new DraftJournal(wrapStore(await storage({scope:'invented'})));session.recovery.journal.current={scope:'invented',serverScope:'a'.repeat(64),value:journal};
 let foreground=true,blocked=false;
 const host:ConversationHost={identity,journal,scope:'invented',current:()=>foreground&&session.getSnapshot().identity===identity,blocked:()=>blocked||session.getSnapshot().busy||!!session.getSnapshot().pending||session.getSnapshot().researchPending,
  authorize:vi.fn(async()=>{}),failure:vi.fn(),navigate:vi.fn(async route=>{session.navigation.sequence.current++;session.setSelected(route.helper!);session.setPracticePage('notebook');session.setSettingsOpen(false);session.setPracticeOpen(false);})};
 session.models.updateThought('Keep the original Chief directions.');await session.conversations.observe(host);
 await session.conversations.open(proof.workspace.id,proof.run.bot,host);session.models.updateThought('Keep the separate Research conversation draft.');await session.conversations.retain(host);
 const selection:ResearchChiefSelection={...proof,workspace_id:proof.workspace.id,workspace_revision:proof.workspace.revision,team_revision:team.revision,bot:proof.run.bot};
 const focus=vi.fn(),helper=new ResearchChiefHandoff(session);
 return {proof,session,host,journal,selection,focus,helper,read,api,storage,setForeground:(value:boolean)=>{foreground=value;},setBlocked:(value:boolean)=>{blocked=value;}};
}
describe('verified Research packet to Chief draft',()=>{
 it('retains both bot drafts, stores only editable directions, and uses the existing conversation opening reads',async()=>{
  const f=await fixture(),send=vi.spyOn(f.session.models,'save');f.read.mockClear();f.api.mark.mockClear();
  expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(true);
  const text='Keep the original Chief directions.\n\n'+researchChiefDirections(f.selection.anchor);
  expect(f.session.getSnapshot()).toMatchObject({selected:'chief',thought:text,selectedSource:f.selection.anchor.entry_id,busy:false});
  expect(await f.journal.load(editorAddress(f.proof.workspace.id,'conversation:chief'))).toMatchObject({data:{text}});
  expect(await f.journal.load(editorAddress(f.proof.workspace.id,`conversation:${f.selection.bot}`))).toMatchObject({data:{text:'Keep the separate Research conversation draft.'}});
  expect(text).not.toContain(f.selection.run.results[0].excerpt);expect(text).not.toContain('Retained source details');
  expect(f.read).toHaveBeenCalledOnce();expect(f.api.mark).toHaveBeenCalledOnce();expect(f.focus).toHaveBeenCalledOnce();expect(send).not.toHaveBeenCalled();
 });
 it('prepares an empty Chief draft without requiring a previous retained message',async()=>{
  const f=await fixture(),address=editorAddress(f.proof.workspace.id,'conversation:chief');await f.journal.persist(address,null);
  expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(true);expect(f.session.getSnapshot().thought).toBe(researchChiefDirections(f.selection.anchor));
  expect(await f.journal.load(address)).toMatchObject({data:{text:researchChiefDirections(f.selection.anchor)}});
 });
 it.each(['packet','save','run','workspace','revision','bot'] as const)('refuses changed %s proof before moving Chief',async change=>{
  const f=await fixture(),selection=structuredClone(f.selection);
  if(change==='packet')selection.anchor.save_request_sha256='f'.repeat(64);
  if(change==='save')selection.saved.entry_id=teamUuid(999);
  if(change==='run')selection.run.results[0].excerpt='unverified text';
  if(change==='workspace')selection.workspace_id=teamUuid(999);
  if(change==='revision')selection.workspace_revision++;
  if(change==='bot')selection.bot=teamUuid(999);
  expect(await f.helper.prepare(selection,f.host,f.focus)).toBe(false);expect(f.session.getSnapshot().selected).toBe(f.selection.bot);expect(f.session.getSnapshot().thought).toBe('Keep the separate Research conversation draft.');expect(f.focus).not.toHaveBeenCalled();
 });
 it.each(['paused','retired','evidence','answer'] as const)('honors Chief %s restrictions without changing settings',async change=>{
  const f=await fixture(),team=structuredClone(f.session.getSnapshot().team!),chief=team.configuration.bots.find(bot=>bot.role==='chief')!;
  if(change==='paused')chief.enabled=false;if(change==='retired')chief.retired=true;if(change==='evidence')chief.include_evidence=false;if(change==='answer')chief.blocked_capabilities=['model_answer'];
  f.session.setTeam(team);expect(researchChiefUnavailable(team)).not.toBeNull();expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(false);expect(f.session.getSnapshot().team).toEqual(team);expect(f.focus).not.toHaveBeenCalled();
 });
 it.each(['pending','unrelated'] as const)('preserves the existing %s navigation guard',async state=>{
  const f=await fixture();if(state==='pending')f.session.setResearchPending(true);else f.setBlocked(true);
  expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(false);expect(f.session.getSnapshot().selected).toBe(f.selection.bot);
 });
 it('preserves a saved-note Chief task and refuses to mix its draft with Research directions',async()=>{
  const f=await fixture(),task={contract:'chief-note-task.compose.v1' as const,note_id:teamUuid(811),note_version:1,content_hash:'a'.repeat(64),source_fingerprint:'b'.repeat(64)};
  await f.journal.persist(editorAddress(f.proof.workspace.id,'conversation:chief'),{kind:'editor',workspaceId:f.proof.workspace.id,editor:'conversation:chief',pending:null,data:{text:'Saved-note directions',noteTask:task}});
  expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(false);expect(f.session.getSnapshot()).toMatchObject({thought:'Saved-note directions',phoneNoteTask:{selection:{note_id:task.note_id}}});expect(f.session.getSnapshot().error).toContain('Finish or close');
 });
 it('refuses overflow without truncating the retained Chief draft',async()=>{
  const f=await fixture(),text='x'.repeat(3900);await f.journal.persist(editorAddress(f.proof.workspace.id,'conversation:chief'),{kind:'editor',workspaceId:f.proof.workspace.id,editor:'conversation:chief',pending:null,data:{text}});
  expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(false);expect(f.session.getSnapshot().thought).toBe(text);expect(f.session.getSnapshot().error).toContain('too long');expect(f.focus).not.toHaveBeenCalled();
 });
 it('keeps the prior Chief text when its continuation cannot be persisted',async()=>{
  const f=await fixture(),persist=f.journal.persist.bind(f.journal);vi.spyOn(f.journal,'persist').mockImplementation(async(address,draft)=>{if(JSON.stringify(draft).includes('Review the saved public Research packet'))throw new Error('sensitive storage details');await persist(address,draft);});
  expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(false);expect(f.session.getSnapshot().thought).toBe('Keep the original Chief directions.');expect(f.session.getSnapshot().error).not.toContain('sensitive');expect(f.focus).not.toHaveBeenCalled();
 });
 it.each(['account','workspace','foreground','edit'] as const)('does not move or replace a draft after %s changes during proof',async change=>{
  const f=await fixture();let release!:()=>void;const prove=vi.fn(async(...args:Parameters<typeof researchAnalysisPreview>)=>{await new Promise<void>(resolve=>{release=resolve;});return researchAnalysisPreview(...args);});
  const preparing=new ResearchChiefHandoff(f.session,prove).prepare(f.selection,f.host,f.focus);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  if(change==='account')f.session.setIdentity({mode:'clerk_jwt',getToken:async()=>null});if(change==='workspace')f.session.setWorkspace({...f.proof.workspace,id:teamUuid(999)});if(change==='foreground')f.setForeground(false);if(change==='edit')f.session.models.updateThought('Newer Research directions');
  release();expect(await preparing).toBe(false);expect(f.session.getSnapshot().thought).toBe(change==='edit'?'Newer Research directions':'Keep the separate Research conversation draft.');expect(f.focus).not.toHaveBeenCalled();
 });
 it('rechecks the exact current packet after account authorization',async()=>{
  const f=await fixture();vi.mocked(f.host.authorize).mockImplementation(async()=>{if(vi.mocked(f.host.authorize).mock.calls.length===2)f.session.setWorkspace({...f.proof.workspace,entries:[]});});
  expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(false);expect(f.session.getSnapshot().thought).toBe('Keep the original Chief directions.');expect(f.focus).not.toHaveBeenCalled();
 });
 it.each(['source','settings','account','route','foreground','unrelated'] as const)('does not publish or focus a stale %s continuation when journal completion arrives',async change=>{
  const f=await fixture(),persist=f.journal.persist.bind(f.journal);let release!:()=>void;
  vi.spyOn(f.journal,'persist').mockImplementation(async(address,draft,expected)=>{if(JSON.stringify(draft).includes('Review the saved public Research packet'))await new Promise<void>(resolve=>{release=resolve;});await persist(address,draft,expected);});
  const preparing=f.helper.prepare(f.selection,f.host,f.focus);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  expect(f.session.getSnapshot().thought).toBe('Keep the original Chief directions.');
  if(change==='source')f.session.setWorkspace({...f.proof.workspace,entries:[]});
  if(change==='settings'){const team=structuredClone(f.session.getSnapshot().team!);team.configuration.bots.find(bot=>bot.role==='chief')!.include_evidence=false;f.session.setTeam(team);}
  if(change==='account')f.session.setIdentity({mode:'clerk_jwt',getToken:async()=>null});
  if(change==='route'){f.session.navigation.sequence.current++;f.session.setPracticePage('home');}
  if(change==='foreground')f.setForeground(false);
  if(change==='unrelated')f.setBlocked(true);
  release();expect(await preparing).toBe(false);expect(f.session.getSnapshot().thought).toBe('Keep the original Chief directions.');expect(f.focus).not.toHaveBeenCalled();expect(f.session.getSnapshot().selectedSource).toBeNull();
  expect(await f.journal.load(editorAddress(f.proof.workspace.id,'conversation:chief'))).toMatchObject({data:{text:'Keep the original Chief directions.'}});
 });
 it('rechecks unrelated locks introduced by the final authorization without blocking on its own conversation marker',async()=>{
  const f=await fixture();let authorizations=0;f.host.authorize=async()=>{if(++authorizations===2)f.setBlocked(true);};
  expect(await f.helper.prepare(f.selection,f.host,f.focus)).toBe(false);expect(authorizations).toBe(2);
  expect(f.session.getSnapshot()).toMatchObject({thought:'Keep the original Chief directions.',conversationBusy:false});expect(f.focus).not.toHaveBeenCalled();
  expect(await f.journal.load(editorAddress(f.proof.workspace.id,'conversation:chief'))).toMatchObject({data:{text:'Keep the original Chief directions.'}});
 });
 it('preserves a newer queued Chief edit when a stale continuation finishes',async()=>{
  let release!:()=>void;
  const f=await fixture(store=>({...store,async write(address,expected,value){const saved=await store.write(address,expected,value);if(JSON.stringify(value).includes('Review the saved public Research packet'))await new Promise<void>(resolve=>{release=resolve;});return saved;}}));
  const preparing=f.helper.prepare(f.selection,f.host,f.focus);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  f.session.models.updateThought('Newer Chief edit wins.');
  const address=editorAddress(f.proof.workspace.id,'conversation:chief'),saving=f.journal.persist(address,{kind:'editor',workspaceId:f.proof.workspace.id,editor:'conversation:chief',pending:null,data:{text:'Newer Chief edit wins.'}});
  release();expect(await preparing).toBe(false);await saving;
  expect(f.session.getSnapshot().thought).toBe('Newer Chief edit wins.');expect(f.focus).not.toHaveBeenCalled();
  expect(await f.journal.load(address)).toMatchObject({data:{text:'Newer Chief edit wins.'}});
 });
 it('never targets a replacement account journal during cleanup',async()=>{
  const f=await fixture(),persist=f.journal.persist.bind(f.journal);let release!:()=>void;
  vi.spyOn(f.journal,'persist').mockImplementation(async(address,draft,expected)=>{if(JSON.stringify(draft).includes('Review the saved public Research packet'))await new Promise<void>(resolve=>{release=resolve;});await persist(address,draft,expected);});
  const preparing=f.helper.prepare(f.selection,f.host,f.focus);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  const address=editorAddress(f.proof.workspace.id,'conversation:chief'),replacement=new DraftJournal(await f.storage({scope:'replacement'}));await replacement.load(address);await replacement.persist(address,{kind:'editor',workspaceId:f.proof.workspace.id,editor:'conversation:chief',pending:null,data:{text:'Other account draft'}});
  f.session.recovery.journal.current={scope:'replacement',serverScope:'b'.repeat(64),value:replacement};release();expect(await preparing).toBe(false);
  expect(await replacement.load(address)).toMatchObject({data:{text:'Other account draft'}});expect(await f.journal.load(address)).toMatchObject({data:{text:'Keep the original Chief directions.'}});expect(f.focus).not.toHaveBeenCalled();
 });
 it('does not publish after real journal close; a possibly committed write remains only an unsent draft on reopening',async()=>{
  let release!:()=>void;
  const f=await fixture(store=>({...store,async write(address,expected,value){const saved=await store.write(address,expected,value);if(JSON.stringify(value).includes('Review the saved public Research packet'))await new Promise<void>(resolve=>{release=resolve;});return saved;}}));
  const preparing=f.helper.prepare(f.selection,f.host,f.focus);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  f.journal.close();f.session.setIdentity({mode:'clerk_jwt',getToken:async()=>null});release();expect(await preparing).toBe(false);
  expect(f.session.getSnapshot().thought).toBe('Keep the original Chief directions.');expect(f.focus).not.toHaveBeenCalled();expect(f.session.getSnapshot().selectedSource).toBeNull();
  const reopened=new DraftJournal(await f.storage({scope:'invented'}));expect(await reopened.load(editorAddress(f.proof.workspace.id,'conversation:chief'))).toMatchObject({pending:null,data:{text:'Keep the original Chief directions.\n\n'+researchChiefDirections(f.selection.anchor)}});
 });
 it('coalesces duplicate clicks while the first proof is unfinished',async()=>{
  const f=await fixture();let release!:()=>void,first=true;const prove=async(...args:Parameters<typeof researchAnalysisPreview>)=>{if(first){first=false;await new Promise<void>(resolve=>{release=resolve;});}return researchAnalysisPreview(...args);};
  const helper=new ResearchChiefHandoff(f.session,prove),firstRequest=helper.prepare(f.selection,f.host,f.focus);await vi.waitFor(()=>expect(release).toBeTypeOf('function'));expect(await helper.prepare(f.selection,f.host,f.focus)).toBe(false);release();expect(await firstRequest).toBe(true);expect(f.focus).toHaveBeenCalledOnce();
 });
});
