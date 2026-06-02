import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { useNavigate } from "react-router-dom";
import { t, toneFor } from "../design/tokens";
import type { OccurrenceRow } from "../api/types";

export function MapView({ rows }: { rows: OccurrenceRow[] }) {
  const nav = useNavigate();
  const pts = rows.filter((r) => r.std_lat != null && r.std_lon != null);
  // Default view over Taiwan.
  return (
    <div style={{ flex: 1, position: "relative" }}>
      <MapContainer center={[23.7, 121]} zoom={7} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          attribution='&copy; OpenStreetMap'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {pts.map((r) => (
          <CircleMarker key={r.id} center={[r.std_lat!, r.std_lon!]} radius={5}
            pathOptions={{ color: toneFor(r.bio_group), fillColor: toneFor(r.bio_group), fillOpacity: 0.7, weight: 1 }}>
            <Popup>
              <div style={{ fontFamily: t.sans, fontSize: 12, minWidth: 160 }}>
                <div style={{ fontFamily: t.mono, fontSize: 10, color: t.fgMuted }}>{r.catalog_number}</div>
                <div style={{ fontStyle: "italic", fontWeight: 600 }}>{r.scientific_name || "—"}</div>
                <div style={{ color: t.fgMuted, fontSize: 11 }}>{r.locality || ""} {r.county || ""}</div>
                <a onClick={() => nav(`/record/${r.id}`)} style={{ color: t.accent, cursor: "pointer", fontSize: 11 }}>open ↗</a>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
      <div style={{
        position: "absolute", bottom: 8, left: 8, zIndex: 1000, background: t.panel,
        border: `1px solid ${t.border}`, padding: "3px 8px", fontSize: 10, color: t.fgMuted, fontFamily: t.mono,
      }}>{pts.length} / {rows.length} georeferenced on this page</div>
    </div>
  );
}
