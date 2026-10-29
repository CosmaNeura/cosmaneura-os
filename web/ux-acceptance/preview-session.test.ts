import {expect,it,vi} from 'vitest';
import {createPreviewSession,PREVIEW_SIGNED_OUT_KEY} from './preview-session';
function store(){const values=new Map<string,string>();return {values,getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);},removeItem:(key:string)=>{values.delete(key);}};}
it('remembers logout across fresh sessions and leaves other settings and drafts alone',async()=>{
  const storage=store();storage.setItem('private-draft','opaque encrypted bytes');
  const first=createPreviewSession(storage,true),old=first.getSnapshot().identity;
  expect(first.getSnapshot().open).toBe(true);expect(old.nativeSession?.isCurrent()).toBe(true);
  const pending=old.getToken({skipCache:true});first.close();
  expect(await pending).toBeNull();expect(old.nativeSession?.isCurrent()).toBe(false);
  expect(storage.getItem(PREVIEW_SIGNED_OUT_KEY)).toBe('closed');
  const restarted=createPreviewSession(storage,true);
  expect(restarted.getSnapshot().open).toBe(false);expect(await restarted.getSnapshot().identity.getToken({skipCache:true})).toBeNull();
  restarted.enter();expect(restarted.getSnapshot().open).toBe(true);
  expect(await restarted.getSnapshot().identity.getToken({skipCache:true})).toBe('invented-ui-rehearsal-token');
  expect(storage.getItem('private-draft')).toBe('opaque encrypted bytes');expect(await old.getToken({skipCache:true})).toBeNull();
});
it('a logout in another preview closes this view but its later entry does not reopen it',async()=>{
  const storage=store(),session=createPreviewSession(storage,false),old=session.getSnapshot().identity;
  storage.setItem(PREVIEW_SIGNED_OUT_KEY,'closed');expect(await old.getToken({skipCache:true})).toBeNull();
  session.storageChanged(PREVIEW_SIGNED_OUT_KEY,'closed');expect(session.getSnapshot().open).toBe(false);
  storage.removeItem(PREVIEW_SIGNED_OUT_KEY);session.storageChanged(PREVIEW_SIGNED_OUT_KEY,null);
  expect(session.getSnapshot().open).toBe(false);expect(await old.getToken({skipCache:true})).toBeNull();
  session.enter();expect(session.getSnapshot().identity).not.toBe(old);expect(await old.getToken({skipCache:true})).toBeNull();
});
it('refuses to open when durable session storage cannot be read or changed',()=>{
  const getItem=vi.fn(()=>{throw new Error('private storage detail');}),storage={getItem,setItem:vi.fn(),removeItem:vi.fn()};
  const session=createPreviewSession(storage,true);expect(session.getSnapshot()).toMatchObject({open:false,storageError:true});
  session.enter();expect(session.getSnapshot()).toMatchObject({open:false,storageError:true});
});
it('closes immediately even if remembering logout fails, without claiming it was remembered',async()=>{
  const storage=store(),session=createPreviewSession({...storage,setItem:()=>{throw new Error('quota');}},true),old=session.getSnapshot().identity;
  session.close();expect(session.getSnapshot()).toMatchObject({open:false,storageError:true});expect(await old.getToken({skipCache:true})).toBeNull();
});
it('a stale subscription or repeated close cannot restore a previous identity',()=>{
  const session=createPreviewSession(store(),true),changed=vi.fn(),remove=session.subscribe(changed),old=session.getSnapshot().identity;
  session.close();session.close();session.enter();remove();session.close();
  expect(changed).toHaveBeenCalledTimes(3);expect(old.nativeSession?.isCurrent()).toBe(false);expect(session.getSnapshot().open).toBe(false);
});
