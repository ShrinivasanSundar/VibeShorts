import { AuthPanel } from "../../components/auth-panel";
export default async function ConsentPage({ searchParams }: { searchParams: Promise<{ request_id?: string }> }) {
  const params = await searchParams;
  return params.request_id ? <AuthPanel requestId={params.request_id} /> : <main className="shell"><section className="card"><h1>Connection expired.</h1><p>Start a new connection from your creative tool.</p><a href="/">Return to workspace</a></section></main>;
}
