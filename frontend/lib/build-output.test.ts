import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import packageJson from "../package.json";

test("production build uses an output directory isolated from the dev server", async () => {
  process.env.CONTEXT_ROUTER_FRONTEND_DIST_DIR = ".next-test-build";
  const { default: nextConfig } = await import("../next.config");

  assert.equal(nextConfig.distDir, undefined);
  assert.equal(packageJson.scripts.build, "sh scripts/build-isolated.sh");

  const buildScript = await readFile(
    new URL("../scripts/build-isolated.sh", import.meta.url),
    "utf8"
  );
  assert.match(buildScript, /cd "\$build_dir"/);
});

test("Docker build writes Next output in its working directory", () => {
  assert.equal(packageJson.scripts["build:docker"], "next build");
});
