import { AuthPanel } from "../../../components/auth-panel";

export default async function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <AuthPanel projectId={projectId} />;
}
