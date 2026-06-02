import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { useAuth } from "../auth";
import { Button } from "../components/ui";

const DEMO = [
  ["curator@tbia.test", "contributor"],
  ["reviewer@tbia.test", "reviewer"],
  ["admin@tbia.test", "admin"],
];

export function Login() {
  const { t: tr } = useTranslation();
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("curator@tbia.test");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try { await login(email, password); nav("/"); }
    catch (err) { setError(err instanceof Error ? err.message : "Login failed"); }
  };

  const field: React.CSSProperties = {
    width: "100%", boxSizing: "border-box", padding: "7px 9px", fontSize: 13,
    border: `1px solid ${t.border}`, background: t.panelAlt, outline: "none", marginTop: 4,
  };

  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: t.bg }}>
      <form onSubmit={submit} style={{ width: 340, background: t.panel, border: `1px solid ${t.border}`, padding: 24 }}>
        <h2 style={{ margin: "0 0 16px", fontSize: 18, fontWeight: 600 }}>{tr("login.title")}</h2>
        <label style={{ fontSize: 11, color: t.fgMuted }}>{tr("login.email")}
          <input style={field} value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label style={{ fontSize: 11, color: t.fgMuted, display: "block", marginTop: 12 }}>{tr("login.password")}
          <input style={field} type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div style={{ color: t.danger, fontSize: 11, marginTop: 10 }}>{error}</div>}
        <div style={{ marginTop: 16 }}><Button primary>{tr("login.submit")}</Button></div>

        <div style={{ marginTop: 18, paddingTop: 14, borderTop: `1px solid ${t.borderSoft}` }}>
          <div style={{ fontSize: 10, color: t.fgSubtle, marginBottom: 6, fontFamily: t.mono }}>{tr("login.demo")} · pw: demo1234</div>
          {DEMO.map(([em, role]) => (
            <div key={em} onClick={() => { setEmail(em); setPassword("demo1234"); }} style={{
              display: "flex", justifyContent: "space-between", padding: "3px 6px", cursor: "pointer",
              fontSize: 11, fontFamily: t.mono, color: t.fgMuted, background: email === em ? t.accentSoft : "transparent",
            }}>
              <span>{em}</span><span>{role}</span>
            </div>
          ))}
        </div>
      </form>
    </div>
  );
}
