export type HostedWorkspaceConfiguration = Readonly<{
  client: "web" | "apple" | "desktop";
  dataMode: "synthetic" | "authorized_beta";
  apiOrigin: string;
  apiBase: string;
  pageOrigin: string;
}>;
export function exactHostedOrigin(value: unknown): value is string;
export function resolveHostedWorkspace(env: Record<string, unknown>): HostedWorkspaceConfiguration | null;
export function permittedHostedWorkspace(configuration: HostedWorkspaceConfiguration | null,
  base: string, page: string, signed?: boolean): boolean;
