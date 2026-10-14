export type Clip = {
  id: string;
  artifact_id: string | null;
  kind: "video" | "image" | "text" | "audio";
  track: number;
  start: number;
  duration: number;
  source_in: number;
  text: string;
  volume: number;
  fade_in: number;
  fade_out: number;
  hidden: boolean;
};
export type Timeline = {
  fonts: Record<string, string>;
  schema_version: 1;
  title: string;
  aspect_ratio: "9:16" | "16:9";
  duration_seconds: number;
  fps: 24;
  background: string;
  foreground: string;
  accent: string;
  clips: Clip[];
  expected_head: string | null;
  reference_artifact_ids: string[];
  spend_cap_micros: number | null;
};
export type Asset = {
  id: string;
  type: string;
  title: string;
  parent_id?: string;
  created_at: number;
  media: {
    mime_type: string;
    duration_seconds?: number;
    width?: number;
    height?: number;
  };
};
export type Job = {
  job_id: string;
  run_id: string;
  kind: string;
  status: string;
  artifact_ids: string[];
  costs: { reserved_micros: number; settled_micros: number };
  error?: { message: string };
};
export type Approval = {
  id: string;
  kind: string;
  target_artifact_id: string;
  decision: string;
  run_id: string | null;
  conversation_id?: string;
  scene_id?: string;
  storyboard_artifact_id?: string;
};
export type Run = {
  run_id: string;
  status: string;
  version: number;
  pending_approval_id: string | null;
  workflow?: {
    brief: { brief: string };
    stage: string;
    composition_artifact_id?: string;
    export_artifact_id?: string;
    draft_artifact_id?: string;
  };
};
export type Brand = {
  colors: Record<string, string>;
  fonts: Record<string, string>;
  logo: string | null;
  reference_frames: string[];
  do: string[];
  dont: string[];
  caption: Record<string, string[]>;
  version?: number;
};
export type StudioState = {
  provider_route: string;
  project: {
    project_id: string;
    name: string;
    brand_version: number;
    composition_head: string | null;
  };
  budget: {
    cap_micros: number;
    reserved_micros: number;
    settled_micros: number;
  };
  runs: Run[];
  jobs: Job[];
  assets: { assets: Asset[]; next_cursor: string | null };
  approvals: Approval[];
  brand: Brand | null;
  events: { sequence: number; status: string; created_at: number }[];
};
export const emptyTimeline: Timeline = {
  fonts: {},
  schema_version: 1,
  title: "Untitled cut",
  aspect_ratio: "9:16",
  duration_seconds: 15,
  fps: 24,
  background: "#101014",
  foreground: "#ffffff",
  accent: "#bf96f6",
  clips: [],
  expected_head: null,
  reference_artifact_ids: [],
  spend_cap_micros: null,
};

export type Storyboard = {
  creative_preferences?: CreativePreferences | null;
  duration_seconds: number;
  aspect_ratio: "9:16" | "16:9";
  scenes: {
    id: string;
    objective: string;
    exact_copy: string[];
    visual_prompt: string;
    editorial_duration_seconds: number;
  }[];
};
export type Conversation = {
  id: string;
  title: string;
  composition_head: string | null;
  storyboard_head: string | null;
  active_run_id: string | null;
  updated_at: number;
};
export type MessageBlock = {
  kind:
    | "attachment"
    | "storyboard"
    | "scene"
    | "video"
    | "composition"
    | "export"
    | "progress"
    | "review"
    | "error";
  artifact_id?: string;
  composition_artifact_id?: string;
  storyboard_artifact_id?: string;
  scene_id?: string;
  job_id?: string;
  retryable?: boolean;
  storyboard?: Storyboard;
  copy?: string[];
};
export type ChatMessage = {
  id: string;
  sequence: number;
  role: "user" | "assistant";
  text: string;
  blocks: MessageBlock[];
  status?: string;
  job_id?: string;
};
export type ConversationState = {
  approvals?: Approval[];
  has_pending_message?: boolean;
  production?: ProductionSummary;
  conversation: Conversation;
  messages: ChatMessage[];
  next_cursor: string | null;
  run: (Run & { approval?: Approval }) | null;
  operations?: {
    job_id: string;
    kind: string;
    status: string;
    quality?: string;
    error?: { message: string };
    retried_by?: string;
  }[];
};

export type CreativePreferences = {
  vibe: "cinematic" | "cartoon" | "collage" | "3d" | null;
  motion: "real_time" | "slow_motion";
};
export type ProductionStep = {
  job_id: string | null;
  status: string;
  artifact_id: string | null;
  error?: { message: string } | null;
};
export type ProductionSummary = {
  mode: "bulk" | "guided";
  stage: string;
  storyboard: Storyboard | null;
  scenes: (Storyboard["scenes"][number] & {
    frame: ProductionStep;
    video: ProductionStep;
    generation: ProductionStep;
  })[];
  music: ProductionStep;
  music_generation: ProductionStep;
  composition: ProductionStep;
  draft: ProductionStep;
  export: ProductionStep;
  affected_scene_ids: string[];
};
