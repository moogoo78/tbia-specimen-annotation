import { Routes, Route, Navigate } from "react-router-dom";
import { t } from "./design/tokens";
import { usePageviews } from "./analytics";
import { useSeo } from "./seo/useSeo";
import { AppHeader } from "./components/AppHeader";
import { CookieConsent } from "./components/CookieConsent";
import { Landing } from "./pages/Landing";
import { Browse } from "./pages/Browse";
import { Explore } from "./pages/Explore";
import { Species } from "./pages/Species";
import { Institutions } from "./pages/Institutions";
import { Volunteers } from "./pages/Volunteers";
import { Collector } from "./pages/Collector";
import { Collectors } from "./pages/Collectors";
import { History } from "./pages/History";
import { Story } from "./pages/Story";
import { StoryTopic } from "./pages/StoryTopic";
import { RecordDetail } from "./pages/RecordDetail";
import { Dashboard } from "./pages/Dashboard";
import { Guide } from "./pages/Guide";
import { AiWalkthrough } from "./pages/AiWalkthrough";
import { Login } from "./pages/Login";
import { OrcidCallback } from "./pages/OrcidCallback";

export default function App() {
  // Title/description for the current route, from src/seo/pages.json — the same
  // file scripts/prerender.mjs bakes into the served HTML. Called once here
  // rather than per page: it keys off the location, and a page wanting a title
  // from loaded data can still call useSeo({ title }) itself.
  useSeo();
  usePageviews();

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: t.bg, color: t.fg, fontFamily: t.sans }}>
      <AppHeader />
      <Routes>
        <Route path="/" element={<Landing />} />
        {/* The hub that used to be the landing page — kept whole, moved here. */}
        <Route path="/browse" element={<Browse />} />
        <Route path="/explore" element={<Explore />} />
        <Route path="/species" element={<Species />} />
        <Route path="/institutions" element={<Institutions />} />
        <Route path="/contributors" element={<Volunteers />} />
        {/* The board was /volunteers (志工) until the rename; keep old links working. */}
        <Route path="/volunteers" element={<Navigate to="/contributors" replace />} />
        <Route path="/collectors" element={<Collectors />} />
        <Route path="/collectors/:id" element={<Collector />} />
        <Route path="/story" element={<Story />} />
        <Route path="/story/:key" element={<StoryTopic />} />
        {/* A topic of /story, but keeps its own route — it is deep-linked from
            collector pages and from the chronology's own citation. */}
        <Route path="/history" element={<History />} />
        <Route path="/record/:id" element={<RecordDetail />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/guide" element={<Guide />} />
        <Route path="/guide/ai-transcribe" element={<AiWalkthrough />} />
        <Route path="/login" element={<Login />} />
        <Route path="/auth/orcid/callback" element={<OrcidCallback />} />
      </Routes>
      <CookieConsent />
    </div>
  );
}
