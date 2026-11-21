import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';
import AppHome from './pages/AppHome';
import NotBuilt from './pages/NotBuilt';

// Voice pages pull in the Agora SDKs (~1 MB gzipped); load them only when needed.
const Talk = lazy(() => import('./pages/Talk'));

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={null}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/app" element={<AppHome />} />
          <Route path="/app/talk" element={<Talk />} />
          <Route path="*" element={<NotBuilt />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
