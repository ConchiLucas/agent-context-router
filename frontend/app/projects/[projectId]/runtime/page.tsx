import { ProjectRuntimeConfigEditor } from "@/components/project-runtime-config";

interface ProjectRuntimePageProps {
  params: Promise<{ projectId: string }>;
}

export default async function ProjectRuntimePage({
  params,
}: ProjectRuntimePageProps) {
  const { projectId } = await params;
  return <ProjectRuntimeConfigEditor projectId={projectId} />;
}
