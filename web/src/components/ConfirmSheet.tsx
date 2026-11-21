import { useState } from 'react';
import { api, type TurnReply } from '../lib/api';
import type { Confirmation } from '../lib/types';
import { CheckIcon } from './Icons';

interface Props {
  confirmation: Confirmation;
  voice: boolean; // a live voice call can also hear "yes"
  onAnswered?: (reply: TurnReply) => void;
}

export function ConfirmSheet({ confirmation, voice, onAnswered }: Props) {
  const [decisionInFlight, setDecisionInFlight] = useState<'yes' | 'no' | null>(null);
  const [error, setError] = useState('');
  const waitingSecond = confirmation.status === 'second_approval';

  const answer = async (decision: 'yes' | 'no') => {
    setDecisionInFlight(decision);
    setError('');
    try {
      const response = await api.answer(confirmation.id, decision);
      onAnswered?.(response);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not go through.');
    } finally {
      setDecisionInFlight(null);
    }
  };

  return (
    <div className="sheet" role="dialog" aria-label={confirmation.question}>
      <div className="sheet-grip" />
      <h2>{confirmation.question}</h2>
      {confirmation.steps.length > 0 && (
        <>
          <p className="muted">If you say yes, I will:</p>
          <ul className="checklist">
            {confirmation.steps.map((s) => (
              <li key={s.text}>
                <span className="check-ok">
                  <CheckIcon />
                </span>
                {s.text}
              </li>
            ))}
          </ul>
        </>
      )}
      {waitingSecond ? (
        <p className="sheet-wait">Waiting for {confirmation.approver} to approve as well.</p>
      ) : (
        <>
          <div className="sheet-actions">
            <button className="btn btn-dark btn-lg" disabled={decisionInFlight !== null} onClick={() => answer('yes')}>
              {decisionInFlight === 'yes' ? 'Approving…' : 'Yes, go ahead'}
            </button>
            <button className="btn btn-lg" disabled={decisionInFlight !== null} onClick={() => answer('no')}>
              {decisionInFlight === 'no' ? 'Saving…' : 'Not now'}
            </button>
          </div>
          {error && <p className="error-text" role="alert">{error}</p>}
          {voice && <p className="muted center small">You can also just say "yes"</p>}
        </>
      )}
    </div>
  );
}
