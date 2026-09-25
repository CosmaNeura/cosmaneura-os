"""Closed native-navigation composition helpers. No network, launches or credentials."""

import re
from pathlib import Path

ORIGIN = re.compile(r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")


def validate_origin(value: str) -> str:
    if value == "":
        return value
    if not isinstance(value, str) or len(value) > 255 or ORIGIN.fullmatch(value) is None:
        raise ValueError("Cosmaneura requires an exact canonical HTTPS web origin.")
    return value


def compose_preload(root: Path, destination: Path) -> None:
    marker = "// @cosmaneura-navigation-dom@"
    source = destination.read_text()
    if source.count(marker) != 1:
        raise ValueError("Native navigation preload marker changed.")
    common = (root / "clients/shared/cosmaneura-navigation-dom.js").read_text()
    wrapper = """(() => {
const available = ipcRenderer.sendSync('cosmas:cosmaneura:capability:v1') === true;
const google = ipcRenderer.sendSync('cosmas:google:capability:v1') === true;
contextBridge.exposeInMainWorld('cosmasGoogleNavigation', Object.freeze({version:1,available:google,mode:'trusted-click'}));
const microsoft = ipcRenderer.sendSync('cosmas:microsoft:capability:v1') === true;
contextBridge.exposeInMainWorld('cosmasMicrosoftNavigation', Object.freeze({version:1, available:microsoft, mode:'trusted-click'}));
const scheduling = ipcRenderer.sendSync('cosmas:scheduling:capability:v1') === true;
contextBridge.exposeInMainWorld('cosmasSchedulingNavigation', Object.freeze({version: 1, available: scheduling, mode: 'trusted-click'}));
contextBridge.exposeInMainWorld('cosmasCosmaneuraNavigation', Object.freeze({version: 1, available, mode: 'trusted-click'}));
COMMON
installCosmaneuraTrustedClicks(available || scheduling || microsoft || google, request => ipcRenderer.invoke('cosmas:cosmaneura:open:v1', request));
})();""".replace("COMMON", common)
    destination.write_text(source.replace(marker, wrapper))


def validate_scheduling(client_id: str, callback_uri: str) -> None:
    if not client_id and not callback_uri:
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com", client_id):
        raise ValueError("An exact Scheduling Google web client ID is required.")
    suffix = "/connections/scheduling/google/callback"
    if not callback_uri.endswith(suffix) or not callback_uri[:-len(suffix)]:
        raise ValueError("The fixed Scheduling callback URI is required.")
    validate_origin(callback_uri[:-len(suffix)])


def validate_microsoft(tenant_id: str, client_id: str, callback_uri: str) -> None:
    if not tenant_id and not client_id and not callback_uri:
        return
    uuid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    if not re.fullmatch(uuid, tenant_id) or not re.fullmatch(uuid, client_id):
        raise ValueError("Exact Microsoft tenant and web client UUIDs are required.")
    suffix = "/connections/microsoft/callback"
    if not callback_uri.endswith(suffix) or not callback_uri[:-len(suffix)]:
        raise ValueError("The fixed Microsoft callback URI is required.")
    validate_origin(callback_uri[:-len(suffix)])


def validate_google(client_id: str, callback_uri: str) -> None:
    if not client_id and not callback_uri:
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", client_id):
        raise ValueError("An exact Gmail Google web client ID is required.")
    suffix = "/connections/google/callback"
    if not callback_uri.endswith(suffix) or not callback_uri[:-len(suffix)]:
        raise ValueError("The fixed Gmail callback URI is required.")
    validate_origin(callback_uri[:-len(suffix)])
