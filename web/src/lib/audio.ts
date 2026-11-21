import { mediaUrl } from './api';

let current: HTMLAudioElement | null = null;

/** Play one clip at a time (EarShot speaking through the phone or dashboard speaker). */
export function playAudio(path: string): Promise<void> {
  current?.pause();
  const audio = new Audio(mediaUrl(path));
  current = audio;
  return new Promise((resolve) => {
    audio.onended = () => resolve();
    audio.onerror = () => resolve();
    audio.play().catch(() => resolve());
  });
}

export function stopAudio(): void {
  current?.pause();
  current = null;
}
