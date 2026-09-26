import { ClerkProvider } from "@clerk/react";
import { Component, useEffect, type ErrorInfo, type ReactNode } from "react";
import { notifyWorkspaceLifecycle } from "./workspace-lifecycle";
import { WORKSPACE_AUTHENTICATED_BUILD, WORKSPACE_BUILD } from "./workspace-api";
import { permittedSignedWorkspaceApi, permittedWorkspaceApi } from "./workspace-origin";
import { NativeAuthenticatedWorkspace } from "./NativeAuthenticatedWorkspace";
import { DesktopAuthenticatedWorkspace } from "./DesktopAuthenticatedWorkspace";
import { permittedDesktopWorkspaceApi } from "./workspace-origin";
import {hostedWorkspaceConfiguration, hostedWorkspaceRequested} from "./hosted-workspace";
import {permittedHostedWorkspace} from "../../clients/shared/hosted-workspace-config.mjs";
import {
  App,
  ClerkBetaApp,
  StatusScreen,
  resolveRuntimeMode,
  type AppRuntimeMode,
} from "./App";

type BetaFrontendConfiguration =
  | { configured: true; publishableKey: string }
  | {
      configured: false;
      reason: "missing_clerk_key" | "invalid_clerk_key" | "missing_api_base" | "invalid_api_base";
    };

export function resolveBetaFrontendConfiguration(
  publishableKey: string | undefined,
  apiBase: string | undefined,
): BetaFrontendConfiguration {
  const key = publishableKey?.trim();
  if (!key) return { configured: false, reason: "missing_clerk_key" };
  if (!/^pk_(?:test|live)_\S+$/.test(key)) {
    return { configured: false, reason: "invalid_clerk_key" };
  }

  const base = apiBase?.trim();
  if (!base) return { configured: false, reason: "missing_api_base" };
  try {
    const parsed = new URL(base);
    if (
      parsed.protocol !== "https:" ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash
    ) {
      return { configured: false, reason: "invalid_api_base" };
    }
  } catch {
    return { configured: false, reason: "invalid_api_base" };
  }

  return { configured: true, publishableKey: key };
}

export class WorkspaceRuntimeErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(_error: unknown) {
    return { failed: true };
  }

  componentDidCatch(_error: unknown, _info: ErrorInfo) {
    // Errors may contain private source text or credentials. Keep only a boolean.
    notifyWorkspaceLifecycle("failed");
  }

  render() {
    if (this.state.failed) {
      return (
        <StatusScreen
          title="Your workspace could not continue"
          detail="Close and reopen CosmasOS, then review saved work and unconfirmed requests before retrying. Unsaved edits may be missing; submitted work may still finish. If recording was active, check the recording indicator and review the interruption after reopening."
        />
      );
    }
    return this.props.children;
  }
}

const configuredRuntimeMode = resolveRuntimeMode(
  import.meta.env.VITE_COSMAS_ENV,
  import.meta.env.DEV,
);

type RuntimeAppProps = {
  runtimeMode?: AppRuntimeMode;
  clerkPublishableKey?: string;
  apiBase?: string;
  authenticatedWorkspace?: boolean;
  workspaceEnabled?: boolean;
};

function RuntimeReady({ children }: { children: ReactNode }) {
  useEffect(() => { notifyWorkspaceLifecycle("ready"); }, []);
  return children;
}

export function RuntimeApp(props: RuntimeAppProps) {
  return <WorkspaceRuntimeErrorBoundary>
    <RuntimeReady><RuntimeRoutes {...props}/></RuntimeReady>
  </WorkspaceRuntimeErrorBoundary>;
}

