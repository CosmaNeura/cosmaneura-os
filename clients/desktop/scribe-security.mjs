import { isAbsolute } from "node:path";
export const RENDERER_CONTENT_SECURITY_POLICY = [
    "default-src 'none'",
    "base-uri 'none'",
    "connect-src 'self'",
    "font-src 'self'",
    "form-action 'none'",
    "frame-ancestors 'none'",
    "img-src 'self' data:",
    "media-src 'none'",
    "object-src 'none'",
    "script-src 'self'",
    "style-src 'self'",
].join("; ");
export const PACKAGED_APP_SCHEME = Object.freeze({
    scheme: "app",
    privileges: Object.freeze({
        standard: true,
        secure: true,
        bypassCSP: false,
        allowServiceWorkers: false,
        supportFetchAPI: false,
        corsEnabled: false,
        codeCache: true,
    }),
});
/** Must run before creating windows or initializing any capture adapter. */
export function requireElectronSingleInstance(application) {
    const acquired = application.requestSingleInstanceLock();
    if (!acquired) {
        application.quit();
    }
    return acquired;
}
export function createSecureBrowserWindowOptions(preloadPath) {
    if (!isAbsolute(preloadPath)) {
        throw new Error("Electron preload path must be absolute");
    }
    return Object.freeze({
        show: false,
        webPreferences: Object.freeze({
            preload: preloadPath,
            contextIsolation: true,
            nodeIntegration: false,
            nodeIntegrationInWorker: false,
            nodeIntegrationInSubFrames: false,
            sandbox: true,
            webSecurity: true,
            allowRunningInsecureContent: false,
            webviewTag: false,
            devTools: false,
            navigateOnDragDrop: false,
        }),
    });
}
/** Apply immediately after BrowserWindow creation and before loading content. */
export function installElectronRendererSecurity(webContents, packagedEntryUrl) {
    const entry = new URL(packagedEntryUrl);
    if (entry.protocol !== "app:" ||
        entry.hostname !== "cosmas" ||
        entry.port !== "" ||
        entry.username !== "" ||
        entry.password !== "") {
        throw new Error("Renderer entry URL must use the packaged app://cosmas origin");
    }
    webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    webContents.on("will-attach-webview", (event) => event.preventDefault());
    for (const eventName of ["will-navigate", "will-redirect"]) {
        webContents.on(eventName, (event, destination) => {
            if (typeof destination !== "string" || destination !== entry.href) {
                event.preventDefault();
            }
        });
    }
    webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    webContents.session.setPermissionCheckHandler(() => false);
    webContents.session.on("will-download", (event) => event.preventDefault());
    webContents.session.webRequest.onHeadersReceived((details, callback) => {
        callback({
            responseHeaders: {
                ...details.responseHeaders,
                "Content-Security-Policy": [RENDERER_CONTENT_SECURITY_POLICY],
            },
        });
    });
}
