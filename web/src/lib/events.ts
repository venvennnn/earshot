/** Live state from the backend WebSocket bus, shared by every page. */
import { useEffect, useState } from 'react';
import { BACKEND_URL } from './api';
import type { LiveEvent, LiveState } from './types';

type Listener = (e: LiveEvent) => void;

let socket: WebSocket | null = null;
let current: LiveState | null = null;
let connected = false;
const stateSubs = new Set<() => void>();
const eventSubs = new Set<Listener>();

function connect(): void {
  if (socket) return;
  const ws = new WebSocket(`${BACKEND_URL.replace(/^http/, 'ws')}/ws`);
  socket = ws;
  ws.onopen = () => {
    connected = true;
    stateSubs.forEach((f) => f());
  };
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data as string) as { type: 'state'; state: LiveState } | { type: 'event'; event: LiveEvent };
    if (data.type === 'state') {
      current = data.state;
      stateSubs.forEach((f) => f());
    } else {
      eventSubs.forEach((f) => f(data.event));
    }
  };
  ws.onclose = () => {
    socket = null;
    connected = false;
    stateSubs.forEach((f) => f());
    window.setTimeout(connect, 1500);
  };
}

/** Current live state (null until the first snapshot) and whether the bus is connected. */
export function useLive(): { live: LiveState | null; connected: boolean } {
  const [, force] = useState(0);
  useEffect(() => {
    connect();
    const f = () => force((n) => n + 1);
    stateSubs.add(f);
    return () => {
      stateSubs.delete(f);
    };
  }, []);
  return { live: current, connected };
}

/** Subscribe to one-off events (capture_start, play_audio, …). */
export function useLiveEvent(handler: Listener): void {
  useEffect(() => {
    connect();
    eventSubs.add(handler);
    return () => {
      eventSubs.delete(handler);
    };
  }, [handler]);
}
