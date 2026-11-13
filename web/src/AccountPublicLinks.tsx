import {accountPublicLinksHiddenOnClient,privacyPolicyUrl,supportUrl} from './account-public-links';

/** External Privacy Policy and Support links when configured and openable. */
export function AccountPublicLinks(){
  if(accountPublicLinksHiddenOnClient())return null;
  const privacy=privacyPolicyUrl();
  const support=supportUrl();
  if(!privacy&&!support)return null;
  return <nav className="account-public-links" aria-label="Help and legal">
    {privacy&&<a href={privacy} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Privacy Policy</a>}
    {support&&<a href={support} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Support</a>}
  </nav>;
}
