import { useEffect, useMemo, useState } from "react";
import L, { type LatLngBoundsExpression } from "leaflet";
import {
  CircleMarker,
  MapContainer,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { LocateFixed, Minus, Plus } from "lucide-react";
import type { DetailedRoute, Engineer, OverviewRoutesResponse, RequestItem } from "../api/types";
import { StatusPill, formatTime } from "./ui";

interface MapPanelProps {
  requests: RequestItem[];
  engineers: Engineer[];
  routes: OverviewRoutesResponse;
  detailedRoute: DetailedRoute | null;
  selectedRequestId: string | null;
  selectedEngineerId: string | null;
  routeLoading: boolean;
  onSelectRequest: (requestId: string) => void;
}

type PointCluster = { key: string; center: [number, number]; requests: RequestItem[] };

function ZoomObserver({ onZoom }: { onZoom: (zoom: number) => void }) {
  useMapEvents({ zoomend: (event) => onZoom(event.target.getZoom()) });
  return null;
}

function MapControls({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap();
  return (
    <div className="map-controls leaflet-top leaflet-right">
      <div className="leaflet-control">
        <button onClick={() => map.zoomIn()} aria-label="Приблизить"><Plus size={18} /></button>
        <button onClick={() => map.zoomOut()} aria-label="Отдалить"><Minus size={18} /></button>
        <button onClick={() => map.fitBounds(bounds, { padding: [32, 32] })} aria-label="Показать все"><LocateFixed size={17} /></button>
      </div>
    </div>
  );
}

function routeLatLngs(coordinates: [number, number][]) {
  return coordinates.map(([lon, lat]) => [lat, lon] as [number, number]);
}

export function MapPanel(props: MapPanelProps) {
  const [zoom, setZoom] = useState(11);
  const bounds = useMemo<LatLngBoundsExpression>(() => {
    const points = props.requests.map((request) => [request.coordinates[1], request.coordinates[0]] as [number, number]);
    return points.length ? points : [[55.62, 37.66], [55.82, 37.92]];
  }, [props.requests]);

  const clusters = useMemo<PointCluster[]>(() => {
    if (zoom >= 13) {
      return props.requests.map((request) => ({
        key: request.id,
        center: [request.coordinates[1], request.coordinates[0]],
        requests: [request],
      }));
    }
    const precision = zoom <= 10 ? 1 : 2;
    const grouped = new Map<string, RequestItem[]>();
    props.requests.forEach((request) => {
      const key = `${request.coordinates[0].toFixed(precision)}:${request.coordinates[1].toFixed(precision)}`;
      grouped.set(key, [...(grouped.get(key) ?? []), request]);
    });
    return [...grouped.entries()].map(([key, requests]) => ({
      key,
      center: [
        requests.reduce((sum, item) => sum + item.coordinates[1], 0) / requests.length,
        requests.reduce((sum, item) => sum + item.coordinates[0], 0) / requests.length,
      ],
      requests,
    }));
  }, [props.requests, zoom]);

  const selectedEngineer = props.engineers.find((item) => item.id === props.selectedEngineerId);
  const displayedRoutes = useMemo(() => {
    if (!props.selectedEngineerId) return props.routes.routes;
    const detail =
      props.detailedRoute?.engineer_id === props.selectedEngineerId
        ? props.detailedRoute
        : null;
    return props.routes.routes.map((overview) =>
      detail && overview.engineer_id === props.selectedEngineerId ? detail : overview,
    );
  }, [props.detailedRoute, props.routes.routes, props.selectedEngineerId]);

  return (
    <div className="map-panel">
      <MapContainer bounds={bounds} zoomControl={false} preferCanvas className="leaflet-map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ZoomObserver onZoom={setZoom} />
        <MapControls bounds={bounds} />

        {displayedRoutes.map((route) => {
          if (!route.geometry) return null;
          const engineer = props.engineers.find((item) => item.id === route.engineer_id);
          const isSelected = route.engineer_id === props.selectedEngineerId;
          return (
            <Polyline
              key={`${route.engineer_id}-${"stops" in route ? "detailed" : "overview"}`}
              positions={routeLatLngs(route.geometry.coordinates)}
              pathOptions={{
                color: engineer?.color ?? "#6f4cff",
                weight: isSelected ? 6 : 3,
                opacity: props.selectedEngineerId && !isSelected ? 0.18 : isSelected ? 0.95 : 0.62,
                lineCap: "round",
                lineJoin: "round",
              }}
            />
          );
        })}

        {clusters.map((cluster) => {
          const request = cluster.requests[0];
          const selected = cluster.requests.some((item) => item.id === props.selectedRequestId);
          const urgent = cluster.requests.some((item) => item.priority_rank === 1);
          const fillColor = selected ? "#121316" : urgent ? "#ef6b4a" : request.status === "COMPLETED" ? "#24a071" : "#ffdb00";
          return (
            <CircleMarker
              key={cluster.key}
              center={cluster.center}
              radius={cluster.requests.length > 1 ? 15 : selected ? 10 : 8}
              pathOptions={{ color: "#fff", weight: 3, fillColor, fillOpacity: 1 }}
              eventHandlers={{ click: () => props.onSelectRequest(request.id) }}
            >
              <Tooltip direction="top" offset={[0, -10]} opacity={1} className="request-tooltip">
                {cluster.requests.length > 1 ? (
                  <div className="cluster-tooltip"><strong>{cluster.requests.length} заявок</strong><span>Нажмите, чтобы открыть верхнюю</span></div>
                ) : (
                  <div className="map-tooltip-card">
                    <div><strong>{request.external_id}</strong><StatusPill status={request.status} /></div>
                    <span>{request.bk_type} · {request.district}</span>
                    <b>{formatTime(request.window_start)}–{formatTime(request.window_end)}</b>
                  </div>
                )}
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
      <div className="map-key">
        <span><i className="map-dot urgent" /> Авария</span>
        <span><i className="map-dot active" /> В работе</span>
        <span><i className="map-dot done" /> Выполнено</span>
      </div>
      {selectedEngineer ? (
        <div className="map-route-caption">
          <i style={{ background: selectedEngineer.color }} />
          <div><strong>{selectedEngineer.name}</strong><span>{selectedEngineer.request_ids.length} заявки в маршруте</span></div>
          {props.routeLoading ? <span className="mini-spinner" /> : <em>точный маршрут</em>}
        </div>
      ) : null}
    </div>
  );
}
