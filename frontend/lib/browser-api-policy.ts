const SAFE_BROWSER_POST_PATHS = [
  /^\/api\/data-sources\/[^/]+\/reveal-password$/,
  /^\/api\/data-sources\/[^/]+\/test$/,
  /^\/api\/mcp\/integration\/tests$/,
  /^\/api\/workspaces\/[^/]+\/prepare-preview(?:\?.*)?$/,
  /^\/api\/workspaces\/[^/]+\/refresh$/,
];

export function isBrowserApiRequestAllowed(
  path: string,
  method = "GET",
): boolean {
  const normalizedMethod = method.toUpperCase();
  if (["GET", "HEAD", "OPTIONS"].includes(normalizedMethod)) {
    return true;
  }
  if (normalizedMethod !== "POST") return false;
  return SAFE_BROWSER_POST_PATHS.some((pattern) => pattern.test(path));
}

export function assertBrowserApiRequestAllowed(
  path: string,
  method = "GET",
): void {
  if (isBrowserApiRequestAllowed(path, method)) return;
  throw new Error(
    "管理界面只提供查看；配置变更请由本机 AI 或运维命令执行",
  );
}
