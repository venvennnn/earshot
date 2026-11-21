import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { ListenPanel } from '../components/ListenPanel';
import { TopBar } from '../components/Bits';
import { useLive } from '../lib/events';
import { useAppSession } from '../lib/useAppSession';
import type { Mode } from '../lib/types';
import './app.css';
import './talk.css';

/** "Check a machine" without a voice call: pick a machine, record, then see and hear the result. */
export default function Listen() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { live } = useLive();
  const session = useAppSession();
  const asset = live?.assets.find((a) => a.id === params.get('asset'));

  if (!asset || !session) {
    return (
      <div className="phone">
        <main className="phone-body">
          <TopBar title="Check a machine" sub="Which one are you standing at?" />
          <div className="pick-list">
            {live?.assets.map((a) => (
              <button key={a.id} className="pick" onClick={() => navigate(`/app/listen?asset=${a.id}`)}>
                <span>{a.name}</span>
                <span className="muted small">{a.state === 'unset' ? 'Not set up yet: record its healthy sound first' : a.label}</span>
              </button>
            ))}
          </div>
        </main>
      </div>
    );
  }
  if (asset.state === 'unset') return <Navigate to={`/app/add?asset=${asset.id}`} replace />;
  const mode = (params.get('mode') as Mode | null) ?? asset.modes[0] ?? 'continuous';
  if (mode === 'tap') return <Navigate to={`/app/tap?asset=${asset.id}`} replace />;
  return (
    <div className="phone">
      <ListenPanel
        asset={asset}
        mode={mode}
        session={session}
        onDone={(res) =>
          navigate(`/app/result?asset=${asset.id}&session=${res.session}`, { state: { reply: res.reply, audio: res.audio_url, result: res.result } })
        }
        onCancel={() => navigate('/app')}
      />
    </div>
  );
}
