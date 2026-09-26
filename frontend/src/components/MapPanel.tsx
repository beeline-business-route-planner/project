import { load } from "@2gis/mapgl";
import { useEffect, useMemo, useRef, useState } from "react";
import { Compass, LocateFixed, Map as MapIcon, Minus, Plus } from "lucide-react";
import type { DetailedRoute, Engineer, OverviewRoutesResponse, RequestItem } from "../api/types";
import { formatTime, statusLabels } from "./ui";

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

type MapGlApi = Awaited<ReturnType<typeof load>>;
type MapInstance = InstanceType<MapGlApi["Map"]>;
type Destructible = { destroy: () => void };
type PointCluster = { key: string; center: [number, number]; requests: RequestItem[] };

const MAP_KEY = import.meta.env.VITE_2GIS_KEY?.trim() ?? "";
// Start fetching the MapGL runtime as soon as this module is evaluated instead
// of waiting for the map component effect. The loader caches this promise.
const mapApiPromise = MAP_KEY ? load() : null;

function centerFromRequests(requests: RequestItem[]): [number, number] {
  if (!requests.length) return [37.72, 55.7];
  return [
    requests.reduce((sum, item) => sum + item.coordinates[0], 0) / requests.length,
    requests.reduce((sum, item) => sum + item.coordinates[1], 0) / requests.length,
  ];
}

function boundsFromRequests(requests: RequestItem[]) {
  const center = centerFromRequests(requests);
  if (requests.length < 2) {
    return { southWest: [center[0] - 0.02, center[1] - 0.012], northEast: [center[0] + 0.02, center[1] + 0.012] };
  }
  const longitudes = requests.map((item) => item.coordinates[0]);
  const latitudes = requests.map((item) => item.coordinates[1]);
  return {
    southWest: [Math.min(...longitudes), Math.min(...latitudes)],
    northEast: [Math.max(...longitudes), Math.max(...latitudes)],
  };
}

function colorWithAlpha(color: string, opacity: number) {
  const normalized = color.startsWith("#") ? color.slice(1) : color;
  if (!/^[0-9a-f]{6}$/i.test(normalized)) return color;
  return `#${normalized}${Math.round(Math.max(0, Math.min(1, opacity)) * 255).toString(16).padStart(2, "0")}`;
}

function createClusters(requests: RequestItem[], zoom: number): PointCluster[] {
  if (zoom >= 13) {
    return requests.map((request) => ({ key: request.id, center: request.coordinates, requests: [request] }));
  }
  const precision = zoom <= 10 ? 1 : 2;
  const grouped = new Map<string, RequestItem[]>();
  requests.forEach((request) => {
    const key = `${request.coordinates[0].toFixed(precision)}:${request.coordinates[1].toFixed(precision)}`;
    grouped.set(key, [...(grouped.get(key) ?? []), request]);
  });
  return [...grouped.entries()].map(([key, clusterRequests]) => ({
    key,
    center: [
      clusterRequests.reduce((sum, item) => sum + item.coordinates[0], 0) / clusterRequests.length,
      clusterRequests.reduce((sum, item) => sum + item.coordinates[1], 0) / clusterRequests.length,
    ],
    requests: clusterRequests,
  }));
}

function createMarkerContent(cluster: PointCluster, selectedRequestId: string | null, onSelectRequest: (requestId: string) => void) {
  const request = cluster.requests[0];
  const selected = cluster.requests.some((item) => item.id === selectedRequestId);
  const urgent = cluster.requests.some((item) => item.priority_rank === 1);
  const marker = document.createElement("button");
  marker.type = "button";
  marker.className = [
    "mapgl-request-marker",
    selected ? "is-selected" : "",
    urgent ? "is-urgent" : "",
    request.status === "COMPLETED" ? "is-completed" : "",
    cluster.requests.length > 1 ? "is-cluster" : "",
  ].filter(Boolean).join(" ");
  marker.setAttribute("aria-label", cluster.requests.length > 1 ? `${cluster.requests.length} заявок` : `Открыть заявку ${request.external_id}`);
  if (cluster.requests.length > 1) marker.textContent = String(cluster.requests.length);

  const tooltip = document.createElement("span");
  tooltip.className = "mapgl-request-tooltip";
  const title = document.createElement("strong");
  title.textContent = cluster.requests.length > 1 ? `${cluster.requests.length} заявок рядом` : request.external_id;
  const description = document.createElement("span");
  description.textContent = cluster.requests.length > 1 ? "Нажмите, чтобы открыть первую" : `${request.bk_type} · ${request.district}`;
  const meta = document.createElement("b");
  meta.textContent = cluster.requests.length > 1 ? "" : `${formatTime(request.window_start)}–${formatTime(request.window_end)} · ${statusLabels[request.status]}`;
  tooltip.append(title, description, meta);
  marker.appendChild(tooltip);
  marker.addEventListener("click", (event) => {
    event.stopPropagation();
    onSelectRequest(request.id);
  });
  return marker;
}

