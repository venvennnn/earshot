import { Link } from 'react-router-dom';
import type { Analysis } from '../lib/types';
import { ChevronLeftIcon } from './Icons';

export function TopBar({ title, sub, back = '/app', right }: { title: string; sub?: string; back?: string; right?: React.ReactNode }) {
  return (
    <header className="topbar">
      <Link to={back} className="icon-btn" aria-label="Back">
        <ChevronLeftIcon />
      </Link>
      <div className="topbar-title">
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {right}
    </header>
  );
}

const BAND_COLOR: Record<string, string> = {
  normal: 'var(--ok)',
  'slightly unusual': 'var(--sound)',
  'very unusual': 'var(--problem)',
};

/** Normal → Very unusual bar. Shows position only, never the raw score. */
export function UnusualBar({ analysis }: { analysis: Analysis }) {
  const score = analysis.anomaly_score ?? 0;
  const band = analysis.band ?? 'normal';
  return (
    <div className="unusual">
      <div className="unusual-track" role="img" aria-label={`How unusual it sounds: ${band}`}>
        <div className="unusual-fill" style={{ width: `${Math.max(4, score * 100)}%`, background: BAND_COLOR[band] }} />
      </div>
      <div className="unusual-labels">
        <span>Normal</span>
        <span style={{ color: band === 'normal' ? undefined : BAND_COLOR[band] }}>Very unusual</span>
      </div>
    </div>
  );
}

/** Healthy (grey) vs now (orange), 24 bands from low to high tones. */
export function SpectrumChart({ baseline, now, height = 150 }: { baseline: number[]; now: number[]; height?: number }) {
  const n = baseline.length;
  const w = 100 / n;
  return (
    <div className="spectrum">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" role="img" aria-label="Healthy sound compared with now">
        {baseline.map((b, i) => {
          const hb = Math.max(2, b * (height - 6));
          const hn = Math.max(2, now[i] * (height - 6));
          return (
            <g key={i}>
              <rect x={i * w + w * 0.12} y={height - hb} width={w * 0.36} height={hb} rx={0.4} fill="#B9BEC7" />
              <rect x={i * w + w * 0.52} y={height - hn} width={w * 0.36} height={hn} rx={0.4} fill="var(--sound)" />
            </g>
          );
        })}
      </svg>
      <div className="spectrum-axis">
        <span>Low tones</span>
        <span>High tones</span>
      </div>
    </div>
  );
}
