import assert from "node:assert/strict";
import test from "node:test";

import { groupInterfaceForwardingIdentities } from "./interface-forwarding-identities";
import type {
  InterfaceForwardingAddress,
  InterfaceForwardingEnvironment,
  InterfaceForwardingIdentity,
} from "./types";

const address = (id: string, name: string, serviceName: string): InterfaceForwardingAddress => ({
  id,
  workspace_id: "workspace-1",
  environment_key: "uat",
  service_id: `service-${id}`,
  service_name: serviceName,
  name,
  base_url: `http://example.test/${serviceName}`,
  created_at: "2026-08-22T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
});

const identity = (
  id: string,
  environmentId: string,
  loginAccount: string,
  roleName: string,
): InterfaceForwardingIdentity => ({
  id,
  workspace_id: "workspace-1",
  environment_id: environmentId,
  environment_key: "uat",
  environment_name: "UAT",
  login_account: loginAccount,
  role_name: roleName,
  request_header: "{}",
});

test("groups one account into one card with all service mappings", () => {
  const environment: InterfaceForwardingEnvironment = {
    workspace_id: "workspace-1",
    environment_key: "uat",
    display_name: "UAT",
    sort_order: 1,
    is_default: false,
    addresses: [
      address("mtp-admin", "运营端", "c12-mtp"),
      address("portal-admin", "运营端", "c12-portal"),
      address("mtp-portal", "门户端", "c12-mtp"),
    ],
  };

  const groups = groupInterfaceForwardingIdentities(environment, [
    identity("1", "mtp-admin", "superAdmin", "运营端管理员"),
    identity("2", "portal-admin", "superAdmin", "运营端管理员"),
    identity("3", "mtp-portal", "15181319157", "货主"),
  ]);

  assert.equal(groups.length, 2);
  assert.equal(groups.find((item) => item.loginAccount === "superAdmin")?.mappings.length, 2);
  assert.equal(groups.find((item) => item.loginAccount === "15181319157")?.roleName, "货主");
});

test("ignores identities belonging to another workspace environment", () => {
  const environment: InterfaceForwardingEnvironment = {
    workspace_id: "workspace-1",
    environment_key: "uat",
    display_name: "UAT",
    sort_order: 1,
    is_default: false,
    addresses: [address("uat-mtp", "运营端", "c12-mtp")],
  };

  const groups = groupInterfaceForwardingIdentities(environment, [
    identity("1", "uat-mtp", "superAdmin", "运营端管理员"),
    identity("2", "local-mtp", "localAdmin", "本地管理员"),
  ]);

  assert.deepEqual(groups.map((item) => item.loginAccount), ["superAdmin"]);
});

test("keeps different roles of the same login account in separate cards", () => {
  const environment: InterfaceForwardingEnvironment = {
    workspace_id: "workspace-1",
    environment_key: "uat",
    display_name: "UAT",
    sort_order: 1,
    is_default: false,
    addresses: [
      address("mtp-portal", "门户端", "c12-mtp"),
      address("portal-portal", "门户端", "c12-portal"),
    ],
  };

  const groups = groupInterfaceForwardingIdentities(environment, [
    identity("1", "mtp-portal", "15181319157", "货主"),
    identity("2", "portal-portal", "15181319157", "货主"),
    identity("3", "mtp-portal", "15181319157", "承运商"),
    identity("4", "portal-portal", "15181319157", "承运商"),
  ]);

  assert.equal(groups.length, 2);
  assert.deepEqual(groups.map((item) => item.roleName).sort(), ["承运商", "货主"]);
  assert.ok(groups.every((item) => item.mappings.length === 2));
});
