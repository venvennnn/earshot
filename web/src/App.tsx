import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Home from './pages/Home';
import AppHome from './pages/AppHome';
import NotBuilt from './pages/NotBuilt';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/app" element={<AppHome />} />
        <Route path="*" element={<NotBuilt />} />
      </Routes>
    </BrowserRouter>
  );
}
