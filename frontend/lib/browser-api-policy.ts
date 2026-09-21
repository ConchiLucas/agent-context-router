const SAFE_BROWSER_POST_PATHS = [
  /^\/api\/data-sources\/[^/]+\/reveal-password$/,
  /^\/api\/data-sources\/[^/]+\/test$/,
  /^\/api\/mcp\/integration\/tests$/,
  /^\/api\/workspaces\/[^/]+\/prepare-preview(?:\?.*)?$/,
  /^\/api\/workspaces\/[^/]+\/shared-files\/(restore|publish)$/,
  /^\/api\/workspaces\/[^/]+\/scripts\/sync$/,
  /^\/api\/workspaces\/[^/]+\/containers\/bulk-action$/,
  /^\/api\/workspaces\/[^/]+\/host-runtime\/actions$/,
  /^\/api\/workspaces\/[^/]+\/relation-records\/search$/,
  /^\/api\/projects\/[^/]+\/runtime-config\/(fast|full)\/execute$/,
  /^\/api\/interface-forwarding\/(import|environments|identities)$/,
  /^\/api\/interface-forwarding\/browser-captures$/,
  /^\/api\/interface-forwarding\/interfaces\/[^/]+\/execute$/,
  /^\/api\/value-mappings$/,
  /^\/api\/value-mappings\/[^/]+\/preview$/,
  /^\/api\/managed-scripts\/[^/]+\/autostart$/,
];

export function isBrowserApiRequestAllowed(
  path: string,
  method = "GET",
): boolean {
  const normalizedMethod = method.toUpperCase();
  if (["GET", "HEAD", "OPTIONS"].includes(normalizedMethod)) {
    return true;
  }
  if (normalizedMethod === "POST") {
    return SAFE_BROWSER_POST_PATHS.some((pattern) => pattern.test(path));
  }
  if (normalizedMethod === "PUT") {
    if (/^\/api\/interface-forwarding\/interfaces\/[^/]+\/semantics$/.test(path)) {
      return true;
    }
    if (
      /^\/api\/interface-forwarding\/(services|environments|identities)\/[^/]+$/.test(
        path,
      )
    ) {
      return true;
    }
    if (/^\/api\/value-mappings\/[^/]+$/.test(path)) {
      return true;
    }
    return /^\/api\/system-guides\/[^/]+\/content$/.test(path);
  }
  if (normalizedMethod === "DELETE") {
    return (
      /^\/api\/interface-forwarding\/(services|interfaces|environments|identities)\/[^/]+$/.test(
        path,
      ) || /^\/api\/value-mappings\/[^/]+$/.test(path)
    );
  }
  return false;
}

export function assertBrowserApiRequestAllowed(
  path: string,
  method = "GET",
): void {
  if (isBrowserApiRequestAllowed(path, method)) return;
  throw new Error(
    "这个配置不能从管理界面修改；请由本机 AI 或运维命令执行",
  );
}
