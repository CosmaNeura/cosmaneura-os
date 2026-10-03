import type {FaxProvider,FaxReadiness} from './fax-readiness-api';
import './fax-connection.css';

const providers:Record<FaxProvider,{name:string;setup:string;workflow:string}>= {
  spruce:{name:'Spruce',
    setup:'A Spruce account with API access and a sending fax line. Your practice administrator also connects Spruce’s status updates.',
    workflow:'Review and approve the PDF upload first, then review and approve the fax separately. Check final delivery in Spruce; CosmaBot cannot yet confirm Spruce fax delivery.'},
  srfax:{name:'SRFax',
    setup:'Your SRFax account number and password, sending fax number, and sender email. Your practice administrator connects these securely.',
    workflow:'Review the PDF and recipient, approve sending, then check delivery in Fax work.'},
  documo:{name:'Documo',
    setup:'A Documo account with API access, your account ID and a sending fax number. Ask your practice administrator to allow both sending and checking delivery; a send-only key is not enough.',
    workflow:'Review the PDF and recipient, approve sending, then check delivery in Fax work. Accepted means Documo has received the request; it does not mean the fax was delivered.'},
  efax:{name:'eFax Corporate',
    setup:'An eFax Corporate or Enterprise API account. A regular eFax subscription may not include API access. Your practice administrator connects the account securely.',
    workflow:'Review the PDF and recipient, approve sending, then check delivery in Fax work.'},
};

export function FaxConnectionOverview({value,loading,unavailable,locked,onRefresh,onSetup,onOpenWork,workLabel,workBlocked}:{
  value?:FaxReadiness;loading:boolean;unavailable:boolean;locked:boolean;
  onRefresh:()=>void;onSetup:()=>void;onOpenWork?:()=>void;workLabel:string;workBlocked:boolean;
}){
  const ready=!!value?.enabled&&value.work_enabled&&value.providers.some(provider=>provider.prepare_enabled_accounts>0);
  const current=!loading&&!unavailable&&!!value;
  const missing=current?[
    !value.enabled?'Enable messaging and fax setup for this practice.':null,
    !value.work_enabled?'Enable fax work for this practice.':null,
    !value.document_storage_configured?'Finish private document storage setup.':null,
    !value.credential_access_configured?'Finish secure access to the provider account.':null,
    !value.delivery_enabled?'Enable sending after account setup and review.':null,
  ].filter(Boolean):[];
  return <section className="fax-connection-overview" aria-label="Fax providers and next steps">
    <h2>📠 Choose your fax provider</h2>
    <p>Use the service your practice prefers. Supported options are below; each needs its own practice account.</p>
    <p role="status">{loading?'Checking fax setup…':unavailable?'Practice fax setup needs to be enabled.':value?
      ready?'An account is available for preparing a fax draft.':'Finish the account setup below before preparing a fax.':
      'Fax setup could not be confirmed. Check again for the latest account status.'}</p>
    <div className="fax-provider-options">{(Object.keys(providers) as FaxProvider[]).map(id=>{
      const provider=providers[id],status=current?value.providers.find(row=>row.id===id):undefined;
      const label=!status?'Not checked':!status.installed_accounts?'Needs practice connection':status.prepare_enabled_accounts?
        'Account configured':status.review_required_accounts?'Account needs review':'No enabled fax account';
      return <details key={id} className="fax-provider-option"><summary><strong>{provider.name}</strong><span>{label}</span></summary>
        <p>{!status?'Check setup to see whether this practice has an account.':!status.installed_accounts?
          'Your practice administrator needs to connect this provider’s account securely.':status.prepare_enabled_accounts?
          `${status.prepare_enabled_accounts} account${status.prepare_enabled_accounts===1?' is':'s are'} configured for draft preparation. Review the current account and recipient before use.`:
          'Open provider accounts to review permissions and activate an eligible fax account.'}</p>
        <p><strong>What you need: </strong>{provider.setup}</p>
        <p><strong>How it works: </strong>{provider.workflow}</p>
      </details>;
    })}</div>
    <details className="fax-other-provider"><summary>Another fax provider</summary>
      <p>A provider not listed here needs a CosmaBot integration before it can be connected. You can continue using its own app.</p>
    </details>
    {missing.length>0&&<div><h3>Setup still needed</h3><ul>{missing.map(item=><li key={item}>{item}</li>)}</ul></div>}
    <div className="fax-connection-actions">
      <button disabled={locked||loading} onClick={onRefresh}>Check fax setup</button>
      <button disabled={locked||unavailable} onClick={onSetup}>Review provider accounts</button>
      {onOpenWork&&<button className="team-primary" disabled={locked||workBlocked||!current||!ready} onClick={onOpenWork}>{workLabel}</button>}
    </div>
    <p>Fax work keeps the document, recipient, review and delivery status with the selected visit. Each send needs a separate approval.</p>
    <p className="team-fine">Checking setup does not verify the provider login or fax delivery. Received eFax requires separate inbound setup and human approval before downloading an image.</p>
  </section>;
}