export function MapPanel(props: MapPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapInstance | null>(null);
  const initialCenter = useRef(centerFromRequests(props.requests));
  const [mapApi, setMapApi] = useState<MapGlApi | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(11);
  const [rotation, setRotation] = useState(0);
  const [pitch, setPitch] = useState(0);

  const selectedEngineer = props.engineers.find((item) => item.id === props.selectedEngineerId);
  const displayedRoutes = useMemo(() => {
    if (!props.selectedEngineerId) return props.routes.routes;
    const detail = props.detailedRoute?.engineer_id === props.selectedEngineerId ? props.detailedRoute : null;
    return props.routes.routes.map((overview) => detail && overview.engineer_id === props.selectedEngineerId ? detail : overview);
  }, [props.detailedRoute, props.routes.routes, props.selectedEngineerId]);
  const clusters = useMemo(() => createClusters(props.requests, zoom), [props.requests, zoom]);

  useEffect(() => {
    if (!MAP_KEY || !containerRef.current) {
      setMapError("Добавьте VITE_2GIS_KEY в frontend/.env");
      return;
    }
    let disposed = false;
    let map: MapInstance | null = null;
    setMapError(null);
    void mapApiPromise?.then((api) => {
      if (disposed || !containerRef.current) return;
      map = new api.Map(containerRef.current, {
        key: MAP_KEY,
        center: initialCenter.current,
        zoom: 11,
        zoomControl: false,
        enableTrackResize: true,
        defaultBackgroundColor: "#181818",
      });
      const handleFirstIdle = () => {
        if (!disposed) setMapReady(true);
        map?.off("idle", handleFirstIdle);
      };
      map.on("idle", handleFirstIdle);
      mapRef.current = map;
      setMapApi(api);
    }).catch(() => {
      if (!disposed) setMapError("Не удалось загрузить карту 2ГИС. Проверьте ключ и подключение к интернету.");
    });
    return () => {
      disposed = true;
      setMapApi(null);
      setMapReady(false);
      map?.destroy();
      if (mapRef.current === map) mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapApi || !map) return;
    const updateView = () => {
      setZoom(map.getZoom());
      setRotation(map.getRotation());
      setPitch(map.getPitch());
    };
    map.on("moveend", updateView);
    return () => { map.off("moveend", updateView); };
  }, [mapApi]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapApi || !map || !props.requests.length) return;
    map.fitBounds(boundsFromRequests(props.requests), {
      padding: { top: 76, right: 54, bottom: 54, left: 54 },
      maxZoom: 13,
      animation: { duration: 650, easing: "easeOutCubic" },
    });
  }, [mapApi, props.requests]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapApi || !map) return;
    const objects: Destructible[] = [];

    displayedRoutes.forEach((route) => {
      if (!route.geometry) return;
      const engineer = props.engineers.find((item) => item.id === route.engineer_id);
      const color = engineer?.color ?? "#ffd400";
      const selected = route.engineer_id === props.selectedEngineerId;
      const dimmed = Boolean(props.selectedEngineerId && !selected);
      if (selected) {
        objects.push(new mapApi.Polyline(map, {
          coordinates: route.geometry.coordinates,
          color: colorWithAlpha(color, .2),
          width: 13,
          zIndex: 9,
        }));
      }
      objects.push(new mapApi.Polyline(map, {
        coordinates: route.geometry.coordinates,
        color: colorWithAlpha(color, dimmed ? .18 : selected ? .96 : .68),
        width: selected ? 6 : 3,
        zIndex: selected ? 10 : 5,
      }));
    });

    clusters.forEach((cluster) => {
      const content = createMarkerContent(cluster, props.selectedRequestId, props.onSelectRequest);
      const size = cluster.requests.length > 1 ? 34 : cluster.requests.some((item) => item.id === props.selectedRequestId) ? 24 : 20;
      const baseZIndex = cluster.requests.some((item) => item.id === props.selectedRequestId) ? 30 : 20;
      const htmlMarker = new mapApi.HtmlMarker(map, {
        coordinates: cluster.center,
        html: content,
        anchor: [size / 2, size / 2],
        interactive: true,
        zIndex: baseZIndex,
      });
      const bringToFront = () => htmlMarker.setZIndex(1000);
      const restoreLayer = () => htmlMarker.setZIndex(baseZIndex);
      content.addEventListener("mouseenter", bringToFront);
      content.addEventListener("mouseleave", restoreLayer);
      content.addEventListener("focusin", bringToFront);
      content.addEventListener("focusout", restoreLayer);
      objects.push(htmlMarker);
    });

    return () => objects.forEach((object) => object.destroy());
  }, [clusters, displayedRoutes, mapApi, props.engineers, props.onSelectRequest, props.selectedEngineerId, props.selectedRequestId]);

  const fitAll = () => {
    const map = mapRef.current;
    if (!map || !props.requests.length) return;
    map.fitBounds(boundsFromRequests(props.requests), {
      padding: { top: 76, right: 54, bottom: 54, left: 54 },
      maxZoom: 13,
      animation: { duration: 500, easing: "easeOutCubic" },
    });
  };

  const resetNorth = () => {
    const map = mapRef.current;
    if (!map) return;
    map.setRotation(0, { duration: 350 });
    setRotation(0);
  };

  const reset2D = () => {
    const map = mapRef.current;
    if (!map) return;
    map.setPitch(0, { duration: 350 });
    map.setRotation(0, { duration: 350 });
    setPitch(0);
    setRotation(0);
  };

  return (
    <div className="map-panel mapgl-panel">
      <div ref={containerRef} className="mapgl-map" aria-label="Карта заявок 2ГИС" />
      {!mapReady && !mapError ? <div className="map-provider-state"><span className="map-loading-orbit"><i /></span><strong>Загружаем карту 2ГИС</strong><small>Подготавливаем районы и маршруты</small></div> : null}
      {mapError ? <div className="map-provider-state error"><strong>Карта недоступна</strong><span>{mapError}</span></div> : null}

      <div className="mapgl-controls" aria-label="Масштаб карты">
        <button onClick={() => mapRef.current?.setZoom((mapRef.current?.getZoom() ?? 11) + 1, { duration: 250 })} aria-label="Приблизить"><Plus size={18} /></button>
        <button onClick={() => mapRef.current?.setZoom((mapRef.current?.getZoom() ?? 11) - 1, { duration: 250 })} aria-label="Отдалить"><Minus size={18} /></button>
        <button onClick={fitAll} aria-label="Показать все"><LocateFixed size={17} /></button>
        <button onClick={resetNorth} aria-label="Компас: повернуть на север" title="Повернуть на север"><Compass size={18} style={{ transform: `rotate(${-rotation}deg)` }} /></button>
        <button className={pitch > .5 || Math.abs(rotation) > .5 ? "is-active" : ""} onClick={reset2D} aria-label="Вернуться в 2D" title="Вернуться в 2D"><MapIcon size={17} /><span>2D</span></button>
      </div>

      <div className="map-provider-badge"><span>2ГИС</span> MapGL</div>
      <div className="map-key">
        <span><i className="map-dot urgent" /> Авария</span>
        <span><i className="map-dot active" /> В работе</span>
        <span><i className="map-dot done" /> Выполнено</span>
      </div>
      {selectedEngineer ? (
        <div className="map-route-caption">
          <i className="route-live-signal" style={{ "--route-color": selectedEngineer.color } as React.CSSProperties} />
          <div><strong>{selectedEngineer.name}</strong><span>{selectedEngineer.request_ids.length} заявки в маршруте</span></div>
          {props.routeLoading ? <span className="mini-spinner" /> : <em>точный маршрут</em>}
        </div>
      ) : null}
    </div>
  );
}
