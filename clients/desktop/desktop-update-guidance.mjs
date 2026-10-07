/** Manual release guidance until a qualified desktop distribution channel exists. */
export function desktopUpdateDetail(config) {
  const version=typeof config.appVersion==='string'?config.appVersion:'unknown';
  const build=typeof config.buildNumber==='string'?config.buildNumber:'unknown';
  const commit=config.sourceProvenance?.commit;
  const source=typeof commit==='string'&&/^[a-f0-9]{40}$/.test(commit)?commit.slice(0,12):'not recorded';
  return `Installed version ${version} (build ${build}). Source ${source}.\n\nDesktop updates are supplied as a matching CosmaBot application package by your practice. Keep saved drafts and recordings, quit CosmaBot, then install the supplied update. Reopen and check the workspace connection.\n\nAutomatic downloads are not available. If this package is current, your practice service needs the matching update.`;
}
export function desktopMenuTemplate({app,dialog,config}) {
  return [{label:'CosmaBot',submenu:[{role:'about'},{label:'Update CosmaBot…',click:()=>dialog.showMessageBox({type:'info',buttons:['OK'],title:'Update CosmaBot',message:'Use the matching desktop update package.',detail:desktopUpdateDetail(config)})},{type:'separator'},{role:'hide'},{role:'hideOthers'},{role:'unhide'},{type:'separator'},{label:'Quit CosmaBot',accelerator:'CommandOrControl+Q',click:()=>app.quit()}]},
    {label:'Edit',submenu:[{role:'undo'},{role:'redo'},{type:'separator'},{role:'cut'},{role:'copy'},{role:'paste'},{role:'selectAll'}]},
    {label:'Window',submenu:[{role:'minimize'},{role:'zoom'},{role:'front'}]}];
}
