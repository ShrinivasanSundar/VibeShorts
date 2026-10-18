"use client";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  Download,
  Film,
  Loader2,
  Plus,
  Save,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useWorkspace } from "../lib/workspace";
import { call, request } from "../lib/api";
import { useStudio, useEditor } from "../lib/studio-store";
import type { Asset, Brand, Clip } from "../lib/studio-types";
import { PrivateMedia } from "./private-media";
import { LoadingState } from "./loading-state";

const uid = () => crypto.randomUUID();
const usd = (value: number) => `$${(value / 1e6).toFixed(3)}`;
const blankBrand: Brand = {
  colors: { primary: "#87ceeb", secondary: "#111418" },
  fonts: {},
  logo: null,
  reference_frames: [],
  do: [],
  dont: [],
  caption: {},
};
function AssetThumb({
  asset,
  projectId,
  onClick,
}: {
  asset: Asset;
  projectId: string;
  onClick: () => void;
}) {
  return (
    <button className="media-card" onClick={onClick}>
      <div className="media-thumb">
        {asset.type === "image" ? (
          <PrivateMedia
            projectId={projectId}
            artifactId={asset.id}
            image
            title={asset.title}
          />
        ) : (
          <Film size={24} />
        )}
      </div>
      <strong>{asset.title}</strong>
      <small>{asset.type}</small>
    </button>
  );
}
export function WorkspaceTools({
  panel,
  onClose,
  onOpenRun,
  onCreateBlank,
  onOpenComposition,
}: {
  panel: string;
  onClose: () => void;
  onOpenRun: (id: string) => void;
  onCreateBlank: () => Promise<void>;
  onOpenComposition: (id: string) => Promise<void>;
}) {
  const w = useWorkspace();
  const {
    projectId,
    user,
    base,
    data,
    busy,
    action: workspaceAction,
    submit,
    importAsset,
    download,
    setNotice,
  } = w;
  const action = (task: () => Promise<unknown>) => workspaceAction(task, true);
  const s = useEditor();
  useEffect(() => w.loadResources(), []);
  const [tab, setTab] = useState(panel);
  const [brand, setBrand] = useState<Brand>(blankBrand);
  const [assetFilter, setAssetFilter] = useState("all");
  const [brief, setBrief] = useState("");
  const [cap, setCap] = useState("");
  const [member, setMember] = useState("");
  const [role, setRole] = useState("editor");
  const [moreAssets, setMoreAssets] = useState<Asset[]>([]);
  const [assetCursor, setAssetCursor] = useState<string | null>(null);
  const [assetsExhausted, setAssetsExhausted] = useState(false);
  const [assetPreview, setAssetPreview] = useState<{
    asset: Asset;
    url: string;
  } | null>(null);
  const [story, setStory] = useState<{
    scenes: { id: string; objective: string; exact_copy: string[] }[];
  } | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const drawer = useRef<HTMLElement>(null);
  useEffect(() => {
    setTab(panel);
  }, [panel]);
  useEffect(() => {
    if (data?.brand) setBrand(data.brand);
  }, [data?.project.brand_version]);
  useEffect(
    () => () => {
      if (assetPreview) URL.revokeObjectURL(assetPreview.url);
    },
    [assetPreview],
  );
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    drawer.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => previous?.focus();
  }, []);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [onClose]);
  // Fetched only while this drawer is open; the polled studio state no longer carries assets.
  const assetPage = useQuery({
    queryKey: ["assets", user.uid, projectId],
    queryFn: async () =>
      (await call(`${base}/assets?limit=100`)) as {
        assets: Asset[];
        next_cursor: string | null;
      },
  });
  const assets = [...(assetPage.data?.assets || []), ...moreAssets].filter(
    (a, i, all) => all.findIndex((x) => x.id === a.id) === i,
  );
  function addClip(asset?: Asset) {
    const kind =
      asset?.type === "audio"
        ? "audio"
        : asset?.type === "video" || asset?.type === "render"
          ? "video"
          : asset
            ? "image"
            : "text";
    const clip: Clip = {
      id: "clip-" + uid().slice(0, 8),
      artifact_id: asset?.id || null,
      kind,
      track: kind === "audio" ? 1 : kind === "text" ? 2 : 0,
      start: 0,
      duration: Math.min(
        asset?.media.duration_seconds || 5,
        s.timeline.duration_seconds,
      ),
      source_in: 0,
      text: kind === "text" ? "Your text" : "",
      volume: kind === "audio" ? 0.8 : 0,
      fade_in: 0,
      fade_out: 0,
      hidden: false,
    };
    s.edit({ ...s.timeline, clips: [...s.timeline.clips, clip] });
    s.select(clip.id);
    setNotice("Added to your cut. Open Edit to adjust its timing.");
  }
  async function viewAsset(asset: Asset) {
    if (asset.type === "composition") {
      await onOpenComposition(asset.id);
      onClose();
      return;
    }
    if (asset.type === "storyboard") {
      const response = await call(`${base}/storyboards/${asset.id}`);
      setStory(response.data);
      return;
    }
    if (asset.type === "audio") {
      const response = await request(`${base}/assets/${asset.id}/content`);
      setAssetPreview({
        asset,
        url: URL.createObjectURL(await response.blob()),
      });
    } else setAssetPreview({ asset, url: "" });
  }
  async function generateImage() {
    await call(`${base}/images`, {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        idempotency_key: uid(),
        input: {
          prompt: brief,
          aspect_ratio: s.timeline.aspect_ratio,
          reference_artifact_ids: brand.reference_frames || [],
        },
      }),
    });
    setNotice("Image queued. Find it in the library when ready.");
  }
  const batchAttempt = useRef<{
    text: string;
    cap: string;
    key: string;
  } | null>(null);
  async function batch() {
    const lines = brief
      .split("\n")
      .map((v) => v.trim())
      .filter(Boolean);
    if (!lines.length || lines.length > 10)
      throw new Error("Enter 1–10 ideas, one per line.");
    if (cap && (!Number.isFinite(Number(cap)) || Number(cap) <= 0))
      throw new Error("Enter a positive allowance.");
    if (
      !batchAttempt.current ||
      batchAttempt.current.text !== brief ||
      batchAttempt.current.cap !== cap
    )
      batchAttempt.current = { text: brief, cap, key: uid() };
    const batchKey = batchAttempt.current.key;
    for (const [index, text] of lines.entries()) {
      const chat = await call(`${base}/conversations`, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: batchKey + ":" + index + ":create",
          title: text.slice(0, 120),
          workflow_mode: "bulk",
        }),
      });
      await call(`${base}/conversations/${chat.data.id}/messages`, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: batchKey + ":" + index + ":message",
          text,
          duration_seconds: 15,
          aspect_ratio: "9:16",
          locale: "en",
          spend_cap_micros: cap ? Math.round(Number(cap) * 1e6) : null,
        }),
      });
    }
    batchAttempt.current = null;
    setBrief("");
    setNotice("Storyboards queued. Open each video to approve its production.");
  }
  return (
    <div
      className="workspace-drawer-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        ref={drawer}
        className="workspace-tools"
        role="dialog"
        aria-modal="true"
        aria-label="Workspace tools"
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          if (e.key === "Tab") {
            const list = Array.from(
              drawer.current?.querySelectorAll<HTMLElement>(
                'button:not(:disabled),a[href],input,select,textarea,[tabindex="0"]',
              ) || [],
            ).filter((n) => n.getClientRects().length);
            if (e.shiftKey && document.activeElement === list[0]) {
              e.preventDefault();
              list.at(-1)?.focus();
            } else if (!e.shiftKey && document.activeElement === list.at(-1)) {
              e.preventDefault();
              list[0]?.focus();
            }
          }
        }}
      >
        <header>
          <h2>
            {panel === "assets"
              ? "Library"
              : panel === "batch"
                ? "Create multiple videos"
                : "Settings & production"}
          </h2>
          <button aria-label="Close tools" onClick={onClose}>
            <X size={20} />
          </button>
        </header>
        <nav>
          {(panel === "assets"
            ? [
                ["assets", "Assets"],
                ["generate", "Create media"],
              ]
            : panel === "batch"
              ? []
              : [
                  ["brand", "Brand"],
                  ["team", "Team"],
                  ["activity", "Production"],
                  ["exports", "Exports"],
                ]
          ).map(([id, label]) => (
            <button
              key={id}
              aria-pressed={tab === id}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="library-body">
          {tab === "batch" && (
            <>
              <p>
                One idea per line. Each video gets its own storyboard and
                approval.
              </p>
              <label>
                Ideas
                <textarea
                  value={brief}
                  onChange={(e) => setBrief(e.target.value)}
                  maxLength={6000}
                />
              </label>
              <label>
                Allowance per video ($)
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  placeholder="Project allowance"
                  value={cap}
                  onChange={(e) => setCap(e.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={busy || !brief.trim()}
                onClick={() => void action(batch)}
              >
                Create storyboards
              </button>
            </>
          )}
          {tab === "generate" && (
            <>
              <label>
                Describe the image or music
                <textarea
                  maxLength={4000}
                  value={brief}
                  onChange={(e) => setBrief(e.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={busy || !brief.trim()}
                onClick={() => void action(generateImage)}
              >
                Create image
              </button>
              <button
                className="secondary"
                disabled={busy || !brief.trim()}
                onClick={() =>
                  void action(async () => {
                    await submit("/music", {
                      prompt: brief,
                      duration_seconds: 30,
                    });
                    setNotice(
                      "Music queued. Find it in the library when ready.",
                    );
                  })
                }
              >
                Create instrumental music
              </button>
            </>
          )}
          {tab === "assets" && (
            <>
              <button
                className="chat-button"
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await onCreateBlank();
                    onClose();
                  })
                }
              >
                <Plus size={15} />
                Start a blank video
              </button>
              <div className="asset-filters">
                {["all", "image", "video", "audio"].map((f) => (
                  <button
                    key={f}
                    className={assetFilter === f ? "active" : ""}
                    onClick={() => setAssetFilter(f)}
                  >
                    {f}
                  </button>
                ))}
              </div>
              <button
                className="upload-zone"
                disabled={busy}
                onClick={() => uploadRef.current?.click()}
              >
                <Upload size={20} />
                <strong>Bring your own assets</strong>
                <small>Images · audio · video · brand fonts</small>
              </button>
              <input
                type="file"
                hidden
                ref={uploadRef}
                accept="image/png,image/jpeg,video/mp4,audio/wav,audio/mpeg,.woff2,.ttf"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void action(() => importAsset(file));
                  e.target.value = "";
                }}
              />
              <div className="media-grid">
                {assets
                  .filter(
                    (a) => assetFilter === "all" || a.type === assetFilter,
                  )
                  .map((a) => (
                    <div key={a.id}>
                      <AssetThumb
                        asset={a}
                        projectId={projectId}
                        onClick={() => void action(() => viewAsset(a))}
                      />
                      {["image", "video", "audio", "render"].includes(
                        a.type,
                      ) && (
                        <button
                          className="add-to-timeline"
                          disabled={!w.head}
                          onClick={() => addClip(a)}
                        >
                          <Plus size={11} /> Add to timeline
                        </button>
                      )}
                    </div>
                  ))}
              </div>
              {!assetPage.data ? (
                <LoadingState label="Loading your library…" />
              ) : (
                !assets.length && (
                  <p className="empty-note">
                    A clean canvas. Import an image or create your first asset.
                  </p>
                )
              )}
              {!assetsExhausted &&
                (assetCursor || assetPage.data?.next_cursor) && (
                  <button
                    className="secondary full"
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        const response = await call(
                          `${base}/assets?limit=100&cursor=${encodeURIComponent(assetCursor || assetPage.data?.next_cursor || "")}`,
                        );
                        setMoreAssets((v) => [...v, ...response.assets]);
                        setAssetCursor(response.next_cursor);
                        setAssetsExhausted(!response.next_cursor);
                      })
                    }
                  >
                    {busy ? "Loading more assets…" : "Load more assets"}
                  </button>
                )}
            </>
          )}
          {tab === "brand" && (
            <>
              <p className="panel-intro">
                The details that make every frame feel like you. Each save
                creates a brand version.
              </p>
              <h3>Brand palette</h3>
              <div className="color-fields">
                {Object.entries(brand.colors).map(([name, value]) => (
                  <label key={name}>
                    <input
                      type="color"
                      value={value}
                      onChange={(e) =>
                        setBrand({
                          ...brand,
                          colors: { ...brand.colors, [name]: e.target.value },
                        })
                      }
                    />
                    <span>
                      {name}
                      <small>{value.toUpperCase()}</small>
                    </span>
                  </label>
                ))}
              </div>
              <label>
                Exact logo
                <select
                  value={brand.logo || ""}
                  onChange={(e) =>
                    setBrand({ ...brand, logo: e.target.value || null })
                  }
                >
                  <option value="">No logo selected</option>
                  {assets
                    .filter((a) => a.type === "image")
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.title}
                      </option>
                    ))}
                </select>
              </label>
              {w.head && (
                <button
                  className="chat-button"
                  disabled={busy || s.dirty}
                  onClick={() =>
                    void action(async () => {
                      const result = await call(
                        `${base}/assets/${w.head}/brand-check`,
                      );
                      setNotice(
                        result.data.passed
                          ? "Brand checks passed for this cut."
                          : "Review missing brand colors or assets in this cut.",
                      );
                    })
                  }
                >
                  Check current video
                </button>
              )}
              <h3>Brand typography</h3>
              {["heading", "body"].map((name) => (
                <label key={name}>
                  {name}
                  <select
                    value={brand.fonts[name] || ""}
                    onChange={(e) => {
                      const fonts = { ...brand.fonts };
                      if (e.target.value) fonts[name] = e.target.value;
                      else delete fonts[name];
                      setBrand({ ...brand, fonts });
                    }}
                  >
                    <option value="">Bundled Inter</option>
                    {assets
                      .filter((a) => a.type === "font")
                      .map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.title}
                        </option>
                      ))}
                  </select>
                </label>
              ))}
              <h3>Reference frames</h3>
              <div className="reference-list">
                {assets
                  .filter((a) => a.type === "image")
                  .map((a) => (
                    <label key={a.id}>
                      <input
                        type="checkbox"
                        checked={brand.reference_frames.includes(a.id)}
                        onChange={(e) =>
                          setBrand({
                            ...brand,
                            reference_frames: e.target.checked
                              ? [...brand.reference_frames, a.id].slice(0, 3)
                              : brand.reference_frames.filter(
                                  (v) => v !== a.id,
                                ),
                          })
                        }
                      />
                      {a.title}
                    </label>
                  ))}
              </div>
              <label>
                Do · one per line
                <textarea
                  value={brand.do.join("\n")}
                  onChange={(e) =>
                    setBrand({ ...brand, do: e.target.value.split("\n") })
                  }
                  placeholder="High contrast\nOne clear claim per scene"
                />
              </label>
              <label>
                Avoid · one per line
                <textarea
                  value={brand.dont.join("\n")}
                  onChange={(e) =>
                    setBrand({ ...brand, dont: e.target.value.split("\n") })
                  }
                  placeholder="Small type\nVisual clutter"
                />
              </label>
              <button
                className="primary full"
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await call(`${base}/brand`, {
                      method: "POST",
                      body: JSON.stringify({
                        idempotency_key: uid(),
                        expected_version: data?.project.brand_version || 0,
                        brand: {
                          colors: brand.colors,
                          fonts: brand.fonts,
                          logo: brand.logo,
                          reference_frames: brand.reference_frames,
                          do: brand.do.filter(Boolean),
                          dont: brand.dont.filter(Boolean),
                          caption: brand.caption,
                        },
                      }),
                    });
                    setNotice(
                      "Brand version saved. Future runs will use this bundle.",
                    );
                  })
                }
              >
                <Save size={14} /> Save brand version
              </button>
            </>
          )}
          {tab === "activity" && (
            <>
              <h3>Runs</h3>
              {data?.runs.map((run) => (
                <div className="run-card" key={run.run_id}>
                  <span className={`status-tag ${run.status}`}>
                    {run.status.replaceAll("_", " ")}
                  </span>
                  <strong>
                    {run.workflow?.brief?.brief || "Standalone media operation"}
                  </strong>
                  <small>
                    {run.workflow?.stage || "Media generation"} · v{run.version}
                  </small>
                  {run.workflow && (
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => onOpenRun(run.run_id)}
                    >
                      Open video
                    </button>
                  )}
                  {!["succeeded", "failed", "cancelled"].includes(
                    run.status,
                  ) && (
                    <button
                      className="text danger"
                      disabled={busy}
                      onClick={() =>
                        void action(async () => {
                          await call(`${base}/runs/${run.run_id}/cancel`, {
                            method: "POST",
                            body: JSON.stringify({ idempotency_key: uid() }),
                          });
                        })
                      }
                    >
                      Cancel run
                    </button>
                  )}
                </div>
              ))}
              <h3>Jobs</h3>
              {data?.jobs.map((job) => (
                <div className="job-item" key={job.job_id}>
                  <span className={`status-dot ${job.status}`} />
                  <div>
                    <strong>{job.kind || "image"}</strong>
                    <small>
                      {job.status.replaceAll("_", " ")} ·{" "}
                      {usd(
                        job.costs.settled_micros || job.costs.reserved_micros,
                      )}
                    </small>
                    {job.error && (
                      <p className="job-error">{job.error.message}</p>
                    )}
                  </div>
                  {job.status === "succeeded" ? (
                    <Check size={13} />
                  ) : !["failed", "cancelled", "submission_unknown"].includes(
                      job.status,
                    ) ? (
                    <Loader2 size={13} className="spin" />
                  ) : (
                    <X size={13} />
                  )}
                </div>
              ))}
            </>
          )}
          {tab === "exports" && (
            <>
              <button
                className="chat-button"
                disabled={busy || !w.head || s.dirty}
                onClick={() =>
                  void action(async () => {
                    await submit("/renders", {
                      composition_artifact_id: w.head,
                      quality: "draft",
                    });
                    setNotice("Draft render queued.");
                  })
                }
              >
                Render current draft
              </button>
              <p className="panel-intro">
                Private exports and editable packages. Every file points to an
                immutable revision.
              </p>
              {assets
                .filter((a) => ["render", "composition"].includes(a.type))
                .map((a) => (
                  <div className="export-card" key={a.id}>
                    <Film size={24} />
                    <strong>{a.title}</strong>
                    <small>
                      {a.type === "composition"
                        ? "Editable HyperFrames package"
                        : "H.264 MP4 · 24 FPS"}
                    </small>
                    <button
                      className="secondary full"
                      disabled={busy}
                      onClick={() => void action(() => download(a))}
                    >
                      <Download size={14} /> Download{" "}
                      {a.type === "composition" ? "package" : "video"}
                    </button>
                  </div>
                ))}
              {!data && <LoadingState label="Loading your exports…" />}
              {data && !assets.some((a) => a.type === "render") && (
                <p className="empty-note">
                  Your next export belongs here. Finish a composition and
                  approve its exact revision.
                </p>
              )}
            </>
          )}
          {tab === "team" && (
            <>
              <p className="panel-intro">
                Share this workspace with a VibeShorts user. Only the project
                owner can change access.
              </p>
              <label>
                Firebase user ID
                <input
                  value={member}
                  onChange={(e) => setMember(e.target.value)}
                  placeholder="User must have signed in first"
                />
              </label>
              <label>
                Role
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="editor">Editor · create and approve</option>
                  <option value="viewer">Viewer · read and download</option>
                </select>
              </label>
              <button
                className="primary full"
                disabled={busy || !member}
                onClick={() =>
                  void action(async () => {
                    await call(`${base}/members`, {
                      method: "POST",
                      body: JSON.stringify({
                        idempotency_key: uid(),
                        uid: member,
                        role,
                      }),
                    });
                    setNotice("Project membership updated.");
                  })
                }
              >
                <Users size={14} /> Add member
              </button>
              <button
                className="secondary full"
                disabled={busy || !member}
                onClick={() =>
                  void action(async () => {
                    await call(`${base}/members`, {
                      method: "POST",
                      body: JSON.stringify({
                        idempotency_key: uid(),
                        uid: member,
                        role: null,
                      }),
                    });
                    setNotice("Member removed.");
                  })
                }
              >
                Remove member
              </button>
            </>
          )}
        </div>
        <div className="budget-footer">
          <strong>
            {usd(data?.budget.settled_micros || 0)} used ·{" "}
            {usd(data?.budget.cap_micros || 0)} allowance
          </strong>
          <small>{usd(data?.budget.reserved_micros || 0)} reserved</small>
        </div>
        {story && (
          <div>
            <h3>Storyboard</h3>
            {story.scenes.map((scene) => (
              <article key={scene.id}>
                <strong>{scene.objective}</strong>
                <p>{scene.exact_copy.join(" · ")}</p>
              </article>
            ))}
            <button onClick={() => setStory(null)}>Close storyboard</button>
          </div>
        )}
        {assetPreview && (
          <div className="tool-asset-preview">
            <button
              aria-label="Close asset preview"
              onClick={() => setAssetPreview(null)}
            >
              <X size={18} />
            </button>
            {assetPreview.asset.type === "image" ? (
              <PrivateMedia
                projectId={projectId}
                artifactId={assetPreview.asset.id}
                image
                title={assetPreview.asset.title}
              />
            ) : assetPreview.asset.type === "audio" ? (
              <audio src={assetPreview.url} controls />
            ) : (
              <PrivateMedia
                projectId={projectId}
                artifactId={assetPreview.asset.id}
                title={assetPreview.asset.title}
              />
            )}
            <button
              onClick={() => void action(() => download(assetPreview.asset))}
            >
              Download
            </button>
            {assetPreview.asset.type === "image" && (
              <button
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    await submit("/videos", {
                      prompt: brief || "Gentle cinematic camera movement",
                      first_frame_artifact_id: assetPreview.asset.id,
                      source_duration_seconds: 6,
                      aspect_ratio: s.timeline.aspect_ratio,
                    });
                    setNotice("Animation queued.");
                  })
                }
              >
                Animate image
              </button>
            )}
          </div>
        )}
        {(w.error || w.notice) && (
          <p role={w.error ? "alert" : "status"}>{w.error || w.notice}</p>
        )}
      </section>
    </div>
  );
}
