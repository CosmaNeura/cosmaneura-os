export function WorkspaceNavIcon({page}:{page:'home'|'visits'|'work'|'settings'}) {
  const paths={
    home:<><path d="m3 10 9-7 9 7"/><path d="M5 9v12h5v-7h4v7h5V9"/></>,
    visits:<><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
    work:<><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 5V3h8v2M3 11h18M10 11v3h4v-3"/></>,
    settings:<><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/></>,
  };
  return <svg className="team-nav-icon" aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{paths[page]}</svg>;
}
