import {app, BrowserWindow, dialog, ipcMain, protocol, session, shell, safeStorage, powerMonitor} from 'electron';
import {readFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {createSecureBrowserWindowOptions, installElectronRendererSecurity,
  PACKAGED_APP_SCHEME, RENDERER_CONTENT_SECURITY_POLICY, requireElectronSingleInstance} from './scribe-security.mjs';
import {enforceNoPhiDiagnosticPolicy} from './scribe-diagnostics.mjs';
import {resolveStaticAsset} from './static-assets.mjs';
import {preparePackagedAuthHelper} from './spawn-auth-helper.mjs';
import {createAuthAccessStore} from './auth-access-store.mjs';
import {createDesktopAuthSession} from './auth-session.mjs';
import {installAuthIpc} from './auth-ipc.mjs';
import {installCosmaneuraNavigation} from './cosmaneura-navigation.mjs';
import {proxyAuthenticatedWorkspaceRequest} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace} from './local-auth-http.mjs';
import {createHostedWorkspaceTransport, exactHostedApiOrigin} from './hosted-auth-http.mjs';
import {captureContentSecurityPolicy, privateDocumentContentSecurityPolicy, installCaptureContentSecurityPolicy} from './capture-content-security.mjs';
import {installMicrophonePermissions} from './microphone-permissions.mjs';
import {prepareDesktopState} from './installation-state.mjs';
import {installDesktopCloseProtection, cleanupOnConfirmedQuit} from './close-protection.mjs';

import {createDesktopFailureHandler, destroyDesktopWorkspace, installDesktopLastWindowPolicy} from './startup-recovery.mjs';
import {installDesktopWorkspaceLifecycle} from './workspace-lifecycle.mjs';
import {preparePackagedDesktopCapture} from './native-capture-package.mjs';
import {validateOperationalNativeIdentity} from './native-identity-config.mjs';

const root = fileURLToPath(new URL('.', import.meta.url));
let window, auth, captureHost, disposeIpc, disposeLifecycle, disposeNavigation, failureClosing = false;
const cleanup = () => {
  // Failure cleanup retires acquisition immediately. Saved native proofs survive
  // unavailable credentials and are recovered before a later recording start.
  void captureHost?.close().catch(() => {});
  const lifecycle = disposeLifecycle, ipc = disposeIpc, navigation = disposeNavigation, session = auth;
  disposeLifecycle = undefined; disposeIpc = undefined; disposeNavigation = undefined; auth = undefined;
  // Each capability closes independently even if another teardown fails.
  try { lifecycle?.(); } catch { /* No private diagnostics. */ }
  try { ipc?.(); } catch { /* Continue closing auth. */ }
  try { navigation?.(); } catch { /* Continue closing auth. */ }
  try { session?.close(); } catch { /* The failure path also destroys the renderer. */ }
};
const fail = createDesktopFailureHandler({app, dialog,
  cleanup: () => { failureClosing = true; cleanup(); },
  closeWorkspace: options => destroyDesktopWorkspace(window, options),
});
installDesktopLastWindowPolicy(app, () => failureClosing);
let config, stateDirectory, contentSecurityPolicy, workspaceTransport, startupFailed=false;
try {
  config = JSON.parse(await readFile(join(root, 'synthetic-build.json'), 'utf8'));
  const hosted = config.mode === 'hosted-beta-authenticated';
  if ((hosted ? !exactHostedApiOrigin(config.apiOrigin) || !['synthetic','authorized_beta'].includes(config.dataMode) :
      config.mode !== 'local-synthetic-authenticated' || config.apiOrigin !== 'http://127.0.0.1:8046') ||
      config.nativeAuthEnabled !== true) throw new Error('Invalid desktop build');
  workspaceTransport = hosted ? createHostedWorkspaceTransport(config.apiOrigin) : fetchLocalAuthenticatedWorkspace;
  enforceNoPhiDiagnosticPolicy(app.commandLine, process.argv, process.execArgv);
  contentSecurityPolicy = privateDocumentContentSecurityPolicy(captureContentSecurityPolicy(RENDERER_CONTENT_SECURITY_POLICY, config.captureUploadOrigins));
  // Validate compatibility before Electron opens a persistent session or native helper.
  stateDirectory = await prepareDesktopState(config, app.getPath('appData'), process.versions.electron);
  app.setName(config.nativeIdentity ? 'CosmaBot' : hosted ? 'CosmasOS Beta' : 'CosmasOS Synth');app.setPath('userData',stateDirectory);app.setPath('sessionData',stateDirectory);
  protocol.registerSchemesAsPrivileged([{...PACKAGED_APP_SCHEME,
    privileges: {...PACKAGED_APP_SCHEME.privileges,supportFetchAPI:true,corsEnabled:true}}]);
} catch { startupFailed=true; }
// Never await readiness at ESM scope: Electron waits for module evaluation first.
if (startupFailed) void fail('startup');
else if (requireElectronSingleInstance(app)) void app.whenReady().then(bootstrap).catch(() => fail('startup'));
cleanupOnConfirmedQuit(app,cleanup,{beforeCleanup:()=>captureHost?.close(),onFailure:()=>{
  const choice=dialog.showMessageBoxSync({type:'warning',buttons:['Keep open','Quit and recover later'],defaultId:0,cancelId:0,
    title:'Recording shutdown incomplete',message:'The recording could not finish closing.',
    detail:'Keep the app open to retry. If you quit, saved audio is retained; review the interruption after reopening.',noLink:true});
  if(choice===1){cleanup();app.exit(0);}
}});

