import {app, BrowserWindow, dialog, ipcMain, protocol, session} from 'electron';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {createSecureBrowserWindowOptions, installElectronRendererSecurity,
  PACKAGED_APP_SCHEME, RENDERER_CONTENT_SECURITY_POLICY, requireElectronSingleInstance} from './scribe-security.mjs';
import {enforceNoPhiDiagnosticPolicy} from './scribe-diagnostics.mjs';
import {proxyWorkspaceRequest} from './api-proxy.mjs';
import {resolveStaticAsset} from './static-assets.mjs';
import {installDesktopCloseProtection, cleanupOnConfirmedQuit} from './close-protection.mjs';

import {createDesktopFailureHandler, destroyDesktopWorkspace, installDesktopLastWindowPolicy} from './startup-recovery.mjs';
import {installDesktopWorkspaceLifecycle} from './workspace-lifecycle.mjs';

const root = fileURLToPath(new URL('.', import.meta.url));
let config, window, disposeLifecycle, startupFailed = false, failureClosing = false;
const cleanup = () => { const dispose = disposeLifecycle; disposeLifecycle = undefined; dispose?.(); };
const fail = createDesktopFailureHandler({app, dialog,
  cleanup: () => { failureClosing = true; cleanup(); },
  closeWorkspace: options => destroyDesktopWorkspace(window, options),
});
installDesktopLastWindowPolicy(app, () => failureClosing);
try {
  config=JSON.parse(await readFile(join(root,'synthetic-build.json'),'utf8'));
  if(config.mode!=='local-synthetic'||config.apiOrigin!=='http://127.0.0.1:8018')throw new Error('Invalid synthetic desktop build');
  app.setName('CosmasOS Synth');app.setPath('userData',config.stateDirectory);
  enforceNoPhiDiagnosticPolicy(app.commandLine,process.argv,process.execArgv);
  protocol.registerSchemesAsPrivileged([{...PACKAGED_APP_SCHEME,
    privileges:{...PACKAGED_APP_SCHEME.privileges,supportFetchAPI:true,corsEnabled:true}}]);
} catch { startupFailed=true; }
if(startupFailed)void fail('startup');
else if(requireElectronSingleInstance(app))void app.whenReady().then(bootstrap).catch(()=>fail('startup'));
cleanupOnConfirmedQuit(app, cleanup);

async function bootstrap() {
  const rendererSession = session.fromPartition('cosmasos-synthetic');
  rendererSession.protocol.handle('app', async request => {
    if (new URL(request.url).pathname.startsWith('/api/')) return proxyWorkspaceRequest(request);
    const asset = resolveStaticAsset(request.url, root);
    if (!asset || request.method !== 'GET') return new Response(null, {status: 404});
    return new Response(await readFile(asset.path), {headers: {
      'Content-Type': asset.contentType,
      'Content-Security-Policy': RENDERER_CONTENT_SECURITY_POLICY,
      'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    }});
  });
  const secure = createSecureBrowserWindowOptions(join(root, 'preload.cjs'));
  window = new BrowserWindow({...secure, width: 1380, height: 900, minWidth: 360,
    title: 'CosmasOS · Synthetic Beta', backgroundColor: '#f7f8f6', autoHideMenuBar: true,
    webPreferences: {...secure.webPreferences, partition: 'cosmasos-synthetic'}});
  installElectronRendererSecurity(window.webContents, 'app://cosmas/index.html');
  installDesktopCloseProtection(window, dialog);
  disposeLifecycle = installDesktopWorkspaceLifecycle({ipcMain, window, fail});
  window.on('closed', () => { window = null; if (!failureClosing) app.quit(); });
  window.once('ready-to-show', () => window.show());
  await window.loadURL('app://cosmas/index.html');
}
