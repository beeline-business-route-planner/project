import type { Transport } from "./types";

// Road geometry for the map is built on request of the browser: the plan API
// stores only stop coordinates. Calls go through our own `/dgis-routing` proxy
// (nginx in Docker, Vite in dev), which adds the routing key server-side, so
// the key never reaches the bundle or the browser's network log.
const ROUTING_PROXY = "/dgis-routing";
const ROUTING_URL = `${ROUTING_PROXY}/routing/7.0.0/global`;
const TRANSIT_URL = `${ROUTING_PROXY}/public_transport/2.0`;
// The key allows at most 10 intermediate points; keep chunks well inside it.
const MAX_POINTS_PER_REQUEST = 10;
const TRANSIT_TYPES = ["bus", "trolleybus", "tram", "metro", "shuttle_bus", "suburban_train", "mcd", "mcc", "light_metro"];
// Gaps shorter than this between a stop and the road line are not worth a connector.
const CONNECTOR_MIN_METERS = 8;

export type LngLat = [number, number];

export type RoutePieceKind =
  | "road" // main road geometry for car / walking / bicycle
  | "walk" // pedestrian part of a transit trip
  | "transit" // ride on a bus, metro, tram, ...
  | "connector" // short dashed link between a stop and the nearest road
  | "fallback"; // 2GIS found no route: straight dashed chord

export interface RoutePiece {
  kind: RoutePieceKind;
  coordinates: LngLat[];
  color?: string;
}

export interface RoadRoute {
  pieces: RoutePiece[];
  failedLegs: number;
}

// The key has a request quota. Every built route is kept in memory and in
// localStorage, so reselecting an engineer or reloading the page costs nothing.
const cache = new Map<string, Promise<RoadRoute>>();
const STORAGE_PREFIX = "dgis-route:v1:";
const STORAGE_INDEX = "dgis-route:v1:index";
const STORAGE_MAX_ROUTES = 60;

function readStored(cacheKey: string): RoadRoute | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + cacheKey);
    return raw ? JSON.parse(raw) as RoadRoute : null;
  } catch {
    return null;
  }
}

function store(cacheKey: string, route: RoadRoute) {
  // Routes with missing legs are not stored: they are retried next time.
  if (route.failedLegs) return;
  try {
    const index = (JSON.parse(localStorage.getItem(STORAGE_INDEX) ?? "[]") as string[]).filter((item) => item !== cacheKey);
    index.push(cacheKey);
    while (index.length > STORAGE_MAX_ROUTES) localStorage.removeItem(STORAGE_PREFIX + index.shift());
    localStorage.setItem(STORAGE_PREFIX + cacheKey, JSON.stringify(route));
    localStorage.setItem(STORAGE_INDEX, JSON.stringify(index));
  } catch {
    // Storage is full or unavailable: the in-memory cache still works.
  }
}

export function buildRoadRoute(points: LngLat[], transport: Transport): Promise<RoadRoute> {
  const cacheKey = `${transport}|${points.map(([lng, lat]) => `${lng.toFixed(6)},${lat.toFixed(6)}`).join(";")}`;
  let route = cache.get(cacheKey);
  if (!route) {
    const stored = readStored(cacheKey);
    route = stored
      ? Promise.resolve(stored)
      : (transport === "transit" ? buildTransitRoute(points) : buildStreetRoute(points, transport));
    route.then((built) => { if (!stored) store(cacheKey, built); }, () => cache.delete(cacheKey));
    cache.set(cacheKey, route);
  }
  return route;
}

function distanceMeters([lng1, lat1]: LngLat, [lng2, lat2]: LngLat) {
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLng = (lng2 - lng1) * toRad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLng / 2) ** 2;
  return 6_371_000 * 2 * Math.asin(Math.sqrt(a));
}

function connector(from: LngLat, to: LngLat | undefined): RoutePiece[] {
  return to && distanceMeters(from, to) >= CONNECTOR_MIN_METERS ? [{ kind: "connector", coordinates: [from, to] }] : [];
}