async function bootstrap() {
  await mkdir(stateDirectory, {recursive: true, mode: 0o700});
  const createHelper = async options => (await preparePackagedAuthHelper(root, app.getPath('temp')))(options);
  auth = await createDesktopAuthSession({enabled: true, createHelper, accessStore: createAuthAccessStore(stateDirectory)});
  // Capture ciphertext and nonextractable IndexedDB keys must survive a process restart.
  const partition = config.installation?.rendererPartition ?? 'persist:cosmasos-authenticated-local';
  const rendererSession = session.fromPartition(partition);
  rendererSession.protocol.handle('app', async request => {
    if (new URL(request.url).pathname.startsWith('/api/')) {
      if (!auth) return new Response('{"detail":"Desktop workspace request unavailable"}', {status: 401,
        headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'}});
      return proxyAuthenticatedWorkspaceRequest(request, auth, workspaceTransport, config.apiOrigin);
    }
    const asset = resolveStaticAsset(request.url, root);
    if (!asset || request.method !== 'GET') return new Response(null, {status: 404});
    return new Response(await readFile(asset.path), {headers: {'Content-Type': asset.contentType,
      'Content-Security-Policy': contentSecurityPolicy, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}});
  });
  const secure = createSecureBrowserWindowOptions(join(root, 'auth-preload.cjs'));
  window = new BrowserWindow({...secure, width: 1380, height: 900, minWidth: 360,
    title: 'CosmaBot', backgroundColor: '#f7f8f6', autoHideMenuBar: true,
    webPreferences: {...secure.webPreferences, partition}});
  installElectronRendererSecurity(window.webContents, 'app://cosmas/index.html');
  installDesktopCloseProtection(window, dialog);
  installCaptureContentSecurityPolicy(rendererSession.webRequest, contentSecurityPolicy);
  installMicrophonePermissions(window.webContents, auth, config.microphoneCaptureEnabled);
  disposeIpc = installAuthIpc(ipcMain, window.webContents, auth);
  if(config.nativeCaptureEnabled===true){
    if(config.mode!=='hosted-beta-authenticated'||!['synthetic','authorized_beta'].includes(config.dataMode))throw new Error('Desktop recording unavailable');
    validateOperationalNativeIdentity(config.nativeIdentity,'desktop',config.apiOrigin);
    const native=await preparePackagedDesktopCapture(root);
    const {installWorkspaceDesktopCapture}=await import('./workspace-native-capture.mjs');
    captureHost=installWorkspaceDesktopCapture({auth,ipc:ipcMain,renderer:window.webContents,directory:stateDirectory,
      apiOrigin:config.apiOrigin,protection:safeStorage,uploadOrigins:config.captureUploadOrigins,...native,
      request:request=>proxyAuthenticatedWorkspaceRequest(request,auth,workspaceTransport,config.apiOrigin),
      isSessionActive:()=>auth?.snapshot().phase==='ready'&&['active','idle'].includes(powerMonitor.getSystemIdleState(1))});
  }
  disposeNavigation = installCosmaneuraNavigation({ipcMain, renderer: window.webContents, auth,
    webOrigin: config.cosmaneuraWebOrigin ?? '', schedulingClientId: config.schedulingGoogleClientId ?? '',
    schedulingCallbackUri: config.schedulingGoogleCallbackUri ?? '',
    googleClientId:config.googleConnectionClientId??'',googleCallbackUri:config.googleConnectionCallbackUri??'', microsoftTenantId:config.microsoftConnectionTenantId??'',microsoftClientId:config.microsoftConnectionClientId??'',microsoftCallbackUri:config.microsoftConnectionCallbackUri??'', openExternal: href => shell.openExternal(href)});
  disposeLifecycle = installDesktopWorkspaceLifecycle({ipcMain, window, fail});
  window.on('closed', () => { window = null; if (!failureClosing) app.quit(); });
  window.once('ready-to-show', () => window.show());
  await window.loadURL('app://cosmas/index.html');
}
