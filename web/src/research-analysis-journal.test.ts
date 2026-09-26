import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {openDraftStore} from './draft-store';
import {DraftJournal,editorAddress,type NotebookDraft,type EditorDraft} from './draft-journal';
import {analysisAnchor,analysisBody} from './research-analysis-test-fixture';
import {modelUuid} from './model-work-test-fixture';
import {modelRequestHash} from './model-work-request';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let idb:IDBFactory;const wid=modelUuid(71),address=`workspace:${wid}`,research=editorAddress(wid,`research:${modelUuid(72)}`);
const store=(scope='1'.repeat(64))=>openDraftStore({scope,native:false,indexedDB:idb,crypto:webcrypto});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);idb=new IDBFactory();});afterEach(()=>vi.unstubAllGlobals());
it('reopens exact selected intent and unsent question from real encrypted storage with actor isolation',async()=>{
 const pending={type:'ask' as const,model_contract:1 as const,origin:'durable_admission_v1' as const,body:analysisBody};
 const notebook:NotebookDraft={kind:'workspace',workspaceId:wid,baseRevision:1,note:'Keep my unsaved notebook',thought:'Keep another unsent thought',evidence:'',source:'',pending};
 const editor:EditorDraft={kind:'editor',workspaceId:wid,editor:`research:${modelUuid(72)}`,pending:null,data:{version:1,bot:modelUuid(72),topic:'literature',query:'',sources:[],pending:null,saved_packet:analysisAnchor,analysis_draft:{question:analysisBody.content,selected:true}}};
 const first=new DraftJournal(await store());await first.load(address);await first.load(research);await first.persist(address,notebook);await first.persist(research,editor);first.close();
 const second=new DraftJournal(await store());expect(await second.load(address)).toEqual(notebook);expect(await second.load(research)).toEqual(editor);second.close();
 const foreign=new DraftJournal(await store('2'.repeat(64)));expect(await foreign.load(address)).toBeNull();expect(await foreign.load(research)).toBeNull();foreign.close();
});
it('refuses altered selected history under its old digest before overwriting exact retained intent',async()=>{
 const original={kind:'workspace' as const,workspaceId:wid,baseRevision:1,note:'',thought:'',evidence:'',source:'',pending:null,previous_model_request:{workspace_id:wid,operation:{type:'ask' as const,body:analysisBody},request_sha256:await modelRequestHash(analysisBody),outcome:'unknown' as const,observed_at:'2026-09-22T20:00:00Z',origin:'durable_admission_v1' as const,legacy_uncertainty_acknowledged:true}};
 const journal=new DraftJournal(await store());await journal.load(address);await journal.persist(address,original);
 const altered=structuredClone(original);altered.previous_model_request.operation.body.research_analysis!.entries[0].save_request_sha256='b'.repeat(64);await expect(journal.persist(address,altered)).rejects.toMatchObject({code:'integrity'});journal.close();
 const read=new DraftJournal(await store());expect(await read.load(address)).toEqual(original);read.close();
});