function linesFromWkt(wkt: string | undefined | null): LngLat[][] {
  if (!wkt) return [];
  const geometry = wkt.replace(/^SRID=\d+;/i, "").trim();
  const type = geometry.match(/^(LINESTRING|MULTILINESTRING)(?:\s+Z)?\s*\(/i)?.[1]?.toUpperCase();
  if (!type) return [];
  const groups = type === "LINESTRING"
    ? [geometry.slice(geometry.indexOf("(") + 1, geometry.lastIndexOf(")"))]
    : [...geometry.matchAll(/\(([^()]+)\)/g)].map((match) => match[1]);
  return groups
    .map((group) => group.split(",").map((pair) => pair.trim().split(/\s+/).slice(0, 2).map(Number) as LngLat))
    .filter((line) => line.length >= 2 && line.every(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat)));
}

// At most two requests in flight: bursts of parallel legs hit the rate limit.
const MAX_IN_FLIGHT = 2;
let inFlight = 0;
const waiting: Array<() => void> = [];
// After HTTP 429 the key is left alone for a while instead of being hammered.
const RATE_LIMIT_PAUSE_MS = 60_000;
let rateLimitedUntil = 0;

async function postJson<T>(url: string, body: unknown): Promise<T> {
  if (Date.now() < rateLimitedUntil) throw new RoutingHttpError(429);
  if (inFlight >= MAX_IN_FLIGHT) await new Promise<void>((resolve) => waiting.push(resolve));
  inFlight += 1;
  try {
    if (Date.now() < rateLimitedUntil) throw new RoutingHttpError(429);
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (response.status === 429) rateLimitedUntil = Date.now() + RATE_LIMIT_PAUSE_MS;
    if (!response.ok) throw new RoutingHttpError(response.status);
    return await response.json() as T;
  } finally {
    inFlight -= 1;
    waiting.shift()?.();
  }
}

export function isKeyProblem(error: unknown): error is RoutingHttpError {
  return error instanceof RoutingHttpError && [401, 403, 429].includes(error.status);
}

// A rejected key or an exhausted quota breaks every request: stop at once
// instead of retrying leg by leg (which would only burn more quota).
function nullUnlessKeyProblem(error: unknown): null {
  if (isKeyProblem(error)) throw error;
  return null;
}

export class RoutingHttpError extends Error {
  constructor(readonly status: number) {
    super(`2GIS routing HTTP ${status}`);
  }
}

/* Car / walking / bicycle: Routing API 7 with intermediate points. */

interface StreetResponse {
  status?: string;
  result?: Array<{
    begin_pedestrian_path?: { geometry?: { selection?: string } };
    end_pedestrian_path?: { geometry?: { selection?: string } };
    maneuvers?: Array<{ outcoming_path?: { geometry?: Array<{ selection?: string }> } }>;
    waypoints?: Array<{ projected_point?: { lon: number; lat: number } }>;
  }>;
}

const streetTransport: Record<Exclude<Transport, "transit">, string> = {
  car: "driving",
  walking: "walking",
  bicycle: "bicycle",
};

async function requestStreetChunk(points: LngLat[], transport: Exclude<Transport, "transit">): Promise<RoutePiece[] | null> {
  const payload = {
    points: points.map(([lon, lat], index) => ({
      type: index === 0 || index === points.length - 1 ? "stop" : "pref",
      lon,
      lat,
    })),
    transport: streetTransport[transport],
    output: "detailed",
    locale: "ru",
  };
  const data = await postJson<StreetResponse>(ROUTING_URL, payload);
  const route = data.status === "OK" ? data.result?.[0] : undefined;
  if (!route) return null;
  const road = [
    ...linesFromWkt(route.begin_pedestrian_path?.geometry?.selection),
    ...(route.maneuvers ?? []).flatMap((maneuver) =>
      (maneuver.outcoming_path?.geometry ?? []).flatMap((part) => linesFromWkt(part.selection))),
    ...linesFromWkt(route.end_pedestrian_path?.geometry?.selection),
  ];
  if (!road.length) return null;
  // The route passes through each stop's projection onto the road; link the
  // real address to that projection so the line visibly reaches the marker.
  const connectors = points.flatMap((point, index) => {
    const projected = route.waypoints?.[index]?.projected_point;
    return connector(point, projected ? [projected.lon, projected.lat] : undefined);
  });
  return [...road.map((coordinates) => ({ kind: "road" as const, coordinates })), ...connectors];
}

