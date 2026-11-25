// 使用者管理 — admin only. Every user, what they have contributed, and the one
// thing an admin sets about them: the identifier flag (backend api/users.py).
//
// Role is shown, not edited — it still has no editing surface. Drafts are
// counted in a user's detail but never listed: they are private working state
// even from an admin (see the module docstring in api/users.py).
//
// The selected user is `?u=<id>`, so a user's detail can be linked to and
// survives a reload; the list's own filters stay in component state.
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { t } from "../design/tokens";
import { Icon } from "../design/Icon";
import { api } from "../api/client";
import { useAuth } from "../auth";
import type { AdminUser, AdminUserSort } from "../api/types";
import { Spinner, StatusPill } from "../components/ui";
import { Pager } from "../components/Contributions";
import { IdentificationCard } from "../components/IdentificationPanel";

const PAGE = 50;
const ROLES = ["contributor", "reviewer", "admin"];
const STATUS_ORDER = ["submitted", "accepted", "merged", "rejected", "draft"];

const day = (iso?: string | null) => (iso ? iso.slice(0, 10) : "—");

export function AdminUsers() {
  const { t: tr } = useTranslation();
  const { user, loading } = useAuth();
  const [params, setParams] = useSearchParams();
  const selected = Number(params.get("u")) || null;
  const select = (id: number | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("u", String(id)); else next.delete("u");
    setParams(next, { replace: true });
  };

  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [onlyIdent, setOnlyIdent] = useState(false);
  const [sort, setSort] = useState<string>("name");
  const [offset, setOffset] = useState(0);
  const isAdmin = user?.role === "admin";

  const list = useQuery({
    queryKey: ["admin-users", q.trim(), role, onlyIdent, sort, offset],
    queryFn: () => api.adminUsers({ q: q.trim() || undefined, role: role || undefined,
      identifiers: onlyIdent, sort, limit: PAGE, offset }),
    enabled: isAdmin,
    placeholderData: (prev) => prev,
  });

  if (loading) return <div style={{ padding: 16 }}><Spinner /></div>;
  if (!isAdmin) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: t.fgMuted, fontSize: 13 }}>
        {user ? tr("admin.adminOnly") : <Link to="/login" style={{ color: t.accent }}>{tr("nav.login")} →</Link>}
      </div>
    );
  }

  // Any filter change goes back to the first page.
  const filter = <T,>(set: (v: T) => void) => (v: T) => { set(v); setOffset(0); };
  // Click a header: same column flips direction, a new column starts on its natural order.
  const sortBy = (k: AdminUserSort) => filter(setSort)(sort === k ? `-${k}` : k);

  const items = list.data?.items ?? [];
  return (
    <div data-admin-users style={{ flex: 1, overflow: "auto", padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "0 0 6px" }}>
        <h2 style={{ fontSize: 18, fontWeight: 600, margin: 0 }}>{tr("admin.usersTitle")}</h2>
        <span style={{ fontFamily: t.mono, fontSize: 12, color: t.fgMuted }}>{(list.data?.total ?? 0).toLocaleString()}</span>
      </div>
      <p style={{ fontSize: 11, color: t.fgMuted, margin: "0 0 12px", maxWidth: 720, lineHeight: 1.6 }}>
        {tr("admin.usersBlurb")}
      </p>

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <input data-admin-search value={q} onChange={(e) => filter(setQ)(e.target.value)} placeholder={tr("dash.identifiersSearch")}
          style={{ fontSize: 12, padding: "4px 8px", border: `1px solid ${t.border}`, fontFamily: t.sans, width: 240, maxWidth: "100%" }} />
        <select value={role} onChange={(e) => filter(setRole)(e.target.value)}
          style={{ fontSize: 12, padding: "3px 6px", border: `1px solid ${t.border}`, fontFamily: t.sans, background: t.panel }}>
          <option value="">{tr("admin.allRoles")}</option>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <label style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, cursor: "pointer" }}>
          <input type="checkbox" checked={onlyIdent} onChange={(e) => filter(setOnlyIdent)(e.target.checked)} />
          {tr("admin.onlyIdentifiers")}
        </label>
        {list.isFetching && <span style={{ fontSize: 11, color: t.fgSubtle }}>…</span>}
      </div>

      <div style={{ display: "flex", gap: 14, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 620px", minWidth: 0, overflowX: "auto", background: t.panel, border: `1px solid ${t.border}` }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, minWidth: 640 }}>
            <thead>
              <tr style={{ background: t.panelAlt }}>
                <Th label={tr("admin.colUser")} k="name" sort={sort} onSort={sortBy} />
                <Th label={tr("admin.colRole")} />
                <Th label={tr("admin.colIdentifier")} center />
                <Th label={tr("admin.colAnnotations")} k="annotations" sort={sort} onSort={sortBy} right />
                <Th label={tr("admin.colIdentifications")} k="identifications" sort={sort} onSort={sortBy} right />
                <Th label={tr("admin.colJoined")} k="created" sort={sort} onSort={sortBy} right />
                <Th label={tr("admin.colLastLogin")} k="last_login" sort={sort} onSort={sortBy} right />
              </tr>
            </thead>
            <tbody>
              {list.isLoading && <tr><td colSpan={7}><Spinner /></td></tr>}
              {!list.isLoading && items.length === 0 && (
                <tr><td colSpan={7} style={{ padding: 10, color: t.fgSubtle, fontSize: 11 }}>{tr("dash.identifiersNoMatch")}</td></tr>
              )}
              {items.map((u) => <UserRow key={u.id} u={u} on={u.id === selected} onSelect={() => select(u.id === selected ? null : u.id)} />)}
            </tbody>
          </table>
          <Pager total={list.data?.total ?? 0} limit={PAGE} offset={offset} onOffset={setOffset} />
        </div>
        {selected && <UserDetail id={selected} onClose={() => select(null)} />}
      </div>
    </div>
  );
}

