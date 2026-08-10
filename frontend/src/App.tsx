import { Routes, Route, Navigate } from "react-router-dom";
import { t } from "./design/tokens";
import { usePageviews } from "./analytics";
import { AppHeader } from "./components/AppHeader";
import { CookieConsent } from "./components/CookieConsent";
import { Home } from "./pages/Home";
import { Explore } from "./pages/Explore";
import { Institutions } from "./pages/Institutions";
import { Volunteers } from "./pages/Volunteers";
import { Collector } from "./pages/Collector";
import { Collectors } from "./pages/Collectors";
import { History } from "./pages/History";
import { RecordDetail } from "./pages/RecordDetail";
import { Dashboard } from "./pages/Dashboard";
import { Guide } from "./pages/Guide";
import { Login } from "./pages/Login";
import { OrcidCallback } from "./pages/OrcidCallback";

export default function App() {
  usePageviews();

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: t.bg, color: t.fg, fontFamily: t.sans }}>
      <AppHeader />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/explore" element={<Explore />} />
        <Route path="/institutions" element={<Institutions />} />
        <Route path="/contributors" element={<Volunteers />} />
        {/* The board was /volunteers (志工) until the rename; keep old links working. */}
        <Route path="/volunteers" element={<Navigate to="/contributors" replace />} />
        <Route path="/collectors" element={<Collectors />} />
        <Route path="/collectors/:id" element={<Collector />} />
        <Route path="/history" element={<History />} />
        <Route path="/record/:id" element={<RecordDetail />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/guide" element={<Guide />} />
        <Route path="/login" element={<Login />} />
        <Route path="/auth/orcid/callback" element={<OrcidCallback />} />
      </Routes>
      <CookieConsent />
    </div>
  );
}
