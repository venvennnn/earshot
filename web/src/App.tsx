import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';
import AppHome from './pages/AppHome';
import NotFound from './pages/NotFound';

// Voice pages pull in the Agora SDK; the dashboard is desktop-only. Load them only when needed.
const Talk = lazy(() => import('./pages/Talk'));
const Listen = lazy(() => import('./pages/Listen'));
const Result = lazy(() => import('./pages/Result'));
const TapTest = lazy(() => import('./pages/TapTest'));
const AddMachine = lazy(() => import('./pages/AddMachine'));
const Jobs = lazy(() => import('./pages/Jobs'));
const History = lazy(() => import('./pages/History'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Recipient = lazy(() => import('./pages/Recipient'));

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={null}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/app" element={<AppHome />} />
          <Route path="/app/talk" element={<Talk />} />
          <Route path="/app/listen" element={<Listen />} />
          <Route path="/app/result" element={<Result />} />
          <Route path="/app/tap" element={<TapTest />} />
          <Route path="/app/add" element={<AddMachine />} />
          <Route path="/app/jobs" element={<Jobs />} />
          <Route path="/app/history" element={<History />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/recipient" element={<Recipient />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
