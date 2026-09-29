import { load } from "@2gis/mapgl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Compass, LocateFixed, Map as MapIcon, Minus, Plus } from "lucide-react";
import { buildRoadRoute, RoutingHttpError, type LngLat, type RoutePiece } from "../api/dgisRouting";
import type { DetailedRoute, Engineer, OverviewRoutesResponse, RequestItem } from "../api/types";
import { formatTime, statusLabels, transportLabels } from "./ui";

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
type PointCluster = { key: string; center: LngLat; requests: RequestItem[] };
type RouteStopGroup = { key: string; coordinates: LngLat; sequences: number[]; requests: RequestItem[] };

const MAP_KEY = import.meta.env.VITE_2GIS_KEY?.trim() ?? "";
const ROUTE_COLOR = "#165dff";
const OUTLINE_COLOR = "#15202d";
const FALLBACK_COLOR = "#e5484d";
// Markers closer than this on screen are merged into a counter bubble.
const CLUSTER_RADIUS_PX = 34;
// From this zoom every address is shown separately; only exact duplicates group.
const NO_CLUSTER_ZOOM = 15;
const OVERVIEW_MAX_ZOOM = 14;
// A group click zooms at least this close; a same-address group at this zoom
// cannot be split any further.
const CLUSTER_ZOOM = 17;
const ROUTE_MAX_ZOOM = 16;
// Start fetching the MapGL runtime as soon as this module is evaluated instead
// of waiting for the map component effect. The loader caches this promise.
const mapApiPromise = MAP_KEY ? load() : null;

const samePoint = (left: LngLat, right: LngLat) => left[0] === right[0] && left[1] === right[1];
const pointKey = ([lng, lat]: LngLat) => `${lng.toFixed(6)}:${lat.toFixed(6)}`;

function boundsOf(points: LngLat[]) {
  if (!points.length) return null;
  const longitudes = points.map((point) => point[0]);
  const latitudes = points.map((point) => point[1]);
  // A single point (or several at one address) still needs a visible area.
  const pad = Math.max(...longitudes) - Math.min(...longitudes) < 0.004 && Math.max(...latitudes) - Math.min(...latitudes) < 0.004 ? 0.006 : 0;
  return {
    southWest: [Math.min(...longitudes) - pad, Math.min(...latitudes) - pad],
    northEast: [Math.max(...longitudes) + pad, Math.max(...latitudes) + pad],
  };
}

function createClusters(requests: RequestItem[], map: MapInstance | null, zoom: number): PointCluster[] {
  const clusters: Array<PointCluster & { pixel: number[] }> = [];
  requests.forEach((request) => {
    const pixel = map?.project(request.coordinates) ?? [0, 0];
    // At high zoom still group requests with identical coordinates so none is
    // hidden under another marker. Repeated clicks cycle through that group.
    const target = zoom >= NO_CLUSTER_ZOOM || !map
      ? clusters.find((cluster) => samePoint(cluster.requests[0].coordinates, request.coordinates))
      : clusters.find((cluster) => Math.hypot(cluster.pixel[0] - pixel[0], cluster.pixel[1] - pixel[1]) < CLUSTER_RADIUS_PX);
    if (target) target.requests.push(request);
    else clusters.push({ key: pointKey(request.coordinates), center: request.coordinates, requests: [request], pixel });
  });
  return clusters.map(({ key, requests: clusterRequests }) => ({
    key,
    // A lone request stays exactly on its address; a group sits at its centroid.
    center: clusterRequests.length === 1
      ? clusterRequests[0].coordinates
      : [
        clusterRequests.reduce((sum, item) => sum + item.coordinates[0], 0) / clusterRequests.length,
        clusterRequests.reduce((sum, item) => sum + item.coordinates[1], 0) / clusterRequests.length,
      ],
    requests: clusterRequests,
  }));
}

function requestTypeClass(request: RequestItem) {
  return request.bk_type === "Авария" ? "emergency" : request.bk_type === "Подключение" ? "connection" : request.bk_type === "Дозаказ" ? "additional" : "local";
}

