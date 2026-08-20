import { WorkspaceMcpEnvironmentDefaults } from "@/components/workspace-mcp-environment-defaults";

interface WorkspaceMcpEnvironmentsPageProps {
  params: Promise<{ workspaceId: string }>;
}

export default async function WorkspaceMcpEnvironmentsPage({
  params,
}: WorkspaceMcpEnvironmentsPageProps) {
  const { workspaceId } = await params;
  return <WorkspaceMcpEnvironmentDefaults workspaceId={workspaceId} />;
}