function Th({ label, k, sort, onSort, right, center }: {
  label: string; k?: AdminUserSort; sort?: string; onSort?: (k: AdminUserSort) => void; right?: boolean; center?: boolean;
}) {
  const active = k && (sort === k || sort === `-${k}`);
  const style: React.CSSProperties = {
    padding: "6px 10px", fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3,
    color: active ? t.fg : t.fgMuted, textAlign: right ? "right" : center ? "center" : "left",
    borderBottom: `1px solid ${t.border}`, whiteSpace: "nowrap",
  };
  if (!k || !onSort) return <th style={style}>{label}</th>;
  return (
    <th style={style} aria-sort={active ? (sort!.startsWith("-") ? "descending" : "ascending") : undefined}>
      <button onClick={() => onSort(k)} style={{
        border: "none", background: "transparent", padding: 0, cursor: "pointer", font: "inherit",
        color: "inherit", textTransform: "inherit", letterSpacing: "inherit",
      }}>
        {label}{active ? (sort!.startsWith("-") ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
}

/** The flag is set in place; the row and any open detail both refresh. */
function IdentifierToggle({ u }: { u: AdminUser }) {
  const qc = useQueryClient();
  const { user: me, refreshUser } = useAuth();
  const save = useMutation({
    mutationFn: (on: boolean) => api.setIdentifier(u.id, on),
    onSuccess: (next) => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      qc.invalidateQueries({ queryKey: ["admin-user", u.id] });
      if (next.id === me?.id) refreshUser();  // your own flag moves your own form
    },
  });
  return (
    <input type="checkbox" data-identifier-toggle={u.id} checked={u.is_identifier} disabled={save.isPending}
      title={save.isError ? (save.error as Error).message : undefined}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => save.mutate(e.target.checked)} />
  );
}

function UserRow({ u, on, onSelect }: { u: AdminUser; on: boolean; onSelect: () => void }) {
  const td: React.CSSProperties = { padding: "6px 10px", borderBottom: `1px solid ${t.borderSoft}`, verticalAlign: "middle" };
  const num: React.CSSProperties = { ...td, textAlign: "right", fontFamily: t.mono, whiteSpace: "nowrap" };
  return (
    <tr data-user-row={u.id} onClick={onSelect} style={{ cursor: "pointer", background: on ? t.accentSoft : "transparent" }}>
      <td style={{ ...td, maxWidth: 260 }}>
        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: on ? 600 : 400 }}>{u.display_name}</div>
        <div style={{ fontSize: 10, fontFamily: t.mono, color: t.fgSubtle, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {u.orcid ?? u.email ?? `#${u.id}`}
        </div>
      </td>
      <td style={{ ...td, fontFamily: t.mono, fontSize: 11, color: u.role === "contributor" ? t.fgMuted : t.fg }}>{u.role}</td>
      <td style={{ ...td, textAlign: "center" }}><IdentifierToggle u={u} /></td>
      <td style={num}><Counts n={u.n_annotations} ok={u.n_annotations_accepted} /></td>
      <td style={num}><Counts n={u.n_identifications} ok={u.n_identifications_accepted} /></td>
      <td style={{ ...num, color: t.fgMuted, fontSize: 11 }}>{day(u.created)}</td>
      <td style={{ ...num, color: t.fgMuted, fontSize: 11 }}>{day(u.last_login_at)}</td>
    </tr>
  );
}

/** "accepted / all non-draft" */
function Counts({ n, ok }: { n: number; ok: number }) {
  if (!n) return <span style={{ color: t.fgSubtle }}>0</span>;
  return <span><span style={{ color: t.ok, fontWeight: 600 }}>{ok.toLocaleString()}</span><span style={{ color: t.fgSubtle }}> / {n.toLocaleString()}</span></span>;
}

function UserDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const { t: tr } = useTranslation();
  const d = useQuery({ queryKey: ["admin-user", id], queryFn: () => api.adminUser(id) });
  const u = d.data?.user;
  const fact = (label: string, value: React.ReactNode) => (
    <div style={{ display: "flex", gap: 8, fontSize: 12, padding: "2px 0" }}>
      <span style={{ width: 110, flexShrink: 0, color: t.fgMuted, fontSize: 11 }}>{label}</span>
      <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>{value}</span>
    </div>
  );
  return (
    <div data-user-detail style={{ flex: "1 1 340px", maxWidth: 480, background: t.panel, border: `1px solid ${t.border}`, padding: "10px 12px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Icon name="user" size={14} />
        <div style={{ fontSize: 14, fontWeight: 600, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {u?.display_name ?? "…"}
        </div>
        <button onClick={onClose} aria-label={tr("admin.close")} style={{ border: "none", background: "transparent", cursor: "pointer", color: t.fgMuted, padding: 2 }}>
          <Icon name="x" size={12} />
        </button>
      </div>
      {d.isLoading && <Spinner />}
      {d.isError && <div style={{ fontSize: 11, color: t.danger }}>{(d.error as Error).message}</div>}
      {u && d.data && (
        <>
          {fact("ORCID", u.orcid
            ? <a href={`https://orcid.org/${u.orcid}`} target="_blank" rel="noreferrer noopener" style={{ color: t.accent, fontFamily: t.mono }}>{u.orcid} ↗</a>
            : <span style={{ color: t.fgSubtle }}>—</span>)}
          {u.email && fact(tr("admin.email"), <span style={{ fontFamily: t.mono }}>{u.email}</span>)}
          {fact(tr("admin.colRole"), <span style={{ fontFamily: t.mono }}>{u.role}</span>)}
          {fact(tr("admin.colIdentifier"), <label style={{ display: "inline-flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
            <IdentifierToggle u={u} />{u.is_identifier ? tr("admin.yes") : tr("admin.no")}
          </label>)}
          {fact(tr("admin.publicName"), u.show_in_ranking
            ? (u.public_display_name || u.display_name)
            : <span style={{ color: t.fgSubtle }}>{tr("admin.notPublished")}</span>)}
          {fact(tr("admin.colJoined"), day(u.created))}
          {fact(tr("admin.colLastLogin"), day(u.last_login_at))}

          <StatusCounts title={tr("admin.colAnnotations")} counts={d.data.annotations_by_status} />
          <StatusCounts title={tr("admin.colIdentifications")} counts={d.data.identifications_by_status} />
          <div style={{ fontSize: 10, color: t.fgSubtle, marginTop: 4 }}>{tr("admin.draftsCounted")}</div>

          <Link to={`/contributors/${u.id}`} style={{ display: "inline-block", marginTop: 8, fontSize: 12, color: t.accent }}>
            {tr("admin.publicPage")} →
          </Link>

          {d.data.recent_identifications.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: t.fgMuted, textTransform: "uppercase", letterSpacing: 0.3 }}>
                {tr("admin.recentIdentifications")}
              </div>
              {d.data.recent_identifications.map((i) => (
                <div key={i.id}>
                  <Link to={`/record/${encodeURIComponent(i.occurrence_id)}`}
                    style={{ display: "block", fontSize: 10, fontFamily: t.mono, color: t.accent, textDecoration: "none", marginTop: 6 }}>
                    {i.occurrence_id}{i.dataset_name ? ` · ${i.dataset_name}` : ""}
                  </Link>
                  <IdentificationCard i={i} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatusCounts({ title, counts }: { title: string; counts: Record<string, number> }) {
  const shown = STATUS_ORDER.filter((s) => counts[s]);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 8, fontSize: 12 }}>
      <span style={{ width: 110, flexShrink: 0, color: t.fgMuted, fontSize: 11 }}>{title}</span>
      {shown.length === 0 && <span style={{ color: t.fgSubtle }}>0</span>}
      {shown.map((s) => (
        <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <StatusPill status={s} /><span style={{ fontFamily: t.mono }}>{counts[s].toLocaleString()}</span>
        </span>
      ))}
    </div>
  );
}
