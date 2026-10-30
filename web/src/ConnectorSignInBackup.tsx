import './provider-connection-portal.css';

/** Disabled vendor sign-in. Shown only when the in-app connector is absent. */
export function ConnectorSignInBackup({name}:{name:string}) {
  return <section className="provider-portal-backup" aria-label="Sign-in portal backup">
    <h3>Sign-in portal</h3>
    <p role="status">Backup only. No vendor sign-in is started from CosmaBot until an administrator enables the {name} connector.</p>
    <button className="team-primary" type="button" disabled>Not available in this app</button>
    <p className="provider-portal-access">Ask your practice administrator to make {name} available in this app. The signed-in CosmaBot session is what opens this work.</p>
  </section>;
}
