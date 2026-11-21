import type { Analysis, Mode } from './types';

export const BACKEND_URL = (import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export const mediaUrl = (path: string | null | undefined): string => (path ? `${BACKEND_URL}${path}` : '');

export interface VoiceSession {
  kind: 'voice';
  session: string;
  app_id: string;
  channel: string;
  uid: number;
  token: string;
  agent_uid: string;
}

export interface AppSession {
  kind: 'app' | 'demo';
  session: string;
  greeting: string;
}

export interface TurnReply {
  reply?: string;
  audio_url?: string | null;
}

export interface ClipResponse extends TurnReply {
  session: string;
  result: Analysis & Record<string, unknown>;
}

async function errorText(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
  } catch {
    /* not JSON */
  }
  return `Request failed (${res.status})`;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, init);
  if (!res.ok) throw new Error(await errorText(res));
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const api = {
  startSession: (kind: 'voice' | 'app' = 'voice', language = 'en') =>
    call<VoiceSession | AppSession>('/api/session', json({ kind, language })),
  endSession: (id: string) =>
    fetch(`${BACKEND_URL}/api/session/${encodeURIComponent(id)}`, { method: 'DELETE', keepalive: true }),
  chat: (session: string, text: string) => call<TurnReply>('/api/chat', json({ session, text })),
  uploadClip: (wav: Blob, fields: { asset_id: string; mode: Mode; purpose: 'check' | 'enroll'; session?: string; part?: number }) => {
    const form = new FormData();
    form.append('file', wav, 'clip.wav');
    form.append('asset_id', fields.asset_id);
    form.append('mode', fields.mode);
    form.append('purpose', fields.purpose);
    if (fields.session) form.append('session', fields.session);
    if (fields.part) form.append('part', String(fields.part));
    return call<ClipResponse>('/api/audio/clip', { method: 'POST', body: form });
  },
  answer: (confirmationId: string, decision: 'yes' | 'no') =>
    call<TurnReply & { status: string }>(`/api/confirmations/${confirmationId}`, json({ decision })),
  reply: (contactId: string, reply: string) => call<{ status: string }>(`/api/contacts/${contactId}/reply`, json({ reply })),
  addAsset: (name: string, type: string) => call<{ asset_id: string; name: string }>('/api/assets', json({ name, type })),
  resetTap: (assetId: string) => call<void>(`/api/tap/${assetId}/reset`, { method: 'POST' }),
  switchPack: (id: string) => call<{ active: string }>('/api/pack', json({ id })),
  packs: () => call<{ active: string; packs: { id: string; name: string }[] }>('/api/packs'),
  writeReport: () => call<{ text: string; audio_url: string | null }>('/api/report', { method: 'POST' }),
};
