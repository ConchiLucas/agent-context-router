const SAFE_BROWSER_POST_PATHS = [
  /^\/api\/data-sources\/[^/]+\/reveal-password$/,
  /^\/api\/data-sources\/[^/]+\/test$/,
  /^\/api\/mcp\/integration\/tests$/,
  /^\/api\/workspaces\/[^/]+\/prepare-preview(?:\?.*)?$/,
  /^\/api\/workspaces\/[^/]+\/refresh$/,
  /^\/api\/workspaces\/reload-local-mapping$/,
  /^\/api\/workspaces\/[^/]+\/shared-files\/(restore|publish)$/,
  /^\/api\/workspaces\/[^/]+\/containers\/bulk-action$/,
  /^\/api\/projects\/[^/]+\/runtime-config\/(fast|full)\/execute$/,
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
    return /^\/api\/system-guides\/[^/]+\/content$/.test(path);
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
