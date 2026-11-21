import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import { VoiceCall } from './agora';

export type CallStatus = 'off' | 'connecting' | 'live' | 'error';

/** An optional live voice call with EarShot from any page (start/stop on demand). */
export function useVoiceCall() {
  const [status, setStatus] = useState<CallStatus>('off');
  const [session, setSession] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [needsTap, setNeedsTap] = useState(false);
  const callRef = useRef<VoiceCall | null>(null);

  const stop = useCallback(async () => {
    const call = callRef.current;
    callRef.current = null;
    await call?.leave();
    setSession((id) => {
      if (id) void api.endSession(id);
      return null;
    });
    setStatus('off');
  }, []);

  const start = useCallback(async () => {
    setStatus('connecting');
    setError('');
    try {
      const s = await api.startSession('voice');
      if (s.kind !== 'voice') throw new Error('Voice is off (demo mode).');
      const call = new VoiceCall(s, () => setNeedsTap(true));
      callRef.current = call;
      await call.join();
      setSession(s.session);
      setStatus('live');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start the call.');
      setStatus('error');
      await callRef.current?.leave();
      callRef.current = null;
    }
  }, []);

  useEffect(() => {
    const onUnload = () => void stop();
    window.addEventListener('pagehide', onUnload);
    return () => {
      window.removeEventListener('pagehide', onUnload);
      void stop();
    };
  }, [stop]);

  const setMuted = useCallback(async (muted: boolean) => {
    await callRef.current?.setMuted(muted);
  }, []);

  const resume = useCallback(() => {
    callRef.current?.resumeAudio();
    setNeedsTap(false);
  }, []);

  return { status, session, error, needsTap, start, stop, setMuted, resume };
}
