"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { onAuthStateChanged, signOut, type User } from "firebase/auth";
import { firebaseAuth, signInWithGoogle } from "../lib/firebase";
import { call } from "../lib/api";
import { track } from "../lib/loading";
import { confirmAction } from "../lib/confirm";
import { LoadingState } from "./loading-state";
import { ProjectPanel } from "./project-panel";
import { ProjectWorkspace } from "./project-workspace";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Film, Layers3, LockKeyhole, Sparkles, Trash2 } from "lucide-react";
import { clearMediaCache } from "../lib/media-cache";
import { Brand } from "./brand";

type Project = { project_id: string; name: string };
type Review = { client_name: string; scopes: string[]; projects: Project[] };
const scopeLabels: Record<string, string> = {
  "vibeshorts:read": "Read project details and download media",
  "vibeshorts:generate": "Generate media using your project budget",
  "vibeshorts:cancel": "Cancel media jobs",
};
export function AuthPanel({ requestId, projectId }: { requestId?: string; projectId?: string }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [review, setReview] = useState<Review | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("");

  useEffect(() => {
    try {
      return onAuthStateChanged(firebaseAuth(), (next) => {
        clearMediaCache();
        queryClient.clear();
        setUser(next); setReady(true); setProjects([]); setReview(null); setSelected([]); setError("");
      });
    } catch (exception) { setError((exception as Error).message); setReady(true); }
  }, []);

  useEffect(() => {
    if (!user || projectId) return;
    let active = true;
    async function load() {
      setLoadingProjects(true);
      try {
        if (requestId) {
          const data: Review = await call(`/oauth/requests/${encodeURIComponent(requestId)}`);
          if (active) { setReview(data); setProjects(data.projects); }
        } else {
          const data = await call("/v1/projects");
          if (active) setProjects(data.data.projects);
        }
      } catch (exception) { if (active) setError((exception as Error).message); }
      finally { if (active) setLoadingProjects(false); }
    }
    void load();
    return () => { active = false; };
  }, [user?.uid, requestId, projectId]); // Project state is discarded whenever identity changes.

  async function action(task: () => Promise<void>) {
    setBusy(true); setError("");
    try { await track(task); } catch (exception) { setError((exception as Error).message); } finally { setBusy(false); }
  }

  async function createProject() {
    const result = await call("/v1/projects", { method: "POST", body: JSON.stringify({ name: name.trim(), idempotency_key: crypto.randomUUID() }) });
    setProjects((current) => [...current, result.data]); setName("");
  }

  async function deleteProject(project: Project) {
    // Confirm before starting the tracked action so the loader doesn't show while the modal waits.
    if (!await confirmAction({ title: "Delete this project?", message: `“${project.name}” and all of its videos, chats and generated media will be permanently erased. This can’t be undone.`, confirmLabel: "Delete project" })) return;
    await action(async () => {
      await call(`/v1/projects/${encodeURIComponent(project.project_id)}`, { method: "DELETE" });
      setProjects((current) => current.filter((p) => p.project_id !== project.project_id));
    });
  }

  async function consent(approved: boolean) {
    const result = await call("/oauth/consent", {
      method: "POST", body: JSON.stringify({
        request_id: requestId, project_ids: approved ? selected : [], approved,
      })
    });
    window.location.assign(result.redirect_url);
  }

  if (projectId && user && !requestId) return <ProjectWorkspace key={`${user.uid}:${projectId}`} projectId={projectId} user={user} />;

  return <main className={`shell ${requestId ? "connection-shell" : "workspace-shell"}`}>
    <header className="workspace-header"><Link href="/" aria-label="VibeShortsAI home"><Brand /></Link><span className="stage"><span className="dot" /> CREATIVE STUDIO</span></header>
    <div className={`workspace-content ${!user && !requestId ? "welcome-content" : ""}`}>
      <section className="workspace-intro">
        <div className="eyebrow"><Sparkles size={17} aria-hidden="true" />{requestId ? "CONNECT YOUR CREATIVE TOOLS" : "YOUR AI VIDEO STUDIO"}</div>
        <h1>{requestId ? <>A connection.<br /><span>Your permission.</span></> : projectId ? <>Your next short<br /><span>starts here.</span></> : user ? <>Big ideas.<br /><span>Your next story.</span></> : <>Turn your ideas into<br /><span>cinematic AI shorts.</span></>}</h1>
        <p className="intro">{requestId ? "Choose the projects this tool can access. You stay in control of your images and budget." : user ? "Open a project to shape your next short, or create a new workspace and see where your imagination takes you." : "Create faceless stories, visual explainers, and product videos from a creative brief. Bring your story. Make it move."}</p>
        {!user && !requestId && <div className="creative-directions"><span><Film size={15} /> Cinematic stories</span><span><Layers3 size={15} /> Visual explainers</span><span><Sparkles size={15} /> Product films</span></div>}
      </section>
      <section className="card workspace-card" aria-label={requestId ? "Connection permissions" : user ? "Your projects" : "Sign in to your studio"}>
        {!user && <><div className="card-kicker"><span className="dot" /> {requestId ? "YOUR WORKSPACE. YOUR CONTROL." : "A LITTLE SPARK. A LOT OF POSSIBILITY."}</div><h2>{requestId ? <>Your creative tools.<br /><span>Connected by you.</span></> : <>Your next short<br />starts with a <span>vibe.</span></>}</h2><p className="card-description">{requestId ? "Sign in to review this tool’s access before connecting it to your projects." : "Sign in to your studio and give your ideas a place to come to life."}</p></>}
        {!ready ? <LoadingState label="Loading sign-in…" /> : !user ?
          <button className="primary" disabled={busy} onClick={() => action(async () => { await signInWithGoogle(); })}>
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24"><path fill="currentColor" d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-2 3.01v2.5h3.24c1.9-1.75 2.98-4.33 2.98-7.34ZM12 22c2.7 0 4.96-.9 6.62-2.43l-3.24-2.5c-.9.6-2.05.96-3.38.96-2.6 0-4.81-1.76-5.6-4.12H3.05v2.59A10 10 0 0 0 12 22ZM6.4 13.91a6 6 0 0 1 0-3.82V7.5H3.05a10 10 0 0 0 0 9l3.35-2.59ZM12 5.97c1.47 0 2.79.51 3.83 1.51l2.87-2.87A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.95 5.5l3.35 2.59C7.19 7.73 9.4 5.97 12 5.97Z" /></svg> Continue with Google <ArrowUpRight size={17} aria-hidden="true" />
          </button> : <>
            <div className="identity"><span className="avatar">{(user.displayName || user.email || "U")[0]}</span>
              <div><strong>{user.displayName || "Signed in"}</strong><small>{user.email}</small></div>
              <button className="text" disabled={busy} onClick={() => action(async () => { await signOut(firebaseAuth()); })}>Sign out</button>
            </div>
            {requestId ? !review ? !error && <LoadingState label="Loading connection request…" /> : <>
              <h2>{review.client_name} is requesting access</h2>
              <ul className="permissions">{review.scopes.map((scope) => <li key={scope}>{scopeLabels[scope] || scope}</li>)}</ul>
              <h2>Choose projects</h2>
              {projects.length === 0 ? <p>Create a project from the <a href="/" target="_blank" rel="noreferrer">workspace</a>, then refresh this page.</p> :
                <div className="projects">{projects.map((project) => <label key={project.project_id}>
                  <input type="checkbox" checked={selected.includes(project.project_id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, project.project_id] : current.filter((id) => id !== project.project_id))} />
                  <span>{project.name}<small>{project.project_id}</small></span>
                </label>)}</div>}
              <div className="actions"><button className="secondary" disabled={busy} onClick={() => action(() => consent(false))}>Decline</button>
                <button className="primary" disabled={busy || selected.length === 0} onClick={() => action(() => consent(true))}>{busy ? "Connecting…" : "Allow connection"}</button></div>
            </> : projectId ? <ProjectPanel key={`${user.uid}:${projectId}`} projectId={projectId} /> : <>
              <div className="project-heading"><h2>Your projects</h2>{!loadingProjects && <span className="tiny-badge">{projects.length} {projects.length === 1 ? "PROJECT" : "PROJECTS"}</span>}</div>
              {loadingProjects ? <LoadingState label="Loading your projects…" /> : projects.length ? <div className="projects">{projects.map((project) => <div className="project-row" key={project.project_id}><Link className="project project-link" href={`/projects/${encodeURIComponent(project.project_id)}`}><strong>{project.name}<span aria-hidden="true">→</span></strong><code>{project.project_id}</code></Link>
                <button className="delete-button" disabled={busy} aria-label={`Delete project ${project.name}`} title="Delete project" onClick={() => void deleteProject(project)}><Trash2 size={16} aria-hidden="true" /></button></div>)}</div> : <p className="muted">Create your first project to get started.</p>}
              <form className="create" onSubmit={(event) => { event.preventDefault(); void action(createProject); }}>
                <label htmlFor="project-name">New project</label><div><input id="project-name" maxLength={120} placeholder="Your next launch" value={name} onChange={(event) => setName(event.target.value)} />
                  <button className="primary" disabled={busy || !name.trim()}>Create</button></div>
              </form>
            </>}
          </>}
        {error && <p className="error" role="alert">{error}</p>}
        {!user && <p className="signin-note"><LockKeyhole size={13} aria-hidden="true" /> Your ideas. Your workspace. Your creative control.</p>}
      </section>
    </div>
    {!requestId && <div className="workspace-ticker" aria-hidden="true"><span>CINEMATIC STORIES</span><b>✳</b><span>SCROLL-STOPPING SHORTS</span><b>✳</b><span>IMPOSSIBLE WORLDS</span></div>}
    <footer className="workspace-footer"><span>Big ideas deserve to be seen.</span><span>THINK IT. MAKE IT MOVE.</span></footer>
  </main>;
}
