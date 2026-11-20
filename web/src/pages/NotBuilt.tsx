import { Link, useLocation } from 'react-router-dom';
import { Logo } from '../components/Logo';

/** Shown for screens that are not part of the build yet, or unknown URLs. */
export default function NotBuilt() {
  const { pathname } = useLocation();
  return (
    <main style={{ padding: 24, maxWidth: 480, margin: '0 auto', display: 'grid', gap: 16 }}>
      <Logo />
      <h1 style={{ fontSize: 22 }}>This screen isn't available yet</h1>
      <p style={{ color: 'var(--muted)' }}>
        <span className="mono">{pathname}</span> is not part of this build.
      </p>
      <Link className="btn" to="/app">Back to the app</Link>
    </main>
  );
}
