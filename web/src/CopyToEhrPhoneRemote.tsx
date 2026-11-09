import {useEffect} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {useCopyToEhrRemote} from './useCopyToEhrRemote';
import './CopyToEhrPhoneRemote.css';

export type CopyToEhrPhoneRemoteProps={
  identity:AuthenticatedWorkspaceIdentity;
  enabled:boolean;
  /** When the computer session is missing or locked, show local Copy to EHR. */
  onUseLocalCopy?:()=>void;
  lockedComputer?:boolean;
  differentLogin?:boolean;
};

function titleForKey(key:string):string{
  return key.replace(/_/g,' ').replace(/\b\w/g,part=>part.toUpperCase());
}

export function CopyToEhrPhoneRemote(props:CopyToEhrPhoneRemoteProps){
  const {identity,enabled,onUseLocalCopy,lockedComputer=false,differentLogin=false}=props;
  const remote=useCopyToEhrRemote({identity,enabled,role:'phone'});
  const showLocal=differentLogin||lockedComputer||remote.connection==='failed'||remote.connection==='idle'&&!remote.session;

  useEffect(()=>{
    if(!enabled||differentLogin||lockedComputer)return;
    void remote.joinCurrentSession();
    // Join once when remote mode opens for the signed-in clinician.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[enabled,identity,differentLogin,lockedComputer]);

  if(!enabled)return null;

  return (
    <section className="copy-to-ehr-phone-remote" data-connection={remote.connection} aria-label="Copy to EHR phone remote">
      <h1>Copy to EHR</h1>
      <p>Tap a section to highlight it on the computer. The computer still copies; you still paste.</p>
      {remote.noteNotSent&&(
        <p className="copy-to-ehr-phone-remote__status" role="alert">
          The note was not sent. Use Copy to EHR on this phone.
        </p>
      )}
      {!remote.noteNotSent&&remote.error&&(
        <p className="copy-to-ehr-phone-remote__status" role="status">{remote.error}</p>
      )}
      {differentLogin&&(
        <p className="copy-to-ehr-phone-remote__status" role="status">
          This phone is signed in as a different clinician. Use Copy to EHR here.
        </p>
      )}
      {lockedComputer&&(
        <p className="copy-to-ehr-phone-remote__status" role="status">
          The computer is locked. Use Copy to EHR on this phone.
        </p>
      )}
      {remote.session&&remote.connection==='connected'&&(
        <div className="copy-to-ehr-phone-remote__actions">
          {remote.session.section_keys.map(key=>(
            <button
              key={key}
              type="button"
              onClick={()=>{void remote.sendHighlight(key);}}
            >
              Highlight {titleForKey(key)}
            </button>
          ))}
          <button type="button" data-kind="end" onClick={()=>{void remote.endSession('end');}}>
            End remote
          </button>
        </div>
      )}
      {showLocal&&(
        <div className="copy-to-ehr-phone-remote__local">
          <p>Local copy stays on this phone. Nothing is sent to the computer until a remote session is open.</p>
          <button type="button" onClick={()=>onUseLocalCopy?.()}>
            Copy to EHR on this phone
          </button>
        </div>
      )}
    </section>
  );
}
