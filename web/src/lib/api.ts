export const BACKEND_URL = (import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export interface VoiceSession {
  app_id: string;
  channel: string;
  uid: number;
  token: string;
  agent_uid: string;
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

export async function createVoiceSession(language = 'en'): Promise<VoiceSession> {
  const res = await fetch(`${BACKEND_URL}/api/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language }),
  });
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as VoiceSession;
}

export async function endVoiceSession(channel: string): Promise<void> {
  await fetch(`${BACKEND_URL}/api/session/${encodeURIComponent(channel)}`, { method: 'DELETE', keepalive: true });
}