function svgIcon(paths: string[], size = 16) {
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("width", String(size));
  icon.setAttribute("height", String(size));
  icon.setAttribute("fill", "none");
  icon.setAttribute("stroke", "currentColor");
  icon.setAttribute("stroke-width", "2.3");
  icon.setAttribute("stroke-linecap", "round");
  icon.setAttribute("stroke-linejoin", "round");
  icon.setAttribute("aria-hidden", "true");
  paths.forEach((shape) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", shape);
    icon.appendChild(path);
  });
  return icon;
}

const typeIconPaths: Record<string, string[]> = {
  emergency: ["M12 3 2 21h20L12 3Z", "M12 9v5", "M12 18h.01"],
  connection: ["M13 2 4 13h7l-1 9 10-12h-7V2Z"],
  additional: ["M3 7 12 3l9 4v10l-9 4-9-4V7Z", "m3 7 9 4 9-4", "M12 11v10"],
  local: ["M14.7 6.3a5 5 0 0 0-6.4 6.4L3 18l3 3 5.3-5.3a5 5 0 0 0 6.4-6.4L15 12l-3-3 2.7-2.7Z"],
};
const flagIconPaths = ["M4 22V4", "M4 4h13l-2.5 4.5L17 13H4"];
const homeIconPaths = ["M3 10.5 12 3l9 7.5", "M5 9v11h14V9", "M10 20v-6h4v6"];

function tooltip(titleText: string, descriptionText: string, metaText: string) {
  const element = document.createElement("span");
  element.className = "mapgl-request-tooltip";
  const title = document.createElement("strong");
  title.textContent = titleText;
  const description = document.createElement("span");
  description.textContent = descriptionText;
  const meta = document.createElement("b");
  meta.textContent = metaText;
  element.append(title, description, meta);
  return element;
}

function requestTooltip(request: RequestItem, prefix = "") {
  return tooltip(
    `${prefix}${request.external_id}`,
    `${request.bk_type} · ${request.address || request.district}`,
    `${formatTime(request.window_start)}–${formatTime(request.window_end)} · ${statusLabels[request.status]}`,
  );
}

function cycleOnClick(element: HTMLElement, requests: RequestItem[], selectedRequestId: string | null, onSelectRequest: (requestId: string) => void) {
  element.addEventListener("click", (event) => {
    event.stopPropagation();
    const currentIndex = requests.findIndex((item) => item.id === selectedRequestId);
    onSelectRequest(requests[(currentIndex + 1) % requests.length].id);
  });
}

// A group click zooms in instead of opening a request (no request card call).
// Only a group at one address that is already zoomed in cycles its requests:
// zooming further can never split it.
function createMarkerContent(
  cluster: PointCluster,
  selectedRequestId: string | null,
  muted: boolean,
  canSplitByZoom: boolean,
  onSelectRequest: (requestId: string) => void,
  onZoomToCluster: (cluster: PointCluster) => void,
) {
  const request = cluster.requests[0];
  const selected = cluster.requests.some((item) => item.id === selectedRequestId);
  const urgent = cluster.requests.some((item) => item.priority_rank === 1);
  const typeClass = requestTypeClass(request);
  const marker = document.createElement("button");
  marker.type = "button";
  marker.className = [
    "mapgl-request-marker",
    selected ? "is-selected" : "",
    urgent ? "is-urgent" : "",
    `type-${typeClass}`,
    request.status === "COMPLETED" ? "is-completed" : "",
    cluster.requests.length > 1 ? "is-cluster" : "",
    muted && !selected ? "is-muted" : "",
  ].filter(Boolean).join(" ");
  const isGroup = cluster.requests.length > 1;
  marker.setAttribute("aria-label", isGroup
    ? `${cluster.requests.length} заявок${canSplitByZoom ? ": приблизить" : " по одному адресу"}`
    : `Открыть заявку ${request.external_id}: ${request.bk_type}`);
  if (isGroup) marker.textContent = String(cluster.requests.length);
  else marker.appendChild(svgIcon(typeIconPaths[typeClass]));
  marker.appendChild(!isGroup
    ? requestTooltip(request)
    : canSplitByZoom
      ? tooltip(`${cluster.requests.length} заявок рядом`, "Нажмите, чтобы приблизить", "")
      : tooltip(`${cluster.requests.length} заявок по одному адресу`, request.address || request.district, "Нажимайте, чтобы переключать заявки"));
  if (isGroup && canSplitByZoom) {
    marker.addEventListener("click", (event) => {
      event.stopPropagation();
      onZoomToCluster(cluster);
    });
  } else cycleOnClick(marker, cluster.requests, selectedRequestId, onSelectRequest);
  return marker;
}

