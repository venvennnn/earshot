import { useEffect, useState } from 'react';
import { api } from './api';

/** A phone session without a voice call (Listen button, tap test, add a machine). Replies come as Murf audio. */
export function useAppSession(existing?: string | null): string | null {
  const [id, setId] = useState<string | null>(existing ?? null);
  useEffect(() => {
    if (existing) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const s = await api.startSession('app');
      if (!cancelled) setId(s.session);
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [existing]);
  return id;
}
