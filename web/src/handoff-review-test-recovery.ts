import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {DraftJournal} from './draft-journal';
import {openDraftStore} from './draft-store';
import type {EditorRecoveryAccess} from './editor-recovery';
import type {Workspace} from './workspace-api';
/** Test-only actual encrypted journal; the caller supplies the current authorized workspace reader. */
export async function createHandoffReviewTestRecovery(workspaceId:string,read:()=>Promise<Workspace>,crypto:Crypto):Promise<EditorRecoveryAccess>{
 const journal=new DraftJournal(await openDraftStore({scope:'e'.repeat(64),native:false,indexedDB:new IDBFactory(),crypto}));
 return {workspaceId,journal,authorize:read,denied:()=>{}};
}
