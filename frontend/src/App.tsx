import { Routes, Route } from "react-router-dom";
import { t } from "./design/tokens";
import { AppHeader } from "./components/AppHeader";
import { Explore } from "./pages/Explore";
import { Institutions } from "./pages/Institutions";
import { RecordDetail } from "./pages/RecordDetail";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";

export default function App() {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: t.bg, color: t.fg, fontFamily: t.sans }}>
      <AppHeader />
      <Routes>
        <Route path="/" element={<Explore />} />
        <Route path="/institutions" element={<Institutions />} />
        <Route path="/record/:id" element={<RecordDetail />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/login" element={<Login />} />
      </Routes>
    </div>
  );
}
