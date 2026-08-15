import assert from "node:assert/strict";
import test from "node:test";

import {
  listAllTableRelationTables,
  listTableRelationWarnings,
  getProjectTableRelationSqlWhitelist,
  rebuildProjectTableRelations,
  rebuildTableRelations,
  refreshWorkspace,
  replaceProjectTableRelationSqlWhitelist,
} from "./api";

test("refreshWorkspace posts to the workspace refresh endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedMethod = "";
  globalThis.fetch = async (input, init) => {
    requestedUrl = String(input);
    requestedMethod = init?.method ?? "GET";
    return new Response(
      JSON.stringify({ id: "workspace-1", name: "Workspace" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const result = await refreshWorkspace("workspace-1");
    assert.equal(
      requestedUrl,
      "http://127.0.0.1:49173/api/workspaces/workspace-1/refresh",
    );
    assert.equal(requestedMethod, "POST");
    assert.equal(result.id, "workspace-1");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rebuildTableRelations always requests a full manual rebuild", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedMethod = "";
  globalThis.fetch = async (input, init) => {
    requestedUrl = String(input);
    requestedMethod = init?.method ?? "GET";
    return new Response(
      JSON.stringify({
        workspace_id: "workspace-1",
        status: "ready",
        project_count: 1,
        ready_project_count: 1,
        sql_file_count: 1,
        statement_count: 1,
        relation_count: 1,
        warning_count: 0,
        warnings: [],
        config_revision: 1,
        eligible_project_count: 1,
        configured_project_count: 1,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await rebuildTableRelations("workspace-1");
    assert.equal(
      requestedUrl,
      "http://127.0.0.1:49173/api/workspaces/workspace-1/table-relations/rebuild",
    );
    assert.equal(requestedMethod, "POST");
    assert.equal(new URL(requestedUrl).search, "");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rebuildProjectTableRelations targets one project through the route", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedMethod = "";
  globalThis.fetch = async (input, init) => {
    requestedUrl = String(input);
    requestedMethod = init?.method ?? "GET";
    return new Response(
      JSON.stringify({
        workspace_id: "workspace-1",
        status: "ready",
        project_count: 1,
        ready_project_count: 1,
        sql_file_count: 1,
        statement_count: 1,
        relation_count: 1,
        warning_count: 0,
        warnings: [],
        config_revision: 1,
        eligible_project_count: 1,
        configured_project_count: 1,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await rebuildProjectTableRelations("workspace-1", "project with space");
    assert.equal(
      requestedUrl,
      "http://127.0.0.1:49173/api/workspaces/workspace-1/table-relations/projects/project%20with%20space/rebuild",
    );
    assert.equal(requestedMethod, "POST");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("project SQL whitelist uses the project-scoped read and replace endpoint", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; method: string; body?: BodyInit | null }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: init?.body,
    });
    return new Response(
      JSON.stringify({
        workspace_id: "workspace-1",
        project_id: "project-1",
        project_name: "c12-mtp",
        paths: ["sql/custom.sql"],
        suggested_paths: [],
        automatic_rules: [],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await getProjectTableRelationSqlWhitelist("workspace-1", "project-1");
    await replaceProjectTableRelationSqlWhitelist(
      "workspace-1",
      "project-1",
      ["sql/custom.sql"],
    );
    const expected = "http://127.0.0.1:49173/api/workspaces/workspace-1/table-relations/projects/project-1/sql-whitelist";
    assert.equal(calls[0]?.url, expected);
    assert.equal(calls[0]?.method, "GET");
    assert.equal(calls[1]?.url, expected);
    assert.equal(calls[1]?.method, "PUT");
    assert.equal(calls[1]?.body, JSON.stringify({ paths: ["sql/custom.sql"] }));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("listAllTableRelationTables follows every server page", async () => {
  const originalFetch = globalThis.fetch;
  const requestedOffsets: string[] = [];
  globalThis.fetch = async (input) => {
    const url = new URL(String(input));
    const offset = url.searchParams.get("offset") ?? "0";
    requestedOffsets.push(offset);
    const firstPage = offset === "0";
    return new Response(
      JSON.stringify({
        workspace_id: "workspace-1",
        total: 201,
        limit: 200,
        offset: Number(offset),
        has_more: firstPage,
        next_offset: firstPage ? 200 : null,
        tables: (firstPage ? Array.from({ length: 200 }, (_, index) => index) : [200]).map(
          (index) => ({
            project_id: "project-1",
            project_name: "project",
            database_key: "database",
            schema_name: "schema",
            table_name: `table_${String(index + 1).padStart(3, "0")}`,
            relation_count: 1,
          }),
        ),
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const result = await listAllTableRelationTables("workspace-1");
    assert.deepEqual(requestedOffsets, ["0", "200"]);
    assert.equal(result.total, 201);
    assert.equal(result.tables.length, 201);
    assert.equal(result.tables.at(-1)?.table_name, "table_201");
    assert.equal(result.has_more, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("listTableRelationWarnings sends the diagnostic disposition", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  globalThis.fetch = async (input) => {
    requestedUrl = String(input);
    return new Response(
      JSON.stringify({
        workspace_id: "workspace-1",
        total: 0,
        attention_total: 0,
        expected_total: 3,
        limit: 100,
        offset: 0,
        categories: [],
        projects: [],
        warnings: [],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await listTableRelationWarnings("workspace-1", {
      disposition: "expected",
      projectId: "project-1",
      query: "migration",
    });
    const url = new URL(requestedUrl);
    assert.equal(url.searchParams.get("disposition"), "expected");
    assert.equal(url.searchParams.get("project_id"), "project-1");
    assert.equal(url.searchParams.get("q"), "migration");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