function RuntimeRoutes({
  runtimeMode = configuredRuntimeMode,
  clerkPublishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY,
  apiBase = import.meta.env.VITE_API_BASE,
  authenticatedWorkspace = WORKSPACE_AUTHENTICATED_BUILD,
  workspaceEnabled = WORKSPACE_BUILD,
}: RuntimeAppProps) {
  if (hostedWorkspaceRequested()) {
    const hosted = hostedWorkspaceConfiguration();
    if (!hosted || !workspaceEnabled || !authenticatedWorkspace || runtimeMode !== "early_adopter_beta" ||
        !apiBase || !permittedHostedWorkspace(hosted, apiBase, window.location.href)) {
      return <StatusScreen title="Workspace connection is not configured"
        detail="This installation needs its beta service and sign-in configuration. Contact your beta administrator." />;
    }
    let workspace: ReactNode;
    if (hosted.client === "desktop") workspace = <DesktopAuthenticatedWorkspace />;
    else if (hosted.client === "apple") workspace = <NativeAuthenticatedWorkspace />;
    else {
      const key = clerkPublishableKey?.trim();
      if (!key || !(hosted.dataMode === "synthetic" ? /^pk_(test|live)_\S+$/ : /^pk_live_\S+$/).test(key)) {
        return <StatusScreen title="Workspace login is not configured"
          detail="This installation needs its beta sign-in configuration. Contact your beta administrator." />;
      }
      workspace = <ClerkProvider publishableKey={key}><ClerkBetaApp workspace /></ClerkProvider>;
    }
    return <>{hosted.dataMode === "synthetic" && <p role="note" className="beta-environment-notice">
      Beta practice environment · Use invented data only.</p>}{workspace}</>;
  }
  if ((import.meta.env.VITE_WORKSPACE_NATIVE_AUTH_ENABLED === "true" ||
       import.meta.env.VITE_WORKSPACE_DESKTOP_AUTH_ENABLED === "true") && !authenticatedWorkspace) {
    return <StatusScreen title="Workspace login is not configured"
      detail="This build needs its approved native login and local API configuration." />;
  }
  if (authenticatedWorkspace) {
    if (import.meta.env.VITE_WORKSPACE_DESKTOP_AUTH_ENABLED === "true") {
      if (!workspaceEnabled || runtimeMode !== "synth_os" || !apiBase ||
          import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED !== "true" ||
          import.meta.env.VITE_WORKSPACE_NATIVE_AUTH_ENABLED === "true" ||
          import.meta.env.VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED === "true" ||
          !permittedDesktopWorkspaceApi(apiBase, window.location.href)) {
        return <StatusScreen title="Workspace login is not configured"
          detail="This build needs its approved native login and local API configuration." />;
      }
      return <DesktopAuthenticatedWorkspace />;
    }
    if (import.meta.env.VITE_WORKSPACE_NATIVE_AUTH_ENABLED === "true") {
      const page = new URL(window.location.href);
      if (!workspaceEnabled || runtimeMode !== "synth_os" || !apiBase ||
          import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED === "true" ||
          import.meta.env.VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED !== "true" ||
          page.protocol !== "capacitor:" || page.hostname !== "localhost" ||
          !!page.port || !!page.username || !!page.password ||
          !permittedSignedWorkspaceApi(apiBase, window.location.href, true)) {
        return <StatusScreen title="Workspace login is not configured"
          detail="This build needs its approved native login and local API configuration." />;
      }
      return <NativeAuthenticatedWorkspace />;
    }
    const key = clerkPublishableKey?.trim();
    const page = new URL(window.location.href);
    if (!workspaceEnabled || runtimeMode !== "synth_os" || !key || !/^pk_test_\S+$/.test(key) || !apiBase ||
        !permittedWorkspaceApi(apiBase, false, window.location.href) ||
        !permittedWorkspaceApi(page.origin, false, window.location.href) ||
        import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED === "true") {
      return <StatusScreen title="Workspace login is not configured"
        detail="This local synthetic build needs its approved test login and local API configuration." />;
    }
    return <ClerkProvider publishableKey={key}>
      <ClerkBetaApp workspace />
    </ClerkProvider>;
  }
  if (runtimeMode !== "early_adopter_beta") {
    return <App runtimeMode={runtimeMode} />;
  }

  const configuration = resolveBetaFrontendConfiguration(clerkPublishableKey, apiBase);
  if (!configuration.configured) {
    return (
      <StatusScreen
        title="Beta login is not configured"
        detail="This build is intentionally offline. It will not contact Clerk or the API until the approved beta configuration is installed."
      />
    );
  }

  return (
    <ClerkProvider publishableKey={configuration.publishableKey}>
      <ClerkBetaApp />
    </ClerkProvider>
  );
}
