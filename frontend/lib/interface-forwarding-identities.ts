import type {
  InterfaceForwardingAddress,
  InterfaceForwardingEnvironment,
  InterfaceForwardingIdentity,
} from "@/lib/types";

export interface InterfaceForwardingIdentityMapping {
  identity: InterfaceForwardingIdentity;
  address: InterfaceForwardingAddress;
}

export interface InterfaceForwardingIdentityGroup {
  key: string;
  loginAccount: string;
  roleName: string;
  mappings: InterfaceForwardingIdentityMapping[];
}

export function groupInterfaceForwardingIdentities(
  environment: InterfaceForwardingEnvironment,
  identities: InterfaceForwardingIdentity[],
): InterfaceForwardingIdentityGroup[] {
  const addresses = new Map(environment.addresses.map((address) => [address.id, address]));
  const groups = new Map<string, InterfaceForwardingIdentityGroup>();

  for (const identity of identities) {
    const address = addresses.get(identity.environment_id);
    if (!address) continue;
    const key = `${identity.login_account.trim().toLocaleLowerCase()}\u0000${identity.role_name.trim().toLocaleLowerCase()}`;
    const group = groups.get(key);
    if (group) {
      if (!group.roleName && identity.role_name) group.roleName = identity.role_name;
      group.mappings.push({ identity, address });
      continue;
    }
    groups.set(key, {
      key,
      loginAccount: identity.login_account,
      roleName: identity.role_name,
      mappings: [{ identity, address }],
    });
  }

  return [...groups.values()]
    .map((group) => ({
      ...group,
      mappings: group.mappings.sort((left, right) =>
        `${left.address.name}-${left.address.service_name || ""}`.localeCompare(
          `${right.address.name}-${right.address.service_name || ""}`,
          "zh-CN",
        ),
      ),
    }))
    .sort((left, right) => left.loginAccount.localeCompare(right.loginAccount, "zh-CN"));
}
