/** Shapes of the live state the backend pushes over the WebSocket (see backend/events.py). */

export type AssetState = 'normal' | 'watch' | 'problem' | 'unset' | 'out';
export type Mode = 'continuous' | 'tap' | 'alarm';
export type Purpose = 'check' | 'enroll' | 'verify';

export interface Asset {
  id: string;
  name: string;
  type: string;
  line: string;
  modes: Mode[];
  parts: number;
  state: AssetState;
  label: string;
}

export interface Analysis {
  id: string;
  asset_id: string;
  ok: boolean;
  at: number;
  band?: 'normal' | 'slightly unusual' | 'very unusual';
  anomaly_score?: number;
  label?: string;
  confidence?: 'not sure' | 'fairly sure' | 'very sure';
  alternatives?: string[];
  spectrum?: { baseline: number[]; now: number[] };
  explanation?: string;
  clip_url?: string;
  baseline_url?: string;
  issue?: string;
  tip?: string;
}

export interface TimelineItem {
  id: string;
  ts: number;
  text: string;
  status: 'done' | 'waiting' | 'next' | 'failed' | 'skipped';
  detail: { tool?: string; args?: unknown; result?: { jira_key?: string; jira_url?: string } & Record<string, unknown>; error?: string; tier?: number };
}

export interface Confirmation {
  id: string;
  session: string;
  asset_id: string;
  asset_name: string;
  question: string;
  steps: PlanStep[];
  tools: string[];
  tier: number;
  status: 'pending' | 'second_approval' | 'approved' | 'declined' | 'replaced';
  worker: string;
  approver: string | null;
}

export interface PlanStep {
  text: string;
  tool: string | null;
  status?: 'next' | 'done' | 'failed' | 'skipped';
}

export interface FollowUp {
  id: string;
  asset_id: string;
  asset_name: string;
  when: string;
  note: string;
  status: 'open' | 'done';
}

export interface Contact {
  id: string;
  name: string;
  role: string;
  language: string;
  language_name: string;
  kind: 'call' | 'announcement';
  status: string;
  message: string;
  text: string;
  audio_url: string | null;
  reply: string | null;
  approval_for?: string;
  ts: number;
}

export interface Line {
  id: string;
  session: string;
  who: 'worker' | 'agent';
  text: string;
  ts: number;
}

export interface TapPart {
  n: number;
  result: 'good' | 'dull';
  decay_ms: number;
  reason: string;
  envelope: number[];
  clip_url?: string;
}

export interface TapBatch {
  asset_id: string;
  total: number;
  parts: TapPart[];
  good_decay_ms: number;
  good_envelope: number[];
  good_url?: string;
}

export interface Person {
  name: string;
  role: string;
  language: string;
  approver: boolean;
}

export interface PackSummary {
  id: string;
  name: string;
  plant: string;
  line: string;
  shift: string;
  language: string;
  worker: { name: string; role: string; language: string };
  people: Person[];
}

export type JobStatus = 'open' | 'scheduled' | 'in_progress' | 'done' | 'cancelled';

export interface Job {
  id: string;
  asset_id: string;
  title: string;
  priority: string;
  status: JobStatus;
  scheduled_for?: string;
  jira_key?: string;
  jira_url?: string;
  jira_error?: string;
}

export interface TtsMetrics {
  murf_ttfa_median_s: number | null;
  llm_reply_median_s: number | null;
  voice_reply_s: number | null;
  murf_calls: number;
  llm_calls: number;
}

export interface PastIssue {
  id: string;
  asset_id: string;
  part?: number;
  title: string;
  priority?: string;
  status?: string;
  when?: string;
  cause?: string;
  summary?: string;
}

export interface InspectionLog {
  id: string;
  asset_id: string;
  part?: number;
  result: string;
  notes: string;
  at: string;
}

export interface AssetHistory {
  last_serviced: string;
  notes: string;
  status: string;
  issues: PastIssue[];
  inspections: InspectionLog[];
}

export interface LiveState {
  pack: PackSummary | null;
  assets: Asset[];
  analyses: Record<string, Analysis>;
  facts: Record<string, Record<string, string>>;
  timeline: TimelineItem[];
  confirmations: Confirmation[];
  contacts: Contact[];
  transcript: Line[];
  jobs: Job[];
  tap_batches: Record<string, TapBatch>;
  sessions: Record<string, { kind: string; worker: string; focus?: string }>;
  report: { text: string; audio_url: string | null; ts: number } | null;
  followups: FollowUp[];
  histories: Record<string, AssetHistory>;
  integrations: { jira?: boolean; jira_project?: string | null };
  tiles: {
    machines_checked: number;
    problems_caught: number;
    problem_assets: string[];
    hours_saved_estimate: number;
    jobs_done: number;
    waiting_for_yes: number;
  };
  tts: TtsMetrics;
}

export type LiveEvent =
  | { kind: 'capture_start'; session: string; asset_id: string; mode: Mode; purpose: Purpose }
  | { kind: 'play_audio'; target: 'dashboard' | 'session'; session?: string; url: string; label?: string; text?: string }
  | { kind: 'briefing'; name: string; contact_id: string }
  | { kind: 'tool'; session: string; name: string; status: string };
