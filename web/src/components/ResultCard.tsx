import { useState } from 'react';
import { sentenceCase } from '../lib/format';
import type { Analysis } from '../lib/types';
import { playAudio, stopAudio } from '../lib/audio';
import { UnusualBar } from './Bits';

interface Props {
  analysis: Analysis;
  facts?: Record<string, string>;
}

export function ResultCard({ analysis, facts = {} }: Props) {
  const [playing, setPlaying] = useState(false);
  if (!analysis.ok) {
    return (
      <section className="card result-card">
        <span className="badge badge-sound">Let's try again</span>
        <h2 className="result-title">I couldn't hear it clearly</h2>
        <p className="muted">{analysis.tip}</p>
      </section>
    );
  }
  const problem = analysis.band !== 'normal';
  const title =
    analysis.band === 'normal'
      ? 'It sounds normal'
      : analysis.confidence === 'not sure'
        ? 'It sounds different, but I am not sure why'
        : `It sounds like ${analysis.label}`;

  const compare = async () => {
    if (playing) {
      stopAudio();
      setPlaying(false);
      return;
    }
    setPlaying(true);
    if (analysis.baseline_url) await playAudio(analysis.baseline_url);
    if (analysis.clip_url) await playAudio(analysis.clip_url);
    setPlaying(false);
  };

  return (
    <section className="card result-card">
      <span className={`badge ${problem ? 'badge-problem' : 'badge-ok'}`}>
        {analysis.band === 'very unusual' ? 'Problem found' : analysis.band === 'slightly unusual' ? 'Keep an eye on it' : 'Sounds normal'}
      </span>
      <h2 className="result-title">{title}</h2>
      {analysis.baseline_url && (
        <button className="btn" onClick={compare}>
          {playing ? '■ Stop' : '▶ Hear normal vs now'}
        </button>
      )}
      <p className="muted small">How unusual it sounds</p>
      <UnusualBar analysis={analysis} />
      <dl className="facts">
        <div>
          <dt>How sure</dt>
          <dd>{sentenceCase(analysis.confidence ?? '')}</dd>
        </div>
        {facts.seen_before && (
          <div>
            <dt>Seen before</dt>
            <dd>{facts.seen_before}</dd>
          </div>
        )}
        {facts.spare && (
          <div>
            <dt>Spare part</dt>
            <dd>{sentenceCase(facts.spare)}</dd>
          </div>
        )}
        {problem && analysis.alternatives && analysis.alternatives.length > 0 && (
          <div>
            <dt>Could also be</dt>
            <dd>{analysis.alternatives.join(', ')}</dd>
          </div>
        )}
      </dl>
    </section>
  );
}
