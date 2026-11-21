/** Small text helpers for plain-language UI. */

export const sentenceCase = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** "Pump P-14" -> "pump P-14" for use mid-sentence (keeps names and ids as they are). */
export const midSentence = (s: string) => (s ? s[0].toLowerCase() + s.slice(1) : s);

export const timeOf = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