async function buildStreetRoute(points: LngLat[], transport: Exclude<Transport, "transit">): Promise<RoadRoute> {
  const chunks: LngLat[][] = [];
  // Chunks overlap at the boundary point so the line stays continuous.
  for (let start = 0; start < points.length - 1; start += MAX_POINTS_PER_REQUEST - 1) {
    chunks.push(points.slice(start, start + MAX_POINTS_PER_REQUEST));
  }
  const results = await Promise.all(chunks.map(async (chunk) => {
    const pieces = await requestStreetChunk(chunk, transport).catch(nullUnlessKeyProblem);
    if (pieces) return { pieces, failedLegs: 0 };
    // One unreachable stop (e.g. a car-free zone) fails the whole chunk:
    // retry leg by leg so the rest of the route is still drawn by roads.
    const legs = await Promise.all(chunk.slice(1).map(async (to, index) => {
      const from = chunk[index];
      const leg = await requestStreetChunk([from, to], transport).catch(nullUnlessKeyProblem);
      return leg ?? [{ kind: "fallback" as const, coordinates: [from, to] }];
    }));
    return { pieces: legs.flat(), failedLegs: legs.filter((leg) => leg[0]?.kind === "fallback").length };
  }));
  return {
    pieces: results.flatMap((result) => result.pieces),
    failedLegs: results.reduce((sum, result) => sum + result.failedLegs, 0),
  };
}

/* Public transport: one request per leg, best variant from 2GIS. */

interface TransitVariant {
  movements?: Array<{
    type?: string;
    metro?: { color?: string };
    routes?: Array<{ color?: string }>;
    alternatives?: Array<{ geometry?: Array<{ selection?: string }> | null }>;
  }>;
}

async function requestTransitLeg(from: LngLat, to: LngLat): Promise<RoutePiece[] | null> {
  const data = await postJson<TransitVariant[] | Record<string, unknown>>(TRANSIT_URL, {
    locale: "ru",
    source: { point: { lon: from[0], lat: from[1] } },
    target: { point: { lon: to[0], lat: to[1] } },
    transport: TRANSIT_TYPES,
  });
  const variant = Array.isArray(data) ? data[0] : undefined;
  if (!variant?.movements?.length) return null;
  const pieces: RoutePiece[] = variant.movements.flatMap((movement) => {
    const ride = movement.type === "passage";
    const color = ride ? movement.metro?.color ?? movement.routes?.[0]?.color : undefined;
    return (movement.alternatives?.[0]?.geometry ?? []).flatMap((part) => linesFromWkt(part.selection))
      .map((coordinates) => ({ kind: ride ? "transit" as const : "walk" as const, coordinates, color }));
  });
  if (!pieces.length) return null;
  const first = pieces[0].coordinates[0];
  const lastLine = pieces[pieces.length - 1].coordinates;
  return [...connector(from, first), ...pieces, ...connector(to, lastLine[lastLine.length - 1])];
}

async function buildTransitRoute(points: LngLat[]): Promise<RoadRoute> {
  const legs = await Promise.all(points.slice(1).map(async (to, index) => {
    const from = points[index];
    const transit = await requestTransitLeg(from, to).catch(nullUnlessKeyProblem);
    if (transit) return transit;
    // No transit variant (too close, night, etc.): the engineer walks.
    const walk = await requestStreetChunk([from, to], "walking").catch(nullUnlessKeyProblem);
    return walk?.map((piece) => (piece.kind === "road" ? { ...piece, kind: "walk" as const } : piece))
      ?? [{ kind: "fallback" as const, coordinates: [from, to] }];
  }));
  return {
    pieces: legs.flat(),
    failedLegs: legs.filter((leg) => leg.length === 1 && leg[0].kind === "fallback").length,
  };
}
