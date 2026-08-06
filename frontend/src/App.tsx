import { Routes, Route } from "react-router-dom";
import { t } from "./design/tokens";
import { usePageviews } from "./analytics";
import { AppHeader } from "./components/AppHeader";
import { CookieConsent } from "./components/CookieConsent";
import { Home } from "./pages/Home";
import { Explore } from "./pages/Explore";
import { Institutions } from "./pages/Institutions";
import { Volunteers } from "./pages/Volunteers";
import { Collector } from "./pages/Collector";
import { RecordDetail } from "./pages/RecordDetail";
import { Dashboard } from "./pages/Dashboard";
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
        <Route path="/volunteers" element={<Volunteers />} />
        <Route path="/collectors/:id" element={<Collector />} />
        <Route path="/record/:id" element={<RecordDetail />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/login" element={<Login />} />
        <Route path="/auth/orcid/callback" element={<OrcidCallback />} />
      </Routes>
      <CookieConsent />
    </div>
  );
}
