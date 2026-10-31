export function resolveEnrollmentBuild(env: Record<string, string>): {
  version: number; kind: string; environment: string; source_commit: string;
  application_origin: string; enrollment_api_origin: string; clerk_issuer: string;
  account_only: boolean; clinical_workspace: boolean;
};
