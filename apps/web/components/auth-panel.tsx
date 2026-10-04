"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { GoogleAuthProvider, onAuthStateChanged, signInWithPopup, signOut, type User } from "firebase/auth";
import { firebaseAuth } from "../lib/firebase";
import { call } from "../lib/api";
import { ProjectPanel } from "./project-panel";
import { Studio } from "./studio";
import { useQueryClient } from "@tanstack/react-query";

type Project = { project_id: string; name: string };
type Review = { client_name: string; scopes: string[]; projects: Project[] };
const scopeLabels: Record<string, string> = {
  "vibeshorts:read": "Read project details and download media",
  "vibeshorts:generate": "Generate media using your project budget",
  "vibeshorts:cancel": "Cancel media jobs",
};
export function AuthPanel({ requestId, projectId }: { requestId?: string; projectId?: string }) {
  const queryClient=useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("");

  useEffect(() => {
    try {
      return onAuthStateChanged(firebaseAuth(), (next) => {
        queryClient.clear();
        setUser(next); setReady(true); setProjects([]); setReview(null); setSelected([]); setError("");
      });
    } catch (exception) { setError((exception as Error).message); setReady(true); }
  }, []);

  useEffect(() => {
    if (!user || projectId) return;
    let active = true;
    async function load() {
      try {
        if (requestId) {
          const data: Review = await call(`/oauth/requests/${encodeURIComponent(requestId)}`);
          if (active) { setReview(data); setProjects(data.projects); }
        } else {
          const data = await call("/v1/projects");
          if (active) setProjects(data.data.projects);
        }
      } catch (exception) { if (active) setError((exception as Error).message); }
    }
    void load();
    return () => { active = false; };
  }, [user?.uid, requestId, projectId]); // Project state is discarded whenever identity changes.

  async function action(task: () => Promise<void>) {
    setBusy(true); setError("");
    try { await task(); } catch (exception) { setError((exception as Error).message); } finally { setBusy(false); }
  }

  async function createProject() {
    const result = await call("/v1/projects", { method: "POST", body: JSON.stringify({ name: name.trim(), idempotency_key: crypto.randomUUID() }) });
    setProjects((current) => [...current, result.data]); setName("");
  }

  async function consent(approved: boolean) {
    const result = await call("/oauth/consent", { method: "POST", body: JSON.stringify({
      request_id: requestId, project_ids: approved ? selected : [], approved,
    }) });
    window.location.assign(result.redirect_url);
  }

  if(projectId && user && !requestId) return <Studio key={`${user.uid}:${projectId}`} projectId={projectId} user={user}/>;

  return <main className="shell">
    <div className="wordmark"><span className="mark" aria-hidden="true">▶</span> VibeShorts <span className="stage">EARLY ACCESS</span></div>
    <section className="card">
      <div className="eyebrow">{requestId ? "CONNECT YOUR CREATIVE TOOLS" : "YOUR CREATIVE WORKSPACE"}</div>
      <h1>{requestId ? "A connection.\nYour permission." : projectId ? "Your project.\nYour images." : "Every idea starts\nwith a story."}</h1>
      <p className="intro">{requestId ? "Choose the projects this tool can access. You stay in control of your images and budget." : projectId ? "View your project details and the images created by your connected tools." : user ? "Open a project to view its images, or create a workspace for your next idea." : "Sign in to create your workspace and connect an image generation tool."}</p>
      {!ready ? <p role="status">Loading sign-in…</p> : !user ?
        <button className="primary" disabled={busy} onClick={() => action(async () => { await signInWithPopup(firebaseAuth(), new GoogleAuthProvider()); })}>
          <span aria-hidden="true">G</span> Continue with Google
        </button> : <>
          <div className="identity"><span className="avatar">{(user.displayName || user.email || "U")[0]}</span>
            <div><strong>{user.displayName || "Signed in"}</strong><small>{user.email}</small></div>
            <button className="text" disabled={busy} onClick={() => action(async () => { await signOut(firebaseAuth()); })}>Sign out</button>
          </div>
          {requestId ? review && <>
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
            <h2>Your projects</h2>
            {projects.length ? <div className="projects">{projects.map((project) => <Link className="project project-link" href={`/projects/${encodeURIComponent(project.project_id)}`} key={project.project_id}><strong>{project.name}<span aria-hidden="true">→</span></strong><code>{project.project_id}</code></Link>)}</div> : <p className="muted">Create your first project to get started.</p>}
            <form className="create" onSubmit={(event) => { event.preventDefault(); void action(createProject); }}>
              <label htmlFor="project-name">New project</label><div><input id="project-name" maxLength={120} placeholder="Your next launch" value={name} onChange={(event) => setName(event.target.value)} />
              <button className="primary" disabled={busy || !name.trim()}>Create</button></div>
            </form>
          </>}
        </>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
    <footer>FROM BRIEF TO BRILLIANT.</footer>
  </main>;
}
