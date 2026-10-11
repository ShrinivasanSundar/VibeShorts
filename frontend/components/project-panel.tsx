"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { call, request } from "../lib/api";

type Project = { project_id: string; name: string; brand_version: string | null };
type Capabilities = { route: string; model: string; deprecated: boolean };
type Asset = { id: string; title: string; media: { width: number; height: number; mime_type: string } };
type AssetPage = { assets: Asset[]; next_cursor: string | null };

export function ProjectPanel({ projectId }: { projectId: string }) {
  const base = `/v1/projects/${encodeURIComponent(projectId)}`;
  const [project, setProject] = useState<Project | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [image, setImage] = useState<{ asset: Asset; url: string } | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const imageUrl = useRef<string | null>(null);
  const active = useRef(true);

  useEffect(() => {
    let mounted = true;
    active.current = true;
    async function load() {
      try {
        const [context, capability, page] = await Promise.all([
          call(`${base}/context`), call(`${base}/capabilities`), call(`${base}/assets?limit=20`),
        ]);
        if (mounted) {
          setProject(context.data); setCapabilities(capability.data);
          setAssets(page.assets); setCursor(page.next_cursor);
        }
      } catch (exception) {
        if (mounted) setError((exception as Error).message);
      } finally { if (mounted) setLoading(false); }
    }
    void load();
    return () => {
      mounted = false; active.current = false;
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    };
  }, [base]);

  async function loadMore() {
    setLoading(true); setError("");
    try {
      const page: AssetPage = await call(`${base}/assets?limit=20&cursor=${encodeURIComponent(cursor!)}`);
      if (active.current) { setAssets((current) => [...current, ...page.assets]); setCursor(page.next_cursor); }
    } catch (exception) { if (active.current) setError((exception as Error).message); }
    finally { if (active.current) setLoading(false); }
  }

  async function openImage(asset: Asset) {
    setOpening(asset.id); setError("");
    try {
      const response = await request(`${base}/assets/${encodeURIComponent(asset.id)}/content`);
      const blob = await response.blob();
      if (!active.current) return;
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
      const url = URL.createObjectURL(blob);
      imageUrl.current = url;
      setImage({ asset, url });
    } catch (exception) { if (active.current) setError((exception as Error).message); }
    finally { if (active.current) setOpening(null); }
  }

  return <div className="project-detail">
    <Link className="back-link" href="/">← All projects</Link>
    {loading && !project && <p className="muted" role="status">Loading project…</p>}
    {project && <>
      <h2 className="project-title">{project.name}</h2>
      <dl className="project-facts">
        <dt>Project ID</dt><dd><code>{project.project_id}</code></dd>
        <dt>Brand revision</dt><dd>{project.brand_version || "No brand configured yet"}</dd>
        {capabilities && <><dt>Image generation</dt><dd>{capabilities.route === "fixture" ? "Local fixture images" : capabilities.model}{capabilities.deprecated && " (deprecated)"}</dd></>}
      </dl>
      <h2>Images</h2>
      {assets.length ? <div className="projects">{assets.map((asset) => <div className="asset-row" key={asset.id}>
        <div><strong>{asset.title}</strong><small>{asset.media.width} × {asset.media.height} · {asset.media.mime_type === "image/png" ? "PNG" : "JPEG"}</small></div>
        <button className="secondary" disabled={opening !== null} onClick={() => void openImage(asset)}>{opening === asset.id ? "Opening…" : "View image"}</button>
      </div>)}</div> : <p className="muted">No images yet. Generate an image with your connected MCP tool to see it here.</p>}
      {cursor && <button className="secondary load-more" disabled={loading} onClick={() => void loadMore()}>{loading ? "Loading…" : "Load more images"}</button>}
      {image && <figure className="image-preview">
        {/* Private media is fetched with the current user's credentials and held in this tab only. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={image.url} alt={image.asset.title} />
        <figcaption>{image.asset.title}</figcaption>
        <a href={image.url} download={`${image.asset.id}.${image.asset.media.mime_type === "image/png" ? "png" : "jpg"}`}>Download image</a>
      </figure>}
    </>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