function createStopContent(group: RouteStopGroup, selectedRequestId: string | null, onSelectRequest: (requestId: string) => void) {
  const request = group.requests[0];
  const marker = document.createElement("button");
  marker.type = "button";
  marker.className = [
    "mapgl-stop-marker",
    group.requests.some((item) => item.id === selectedRequestId) ? "is-selected" : "",
    group.requests.some((item) => item.priority_rank === 1) ? "is-urgent" : "",
    group.requests.every((item) => item.status === "COMPLETED") ? "is-completed" : "",
  ].filter(Boolean).join(" ");
  marker.textContent = group.sequences.join(",");
  marker.setAttribute("aria-label", `Точка ${group.sequences.join(", ")} маршрута: ${request.external_id}`);
  marker.appendChild(group.requests.length > 1
    ? tooltip(`Точки ${group.sequences.join(", ")} · один адрес`, request.address || request.district, group.requests.map((item) => item.external_id).join(", "))
    : requestTooltip(request, `${group.sequences[0]}. `));
  cycleOnClick(marker, group.requests, selectedRequestId, onSelectRequest);
  return marker;
}

function createOfficeContent(active: boolean, engineersCount: number) {
  const marker = document.createElement("div");
  marker.className = `mapgl-office-marker${active ? " is-active" : ""}`;
  marker.setAttribute("role", "img");
  marker.setAttribute("aria-label", "Офис округа — стартовая точка маршрутов");
  marker.appendChild(svgIcon(flagIconPaths, 17));
  marker.appendChild(tooltip(
    "Офис округа",
    active ? "Отсюда инженер начинает день" : `Старт ${engineersCount} ${engineersCount === 1 ? "бригады" : "бригад"}`,
    "",
  ));
  return marker;
}

// Brigades serving remote towns (Kashira, Stupino, ...) start from a "home"
// point in that town instead of the office; shown only for the selected one.
function createHomeContent() {
  const marker = document.createElement("div");
  marker.className = "mapgl-office-marker is-home";
  marker.setAttribute("role", "img");
  marker.setAttribute("aria-label", "Дом бригады — стартовая точка маршрута");
  marker.appendChild(svgIcon(homeIconPaths, 17));
  marker.appendChild(tooltip("Дом бригады", "Удалённая бригада начинает день отсюда, а не из офиса", ""));
  return marker;
}

function drawPiece(api: MapGlApi, map: MapInstance, piece: RoutePiece): Destructible[] {
  const { coordinates } = piece;
  const common = { coordinates, interactive: false };
  switch (piece.kind) {
    case "road":
      return [
        new api.Polyline(map, { ...common, width: 11, color: OUTLINE_COLOR, zIndex: 5 }),
        new api.Polyline(map, { ...common, width: 7, color: "#ffffff", zIndex: 6 }),
        new api.Polyline(map, { ...common, width: 5, color: ROUTE_COLOR, zIndex: 7 }),
      ];
    case "transit":
      return [
        new api.Polyline(map, { ...common, width: 11, color: OUTLINE_COLOR, zIndex: 5 }),
        new api.Polyline(map, { ...common, width: 7, color: piece.color ?? ROUTE_COLOR, zIndex: 7 }),
      ];
    case "walk":
      return [
        new api.Polyline(map, { ...common, width: 7, color: "#ffffff", zIndex: 5 }),
        new api.Polyline(map, { ...common, width: 4, color: ROUTE_COLOR, dashLength: 6, gapLength: 5, gapColor: "#ffffff", zIndex: 6 }),
      ];
    case "connector":
      return [new api.Polyline(map, { ...common, width: 3, color: OUTLINE_COLOR, dashLength: 4, gapLength: 4, zIndex: 8 })];
    case "fallback":
      return [
        new api.Polyline(map, { ...common, width: 7, color: "#ffffff", zIndex: 5 }),
        new api.Polyline(map, { ...common, width: 4, color: FALLBACK_COLOR, dashLength: 10, gapLength: 7, gapColor: "#ffffff", zIndex: 6 }),
      ];
  }
}

