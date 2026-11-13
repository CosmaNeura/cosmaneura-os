import {privacyPolicyUrl,supportUrl} from './account-public-links';

/** External Privacy Policy and Support links for the Account screen. */
export function AccountPublicLinks(){
  return <nav className="account-public-links" aria-label="Help and legal">
    <a href={privacyPolicyUrl()} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Privacy Policy</a>
    <a href={supportUrl()} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Support</a>
  </nav>;
}