function pluralLegs(count: number) {
  return count === 1 ? "участок" : count >= 2 && count <= 4 ? "участка" : "участков";
}

export function MapPanel(props: MapPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapInstance | null>(null);
  const [mapApi, setMapApi] = useState<MapGlApi | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(11);
  const [rotation, setRotation] = useState(0);
  const [pitch, setPitch] = useState(0);
  const [roadLoading, setRoadLoading] = useState(false);
  const [roadError, setRoadError] = useState<string | null>(null);
  const [roadReady, setRoadReady] = useState(false);
  const [failedLegs, setFailedLegs] = useState(0);

  const selectedEngineer = props.engineers.find((item) => item.id === props.selectedEngineerId) ?? null;
  const selectedRoute = props.routes.routes.find((route) => route.engineer_id === props.selectedEngineerId);
  const mappedRequests = useMemo(() => props.requests.filter((item) => item.mapping_state === "mapped"), [props.requests]);

  // One office per district. The plan API gives only each engineer's start;
  // office brigades all share the office point, while remote brigades start
  // from their own "home" points, so the office is the most shared start.
  const office = useMemo(() => {
    const grouped = new Map<string, { coordinates: LngLat; engineerIds: string[] }>();
    props.routes.routes.forEach((route) => {
      if (!route.start_coordinates) return;
      const key = pointKey(route.start_coordinates);
      const start = grouped.get(key) ?? { coordinates: route.start_coordinates, engineerIds: [] };
      start.engineerIds.push(route.engineer_id);
      grouped.set(key, start);
    });
    return [...grouped.values()].sort((left, right) => right.engineerIds.length - left.engineerIds.length)[0] ?? null;
  }, [props.routes]);

  // Ordered stops of the selected engineer; `request_ids` follow the plan sequence.
  const routeStops = useMemo(() => {
    if (!selectedEngineer) return [];
    const byId = new Map(mappedRequests.map((request) => [request.id, request]));
    return selectedEngineer.request_ids
      .map((id) => byId.get(id))
      .filter((request): request is RequestItem => Boolean(request));
  }, [mappedRequests, selectedEngineer]);
  const startPoint = selectedRoute?.start_coordinates ?? null;
  const startsAtOffice = Boolean(startPoint && office && samePoint(startPoint, office.coordinates));

  const routePoints = useMemo(() => {
    const points = [...(startPoint ? [startPoint] : []), ...routeStops.map((request) => request.coordinates)];
    return points.filter((point, index) => index === 0 || !samePoint(point, points[index - 1]));
  }, [startPoint, routeStops]);
  const routePointsKey = routePoints.map(pointKey).join(";");

  const overviewPoints = useMemo(
    () => [...mappedRequests.map((request) => request.coordinates), ...(office ? [office.coordinates] : [])],
    [mappedRequests, office],
  );
  // Refit only when the set of points changes, not on every status update.
  const overviewKey = useMemo(() => overviewPoints.map(pointKey).sort().join(";"), [overviewPoints]);

  const fitTo = useCallback((points: LngLat[], maxZoom: number, duration = 650) => {
    const map = mapRef.current;
    const bounds = boundsOf(points);
    if (!map || !bounds) return;
    map.fitBounds(bounds, {
      // Leave room for the route caption on top and the legend at the bottom.
      padding: { top: props.selectedEngineerId ? 84 : 60, right: 70, bottom: 64, left: 50 },
      maxZoom,
      animation: { duration, easing: "easeOutCubic" },
    });
  }, [props.selectedEngineerId]);

  const zoomToCluster = useCallback((cluster: PointCluster) => {
    const map = mapRef.current;
    if (!map) return;
    const points = cluster.requests.map((item) => item.coordinates);
    const sameAddress = points.every((point) => samePoint(point, points[0]));
    if (sameAddress) {
      map.setCenter(points[0], { duration: 450 });
      map.setZoom(CLUSTER_ZOOM, { duration: 450 });
    } else {
      // Frame just this group; the markers then split apart on screen.
      fitTo(points, CLUSTER_ZOOM + 1, 450);
    }
  }, [fitTo]);

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
        center: [37.62, 55.75],
        zoom: 10,
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

  // Camera: the whole district on open / district switch / deselection, the
  // engineer's office and stops when an engineer is selected. Waiting for the
  // first `idle` guarantees the container has its real size before fitting.
  const focusRequest = props.selectedEngineerId ? null : mappedRequests.find((item) => item.id === props.selectedRequestId) ?? null;
  const flyToRequest = useCallback((request: RequestItem) => {
    const map = mapRef.current;
    if (!map) return;
    map.setCenter(request.coordinates, { duration: 600 });
    if (map.getZoom() < 15) map.setZoom(15, { duration: 600 });
  }, []);

  useEffect(() => {
    if (!mapReady) return;
    if (props.selectedEngineerId && routePoints.length) fitTo(routePoints, ROUTE_MAX_ZOOM);
    // A request opened from another page wins over the district overview.
    else if (!props.selectedEngineerId && focusRequest) flyToRequest(focusRequest);
    else if (!props.selectedEngineerId) fitTo(overviewPoints, OVERVIEW_MAX_ZOOM);
    // The point lists are tracked through their keys; request focus has its own effect.
  }, [mapReady, overviewKey, routePointsKey, props.selectedEngineerId, fitTo]);

  // Selecting a request (list, card link, timeline) brings it into view.
  // Deselecting leaves the camera where the dispatcher put it.
  useEffect(() => {
    if (mapReady && focusRequest) flyToRequest(focusRequest);
  }, [mapReady, focusRequest?.id, flyToRequest]);

  // With an engineer selected, his stops are drawn as numbered markers and the
  // remaining requests stay visible but muted.
  const backgroundRequests = useMemo(() => {
    if (!selectedEngineer) return mappedRequests;
    const onRoute = new Set(routeStops.map((request) => request.id));
    return mappedRequests.filter((request) => !onRoute.has(request.id));
  }, [mappedRequests, routeStops, selectedEngineer]);
  // `zoom` is a dependency on purpose: clusters are computed in screen pixels.
  const clusters = useMemo(
    () => createClusters(backgroundRequests, mapApi ? mapRef.current : null, zoom),
    [backgroundRequests, mapApi, zoom],
  );
  const stopGroups = useMemo(() => {
    const grouped = new Map<string, RouteStopGroup>();
    routeStops.forEach((request, index) => {
      const key = pointKey(request.coordinates);
      const group = grouped.get(key) ?? { key, coordinates: request.coordinates, sequences: [], requests: [] };
      group.sequences.push(index + 1);
      group.requests.push(request);
      grouped.set(key, group);
    });
    return [...grouped.values()];
  }, [routeStops]);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapApi || !map) return;
    const objects: Destructible[] = [];
    const muted = Boolean(selectedEngineer);
    const addMarker = (coordinates: LngLat, content: HTMLElement, size: number, baseZIndex: number) => {
      const marker = new mapApi.HtmlMarker(map, { coordinates, html: content, anchor: [size / 2, size / 2], interactive: true, zIndex: baseZIndex });
      const bringToFront = () => marker.setZIndex(1000);
      const restoreLayer = () => marker.setZIndex(baseZIndex);
      content.addEventListener("mouseenter", bringToFront);
      content.addEventListener("mouseleave", restoreLayer);
      content.addEventListener("focusin", bringToFront);
      content.addEventListener("focusout", restoreLayer);
      objects.push(marker);
    };

    clusters.forEach((cluster) => {
      const selected = cluster.requests.some((item) => item.id === props.selectedRequestId);
      const size = muted && !selected ? 20 : cluster.requests.length > 1 || selected ? 34 : 30;
      const sameAddress = cluster.requests.every((item) => samePoint(item.coordinates, cluster.requests[0].coordinates));
      const canSplitByZoom = !sameAddress || zoom < CLUSTER_ZOOM - 0.5;
      addMarker(
        cluster.center,
        createMarkerContent(cluster, props.selectedRequestId, muted, canSplitByZoom, props.onSelectRequest, zoomToCluster),
        size,
        selected ? 30 : muted ? 10 : 20,
      );
    });
    stopGroups.forEach((group) => {
      const selected = group.requests.some((item) => item.id === props.selectedRequestId);
      addMarker(group.coordinates, createStopContent(group, props.selectedRequestId, props.onSelectRequest), group.sequences.length > 1 ? 34 : 30, selected ? 45 : 40);
    });
    // The pin's tip (34×42 badge, tip at the bottom centre) marks the point.
    const addPin = (coordinates: LngLat, content: HTMLElement) =>
      objects.push(new mapApi.HtmlMarker(map, { coordinates, html: content, anchor: [17, 42], interactive: true, zIndex: 50 }));
    // The office stays visible as a landmark; it is highlighted when it is the
    // selected engineer's start.
    if (office) addPin(office.coordinates, createOfficeContent(startsAtOffice, office.engineerIds.length));
    if (startPoint && !startsAtOffice) addPin(startPoint, createHomeContent());

    return () => objects.forEach((object) => object.destroy());
  }, [clusters, mapApi, office, props.onSelectRequest, props.selectedRequestId, selectedEngineer, startPoint, startsAtOffice, stopGroups, zoom, zoomToCluster]);

  // Road geometry for the selected engineer: office → stops in plan order,
  // by the engineer's own transport (car, walking, bicycle or public transport).
  const transport = selectedEngineer?.transport ?? null;
  useEffect(() => {
    const map = mapRef.current;
    setFailedLegs(0);
    if (!mapApi || !map || !props.selectedEngineerId || !transport) {
      setRoadLoading(false); setRoadReady(false); setRoadError(null);
      return;
    }
    if (routePoints.length < 2) {
      setRoadLoading(false); setRoadReady(false);
      setRoadError(routeStops.length ? "Нет координат офиса для построения маршрута." : "У инженера нет заявок на карте.");
      return;
    }
    let disposed = false;
    const lines: Destructible[] = [];
    setRoadLoading(true); setRoadReady(false); setRoadError(null);
    buildRoadRoute(routePoints, transport).then((route) => {
      if (disposed) return;
      route.pieces.forEach((piece) => lines.push(...drawPiece(mapApi, map, piece)));
      setFailedLegs(route.failedLegs);
      setRoadReady(route.failedLegs < routePoints.length - 1);
      setRoadError(route.failedLegs >= routePoints.length - 1 ? "2ГИС не нашёл маршрут — показаны прямые отрезки." : null);
      setRoadLoading(false);
      // Roads may bend outside the stops' bounding box: include them in view.
      fitTo([...routePoints, ...route.pieces.flatMap((piece) => piece.coordinates)], ROUTE_MAX_ZOOM, 450);
    }).catch((error: unknown) => {
      if (disposed) return;
      // Without road geometry still show the visiting order as straight dashes.
      routePoints.slice(1).forEach((to, index) =>
        lines.push(...drawPiece(mapApi, map, { kind: "fallback", coordinates: [routePoints[index], to] })));
      setRoadError(error instanceof RoutingHttpError && error.status === 429
        ? "Лимит запросов 2ГИС исчерпан — точки соединены по прямой."
        : error instanceof RoutingHttpError && (error.status === 401 || error.status === 403)
          ? `2ГИС отклонил ключ маршрутизации (HTTP ${error.status}). Нужен доступ к Routing API.`
          : error instanceof RoutingHttpError
            ? `2ГИС не построил маршрут (HTTP ${error.status}).`
            : "2ГИС не ответил. Проверьте подключение к интернету.");
      setRoadLoading(false);
    });
    return () => { disposed = true; lines.forEach((line) => line.destroy()); };
    // routePoints is tracked through routePointsKey.
  }, [mapApi, props.selectedEngineerId, transport, routePointsKey]);

  const fitCurrent = () => {
    if (props.selectedEngineerId && routePoints.length) fitTo(routePoints, ROUTE_MAX_ZOOM, 500);
    else fitTo(overviewPoints, OVERVIEW_MAX_ZOOM, 500);
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

  const stopsCount = routeStops.length;
  const routeStatus = roadReady
    ? failedLegs
      ? `${failedLegs} ${pluralLegs(failedLegs)} без маршрута 2ГИС — пунктир`
      : `${transport ? transportLabels[transport].toLowerCase() : ""} · по данным 2ГИС`
    : roadError ?? "Маршрут не построен";

  return (
    <div className="map-panel mapgl-panel">
      <div ref={containerRef} className="mapgl-map" aria-label="Карта заявок 2ГИС" />
      {!mapReady && !mapError ? <div className="map-provider-state"><span className="map-loading-orbit"><i /></span><strong>Загружаем карту 2ГИС</strong><small>Подготавливаем районы и маршруты</small></div> : null}
      {mapError ? <div className="map-provider-state error"><strong>Карта недоступна</strong><span>{mapError}</span></div> : null}

      <div className="mapgl-controls" aria-label="Масштаб карты">
        <button onClick={() => mapRef.current?.setZoom((mapRef.current?.getZoom() ?? 11) + 1, { duration: 250 })} aria-label="Приблизить"><Plus size={18} /></button>
        <button onClick={() => mapRef.current?.setZoom((mapRef.current?.getZoom() ?? 11) - 1, { duration: 250 })} aria-label="Отдалить"><Minus size={18} /></button>
        <button onClick={fitCurrent} aria-label={props.selectedEngineerId ? "Показать маршрут целиком" : "Показать все заявки"} title={props.selectedEngineerId ? "Показать маршрут целиком" : "Показать все заявки"}><LocateFixed size={17} /></button>
        <button onClick={resetNorth} aria-label="Компас: повернуть на север" title="Повернуть на север"><Compass size={18} style={{ transform: `rotate(${-rotation}deg)` }} /></button>
        <button className={pitch > .5 || Math.abs(rotation) > .5 ? "is-active" : ""} onClick={reset2D} aria-label="Вернуться в 2D" title="Вернуться в 2D"><MapIcon size={17} /><span>2D</span></button>
      </div>

      <div className="map-provider-badge"><span>2ГИС</span> MapGL</div>
      <div className="map-key">
        <span><i className="map-dot office" /> Офис округа</span>
        <span><i className="map-dot urgent" /> Авария</span>
        <span><i className="map-dot connection" /> Подключение</span>
        <span><i className="map-dot additional" /> Дозаказ</span>
        <span><i className="map-dot local" /> Локальная</span>
      </div>
      {selectedEngineer ? (
        <div className="map-route-caption">
          <i className="route-live-signal" style={{ "--route-color": ROUTE_COLOR } as React.CSSProperties} />
          <div><strong>{selectedEngineer.name}</strong><span>{stopsCount} {stopsCount === 1 ? "точка" : stopsCount >= 2 && stopsCount <= 4 ? "точки" : "точек"} · {startsAtOffice ? "старт из офиса" : "старт из дома бригады"}</span></div>
          {props.routeLoading || roadLoading ? <span className="mini-spinner" /> : <em className={roadReady && !failedLegs ? "" : "route-error"}>{routeStatus}</em>}
        </div>
      ) : null}
    </div>
  );
}
