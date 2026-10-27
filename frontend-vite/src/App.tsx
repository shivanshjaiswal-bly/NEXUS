
import { useEffect, useRef, useState, type ReactNode } from "react";
import HomePage from "./HomePage";
import Discovery from "./Discovery";
import "./home.css";

declare global { interface Window { L: any } }
type Coord = { lat: number; lon: number };
type RouteLocation = Coord & { label: string; source: "place" | "map" | "manual" | "current" };
type PlaceResult = Coord & { display_name: string };
type LocationField = "start" | "destination";
type Report = { latitude: number; longitude: number; condition: string; incident: string; time: string };
type Traffic = { segment_id: string | null; status: string; incident: string; report_count: number; confidence: string; latitude: number; longitude: number; road_name?: string; geometry?: [number, number][] };
type Route = { found: boolean; status: string; error?: string; coordinates: [number, number][]; segment_ids: string[]; road_names: string[]; total_distance_km: number; estimated_travel_time_s: number; snapped_start?: { node: [number, number]; distance_km: number }; snapped_destination?: { node: [number, number]; distance_km: number }; provider?: string; traffic_aware?: boolean; source?: "local" | "external" };
const statusColor: Record<string, string> = { Normal: "#22c55e", Moderate: "#f59e0b", Heavy: "#f05231", Blocked: "#991b1b" };
const TRAFFIC_POLL_MS = 10000;
const MIN_MAP_ZOOM = 11;
const INITIAL_MAP_MAX_ZOOM = 13;
const NEXUS_ROAD_BOUNDS: [[number, number], [number, number]] = [[26.421184, 80.310997], [26.487423, 80.369086]];

function Icon({ children }: { children: ReactNode }) { return <span aria-hidden="true" className="icon">{children}</span>; }
function Button({ children, onClick, variant = "primary", disabled = false }: { children: ReactNode; onClick: () => void; variant?: string; disabled?: boolean }) {
  return <button type="button" disabled={disabled} className={`button button--${variant}`} onClick={onClick}>{children}</button>;
}

type DiscoveryPlace = { id: string; name: string; latitude?: number; longitude?: number };
function TrafficApp({ onHome, routeTarget }: { onHome: () => void; routeTarget: DiscoveryPlace | null }) {
  const mapRef = useRef<any>(null), mapNode = useRef<HTMLDivElement>(null), routeLayer = useRef<any>(null), trafficLayer = useRef<any>(null), reportLayer = useRef<any>(null), markerLayer = useRef<any>(null);
  const [dark, setDark] = useState(true), [emergency, setEmergency] = useState(false);
  const [start, setStart] = useState<RouteLocation | null>(null), [destination, setDestination] = useState<RouteLocation | null>(null);
  const [selectMode, setSelectMode] = useState<"start" | "destination" | "report" | null>(null);
  const [route, setRoute] = useState<Route | null>(null), [routeError, setRouteError] = useState("");
  const [traffic, setTraffic] = useState<Traffic[]>([]), [reports, setReports] = useState<Report[]>([]);
  const [trafficVisible, setTrafficVisible] = useState(true), [reportsVisible, setReportsVisible] = useState(true);
  const [locating, setLocating] = useState(false), [panel, setPanel] = useState<"planner" | "route" | "report" | "community" | "benchmarks" | null>(null);
  const [reportCoord, setReportCoord] = useState<Coord | null>(null), [condition, setCondition] = useState("Heavy"), [incident, setIncident] = useState("None");
  const [reportState, setReportState] = useState(""), [reportError, setReportError] = useState("");
  const [loadingTraffic, setLoadingTraffic] = useState(false), [routeLoading, setRouteLoading] = useState(false);
  const [apiConnected, setApiConnected] = useState<boolean | null>(null);
  const [mapZoom, setMapZoom] = useState(INITIAL_MAP_MAX_ZOOM);
  const [manualMode, setManualMode] = useState(false);
  const fetchRouteWithFallback = async (startCoord: Coord, destCoord: Coord) => {

  
    setRouteLoading(true);
    setRouteError("");
    try {
      const response = await fetch("/api/route", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start, destination }),
      });
      const data = await response.json();
      
      // Handle error messages from API response
      if (!response.ok) {
        // Check for error in data first, then data.message, then default
        setRouteError(data.error || data.message || `Route calculation failed`);
        setRoute({ found: false, status: "ROUTE_ERROR", error: data.error || data.message || `Route calculation failed`, coordinates: [], segment_ids: [], road_names: [], total_distance_km: 0, estimated_travel_time_s: 0, snapped_start: undefined, snapped_destination: undefined, provider: "local", traffic_aware: false, source: "local" });
      } else if (data.found) {
        setRoute(data);
        setRouteError("");
      } else {
        // Route not found - display error from API response
        setRouteError(data.error || data.message || `Route calculation failed`);
        setRoute({
          found: false,
          status: data.status || "NO_PATH_FOUND",
          error: data.error || data.message || `Route calculation failed`,
          coordinates: data.coordinates || [],
          segment_ids: data.segment_ids || [],
          road_names: data.road_names || [],
          total_distance_km: data.total_distance_km || 0,
          estimated_travel_time_s: data.estimated_travel_time_s || 0,
          snapped_start: data.snapped_start,
          snapped_destination: data.snapped_destination,
          provider: data.provider || "local",
          traffic_aware: data.traffic_aware || false,
          source: "local",
        });
      }
    } catch (error) {
      setRouteError("An unexpected error occurred during route calculation.");
      setRoute({ found: false, status: "INTERNAL_ROUTING_ERROR", error: "An unexpected error occurred during route calculation.", coordinates: [], segment_ids: [], road_names: [], total_distance_km: 0, estimated_travel_time_s: 0, snapped_start: undefined, snapped_destination: undefined, provider: "local", traffic_aware: false, source: "local" });
    } finally {
      setRouteLoading(false);
    }

    setRouteLoading(true);
    setRouteError("");

    // Step 1: Try local router first
    let localResponse = null;
    try {
      localResponse = await fetch("/api/route", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: { lat: startCoord.lat, lon: startCoord.lon }, destination: { lat: destCoord.lat, lon: destCoord.lon } }),
      });
    } catch (error) {
      setRouteLoading(false);
      setRouteError("Failed to connect to routing service.");
      return;
    }

    let localData = null;
    let localStatus = null;
    if (localResponse.ok) {
      localData = await localResponse.json();
    } else if (localResponse.status === 404) {
      try {
        localData = await localResponse.json();
        localStatus = localData?.status;
      } catch {
        localData = null;
      }
      // Only fall back for START_NOT_FOUND / DESTINATION_NOT_FOUND.
      // Do NOT fall back for NO_PATH_FOUND, SAME_SNAPPED_NODE, or other 404s.
      if (localStatus !== "START_NOT_FOUND" && localStatus !== "DESTINATION_NOT_FOUND") {
        setRouteError(localData?.error || "No route found.");
        setRouteLoading(false);
        return;
      }
      // Fall back to external OSRM provider
      try {
        const externalResponse = await fetch("/api/route-external", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ start: { lat: startCoord.lat, lon: startCoord.lon }, destination: { lat: destCoord.lat, lon: destCoord.lon } }),
        });
        if (externalResponse.ok) {
          localData = await externalResponse.json();
          // Mark as external route - NEXUS traffic intelligence is not applied
          localData.source = "external";
          localData.provider = "OSRM";
          localData.traffic_aware = false;
        } else {
          localData = { found: false, status: "EXTERNAL_ROUTING_FAILED", error: "External routing service unavailable." };
        }
      } catch (error) {
        localData = { found: false, status: "EXTERNAL_ROUTING_ERROR", error: "External routing service request failed." };
      }
    }
    if (localData && localData.found) {
      localData.source = localData.source || "local";
      localData.traffic_aware = localData.traffic_aware !== undefined ? localData.traffic_aware : true;
      setRoute(localData as Route);
    } else if (localData) {
      setRouteError(localData.error || "No route found.");
    }
    setRouteLoading(false);
  };

  const [startQuery, setStartQuery] = useState(""), [destinationQuery, setDestinationQuery] = useState("");
  const [startResults, setStartResults] = useState<PlaceResult[]>([]), [destinationResults, setDestinationResults] = useState<PlaceResult[]>([]);
  

  const [searchingField, setSearchingField] = useState<LocationField | null>(null), [placeSearchError, setPlaceSearchError] = useState("");
  const [startCoordinates, setStartCoordinates] = useState({ lat: "", lon: "" }), [destinationCoordinates, setDestinationCoordinates] = useState({ lat: "", lon: "" });
  const [coordinateErrors, setCoordinateErrors] = useState<{ start?: string; destination?: string }>({});
  const [resumePlannerAfterPick, setResumePlannerAfterPick] = useState(false);
  useEffect(() => { if (!routeTarget || routeTarget.latitude == null || routeTarget.longitude == null) return;
    setDestination({ lat: routeTarget.latitude, lon: routeTarget.longitude, label: routeTarget.name, source: "place" });
    setDestinationQuery(routeTarget.name); setDestinationCoordinates({ lat: String(routeTarget.latitude), lon: String(routeTarget.longitude) });
    setRoute(null); setRouteError(""); setPanel("planner"); mapRef.current?.setView([routeTarget.latitude, routeTarget.longitude], 15);
  }, [routeTarget]);
  const resumePlannerAfterPickRef = useRef(false);
  const searchRequestIds = useRef<Record<LocationField, number>>({ start: 0, destination: 0 });
  const routeRequestInFlight = useRef(false);
  const selectModeRef = useRef<typeof selectMode>(null);
  selectModeRef.current = selectMode;

  async function refreshTraffic() {
    setLoadingTraffic(true);
    try {
      const [trafficResponse, reportsResponse] = await Promise.all([fetch("/api/traffic"), fetch("/api/reports")]);
      if (!trafficResponse.ok || !reportsResponse.ok) throw new Error("Traffic data is currently unavailable.");
      setTraffic(await trafficResponse.json()); setReports(await reportsResponse.json()); setApiConnected(true);
    } catch (error) { setApiConnected(false); setRouteError(error instanceof Error ? error.message : "Could not load traffic data."); }
    finally { setLoadingTraffic(false); }
  }

  useEffect(() => {
    let timer: number | null = null;
    const stop = () => { if (timer !== null) { window.clearInterval(timer); timer = null; } };
    const start = () => { if (timer === null && !document.hidden) timer = window.setInterval(() => { void refreshTraffic(); }, TRAFFIC_POLL_MS); };
    const onVisibilityChange = () => {
      if (document.hidden) stop();
      else { void refreshTraffic(); start(); }
    };
    start();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => { stop(); document.removeEventListener("visibilitychange", onVisibilityChange); };
  }, []);

  useEffect(() => {
    refreshTraffic();
    if (!mapNode.current || !window.L) return;
    const L = window.L;
    const map = L.map(mapNode.current, { zoomControl: false, minZoom: MIN_MAP_ZOOM, maxZoom: 19, zoomSnap: 1, zoomDelta: 1 }).setView([26.455, 80.335], INITIAL_MAP_MAX_ZOOM);
    mapRef.current = map;
    const syncZoom = () => setMapZoom(map.getZoom());
    map.on("zoomend", syncZoom);
    const resizeObserver = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resizeObserver.observe(mapNode.current);
    const initialFrame = window.requestAnimationFrame(() => {
      map.invalidateSize({ pan: false });
      map.fitBounds(NEXUS_ROAD_BOUNDS, { padding: [24, 24], maxZoom: INITIAL_MAP_MAX_ZOOM, animate: false });
      syncZoom();
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
    routeLayer.current = L.layerGroup().addTo(map); trafficLayer.current = L.layerGroup().addTo(map); reportLayer.current = L.layerGroup().addTo(map); markerLayer.current = L.layerGroup().addTo(map);
    const handleMapClick = (event: any) => {
      const mode = selectModeRef.current;
      if (!mode) return;
      const point = { lat: event.latlng.lat, lon: event.latlng.lng };
      if (import.meta.env.DEV) console.debug("[NEXUS route selection] map click", { endpoint: mode, coordinates: point });
      if (mode === "start") {
        setStart({ ...point, label: "Map selection", source: "map" }); setStartQuery(""); setStartResults([]);
        setStartCoordinates({ lat: String(point.lat), lon: String(point.lon) });
        setRoute(null); setRouteError(""); setCoordinateErrors({});
        setPanel(resumePlannerAfterPickRef.current ? "planner" : null);
        resumePlannerAfterPickRef.current = false; setResumePlannerAfterPick(false);
      } else if (mode === "destination") {
        setDestination({ ...point, label: "Map selection", source: "map" }); setDestinationQuery(""); setDestinationResults([]);
        setDestinationCoordinates({ lat: String(point.lat), lon: String(point.lon) });
        setRoute(null); setRouteError(""); setCoordinateErrors({});
        setPanel(resumePlannerAfterPickRef.current ? "planner" : null);
        resumePlannerAfterPickRef.current = false; setResumePlannerAfterPick(false);
      } else {
        setReportCoord(point); setPanel("report"); setReportState("");
      }
      setSelectMode(null);
    };
    map.on("click", handleMapClick);
    return () => { window.cancelAnimationFrame(initialFrame); resizeObserver.disconnect(); map.off("zoomend", syncZoom); map.off("click", handleMapClick); map.remove(); mapRef.current = null; };
  }, []);

  useEffect(() => {
    const L = window.L, map = mapRef.current;
    if (!L || !map || !trafficLayer.current || !reportLayer.current || !markerLayer.current) return;
    trafficLayer.current.clearLayers(); reportLayer.current.clearLayers(); markerLayer.current.clearLayers();
    if (trafficVisible) for (const segment of traffic) {
      const color = statusColor[segment.status] || "#94a3b8";
      if (segment.geometry?.length) L.polyline(segment.geometry, { color, weight: segment.status === "Blocked" ? 8 : 6, opacity: .9, dashArray: segment.status === "Blocked" ? "7 5" : undefined }).addTo(trafficLayer.current).bindPopup(`${segment.road_name || "Unmatched road"} · ${segment.status} · ${segment.report_count} report(s)`);
    }
    if (reportsVisible) for (const report of reports) L.circleMarker([report.latitude, report.longitude], { radius: 7, color: statusColor[report.condition] || "#f05231", fillColor: statusColor[report.condition] || "#f05231", fillOpacity: .85, weight: 2 }).addTo(reportLayer.current).bindPopup(`${report.condition}${report.incident !== "None" ? ` · ${report.incident}` : ""} · ${new Date(report.time).toLocaleString()}`);
    for (const [point, color, label] of [[start, "#22c55e", "Start"], [destination, "#ef4444", "Destination"]] as [RouteLocation | null, string, string][]) if (point) L.circleMarker([point.lat, point.lon], { radius: 8, color, fillColor: color, fillOpacity: 1, weight: 2 }).addTo(markerLayer.current).bindPopup(`${label}: ${point.label} (${point.lat.toFixed(6)}, ${point.lon.toFixed(6)})`);
    if (reportCoord) L.circleMarker([reportCoord.lat, reportCoord.lon], { radius: 10, color: "#fff", fillColor: "#a855f7", fillOpacity: 1, weight: 3 }).addTo(markerLayer.current).bindPopup(`Report location: ${reportCoord.lat.toFixed(6)}, ${reportCoord.lon.toFixed(6)}`);
    routeLayer.current.clearLayers();
    if (route?.found && route.coordinates?.length) {
      L.polyline(route.coordinates, { color: "#f8fafc", weight: 10, opacity: .8 }).addTo(routeLayer.current); L.polyline(route.coordinates, { color: emergency ? "#f05231" : "#168cff", weight: 6, opacity: .95 }).addTo(routeLayer.current);
      map.fitBounds(L.latLngBounds(route.coordinates), { padding: [50, window.innerWidth > 900 ? 360 : 50], maxZoom: 16 });
    }
  }, [traffic, reports, trafficVisible, reportsVisible, start, destination, reportCoord, route, emergency]);

  function useCurrentLocation() {
    setRouteError(""); setRoute(null);
    if (!navigator.geolocation) { setRouteError("This browser does not support location lookup. You can search for a place or choose the start on the map."); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(position => {
      const point = { lat: position.coords.latitude, lon: position.coords.longitude };
      setStart({ ...point, label: "Current location", source: "current" });
      setStartCoordinates({ lat: String(point.lat), lon: String(point.lon) });
      setCoordinateErrors({}); setRoute(null); mapRef.current?.setView([point.lat, point.lon], 15); setLocating(false);
    }, error => {
      const secureContextHint = window.isSecureContext ? "" : " Browser location usually requires localhost or HTTPS.";
      const message = error.code === error.PERMISSION_DENIED ? `Location permission denied. Allow access or choose the start on the map.${secureContextHint}` : error.code === error.POSITION_UNAVAILABLE ? `Your location is unavailable. Try again or choose the start on the map.${secureContextHint}` : error.code === error.TIMEOUT ? `Location request timed out. Try again or choose the start on the map.${secureContextHint}` : `Could not get your location. Try again or choose the start on the map.${secureContextHint}`;
      setRouteError(message); setLocating(false);
    }, { enableHighAccuracy: true, timeout: 9000, maximumAge: 30000 });
  }

  function changeSearchQuery(field: LocationField, value: string) {
    searchRequestIds.current[field] += 1;
    setPlaceSearchError(""); setSearchingField(current => current === field ? null : current); setRoute(null);
    if (field === "start") { setStartQuery(value); setStartResults([]); setStart(null); }
    else { setDestinationQuery(value); setDestinationResults([]); setDestination(null); }
  }

  async function searchPlaces(field: LocationField) {
    const query = (field === "start" ? startQuery : destinationQuery).trim();
    if (query.length < 2) { setPlaceSearchError("Enter at least two characters to search for a place."); return; }
    const requestId = ++searchRequestIds.current[field];
    setSearchingField(field); setPlaceSearchError("");
    if (field === "start") setStartResults([]); else setDestinationResults([]);
    try {
      const response = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`);
      const responseText = await response.text();
      let data: { error?: string; results?: PlaceResult[] };
      try {
        data = JSON.parse(responseText);
      } catch {
        throw new Error("Place search returned an unreadable response. Check that Flask and its geocoding connection are available.");
      }
      if (requestId !== searchRequestIds.current[field]) return;
      if (!response.ok) throw new Error(data.error || `Place search failed (HTTP ${response.status}).`);
      const results = Array.isArray(data.results) ? data.results as PlaceResult[] : [];
      if (field === "start") setStartResults(results); else setDestinationResults(results);
      if (!results.length) setPlaceSearchError("No matching places found. Try a more specific name or choose a point on the map.");
    } catch (error) {
      if (requestId === searchRequestIds.current[field]) setPlaceSearchError(error instanceof Error ? error.message : "Place search is unavailable. Choose the location on the map instead.");
    } finally {
      if (requestId === searchRequestIds.current[field]) setSearchingField(null);
    }
  }

  function selectPlace(field: LocationField, place: PlaceResult) {
    const selected: RouteLocation = { lat: place.lat, lon: place.lon, label: place.display_name, source: "place" };
    if (field === "start") {
      setStart(selected); setStartQuery(place.display_name); setStartResults([]);
      setStartCoordinates({ lat: String(place.lat), lon: String(place.lon) });
    } else {
      setDestination(selected); setDestinationQuery(place.display_name); setDestinationResults([]);
      setDestinationCoordinates({ lat: String(place.lat), lon: String(place.lon) });
    }
    setCoordinateErrors({}); setRouteError(""); setRoute(null);
  }

  function clearLocation(field: LocationField) {
    if (field === "start") { setStart(null); setStartQuery(""); setStartResults([]); setStartCoordinates({ lat: "", lon: "" }); }
    else { setDestination(null); setDestinationQuery(""); setDestinationResults([]); setDestinationCoordinates({ lat: "", lon: "" }); }
    setCoordinateErrors({}); setRouteError(""); setRoute(null);
  }

  function beginMapSelection(field: "start" | "destination" | "report") {
    resumePlannerAfterPickRef.current = field !== "report" && (panel === "planner" || resumePlannerAfterPick);
    setResumePlannerAfterPick(resumePlannerAfterPickRef.current);
    if (field !== "report") setPanel(null);
    setSelectMode(field);
  }

  function cancelMapSelection() {
    setSelectMode(null);
    if (resumePlannerAfterPickRef.current) setPanel("planner");
    resumePlannerAfterPickRef.current = false; setResumePlannerAfterPick(false);
  }

  async function calculateRoute() {
    if (routeRequestInFlight.current) return;
    setRouteError(""); setRoute(null);
    let routeStart = start;
    let routeDestination = destination;
    if (manualMode) {
      const parseManualPoint = (values: { lat: string; lon: string }, field: LocationField) => {
        const lat = values.lat.trim() === "" ? Number.NaN : Number(values.lat);
        const lon = values.lon.trim() === "" ? Number.NaN : Number(values.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return { error: `Enter numeric latitude and longitude for the ${field}.` };
        if (lat < -90 || lat > 90) return { error: `${field === "start" ? "Start" : "Destination"} latitude must be between -90 and 90.` };
        if (lon < -180 || lon > 180) return { error: `${field === "start" ? "Start" : "Destination"} longitude must be between -180 and 180.` };
        return { point: { lat, lon, label: "Manual coordinates", source: "manual" as const } };
      };
      const parsedStart = parseManualPoint(startCoordinates, "start");
      const parsedDestination = parseManualPoint(destinationCoordinates, "destination");
      const errors = { start: parsedStart.error, destination: parsedDestination.error };
      setCoordinateErrors(errors);
      if (errors.start || errors.destination || !parsedStart.point || !parsedDestination.point) {
        setRouteError("Fix the highlighted coordinates before calculating the route.");
        return;
      }
      routeStart = parsedStart.point; routeDestination = parsedDestination.point;
      setStart(routeStart); setDestination(routeDestination);
    }
    if (!routeStart || !routeDestination) { setRouteError("Search for or choose both a start and destination before calculating the route."); return; }
    routeRequestInFlight.current = true;
    const requestCoordinates = {
      start: { lat: routeStart.lat, lon: routeStart.lon },
      destination: { lat: routeDestination.lat, lon: routeDestination.lon },
    };
    try {
      const response = await fetch("/api/route", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestCoordinates),
      });
      const responseText = await response.text();
      let data: Route & { error?: string; message?: string; status?: string };
      try {
        data = JSON.parse(responseText) as Route & { error?: string; message?: string; status?: string };
      } catch {
        throw new Error("Route response was not valid JSON.");
      }

      if (!response.ok) {
        const message = data.error || data.message || `Route calculation failed (HTTP ${response.status}).`;
        setRouteError(message);
        setRoute({
          found: false,
          status: data?.status || "ROUTE_ERROR",
          error: message,
          coordinates: data?.coordinates || [],
          segment_ids: data?.segment_ids || [],
          road_names: data?.road_names || [],
          total_distance_km: data?.total_distance_km || 0,
          estimated_travel_time_s: data?.estimated_travel_time_s || 0,
          snapped_start: data?.snapped_start,
          snapped_destination: data?.snapped_destination,
          provider: data?.provider || "local",
          traffic_aware: data?.traffic_aware ?? false,
          source: data?.source || "local",
        });
        return;
      }

      if (data?.found) {
        setRoute(data as Route); setPanel("route"); setRouteError("");
        return;
      }

      const localStatus = data?.status;
      if (localStatus === "START_NOT_FOUND" || localStatus === "DESTINATION_NOT_FOUND") {
        try {
          const externalResponse = await fetch("/api/route-external", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestCoordinates),
          });
          if (externalResponse.ok) {
            const externalData = await externalResponse.json() as Route & { error?: string; message?: string; status?: string };
            externalData.source = "external";
            externalData.provider = "OSRM";
            externalData.traffic_aware = false;
            setRoute(externalData as Route);
            setRouteError("");
            setPanel("route");
            return;
          }
          const externalMessage = `External routing service unavailable (HTTP ${externalResponse.status}).`;
          setRouteError(externalMessage);
          setRoute({
            found: false,
            status: "EXTERNAL_ROUTING_FAILED",
            error: externalMessage,
            coordinates: [],
            segment_ids: [],
            road_names: [],
            total_distance_km: 0,
            estimated_travel_time_s: 0,
            snapped_start: undefined,
            snapped_destination: undefined,
            provider: "osrm",
            traffic_aware: false,
            source: "external",
          });
        } catch (error) {
          const externalMessage = "External routing service request failed.";
          setRouteError(externalMessage);
          setRoute({
            found: false,
            status: "EXTERNAL_ROUTING_ERROR",
            error: externalMessage,
            coordinates: [],
            segment_ids: [],
            road_names: [],
            total_distance_km: 0,
            estimated_travel_time_s: 0,
            snapped_start: undefined,
            snapped_destination: undefined,
            provider: "osrm",
            traffic_aware: false,
            source: "external",
          });
        }
      } else {
        const message = data?.error || "No route found.";
        setRouteError(message);
        setRoute({
          found: false,
          status: data?.status || "NO_PATH_FOUND",
          error: message,
          coordinates: data?.coordinates || [],
          segment_ids: data?.segment_ids || [],
          road_names: data?.road_names || [],
          total_distance_km: data?.total_distance_km || 0,
          estimated_travel_time_s: data?.estimated_travel_time_s || 0,
          snapped_start: data?.snapped_start,
          snapped_destination: data?.snapped_destination,
          provider: data?.provider || "local",
          traffic_aware: data?.traffic_aware ?? false,
          source: data?.source || "local",
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "An unexpected error occurred during route calculation.";
      setRouteError(message);
      setRoute({
        found: false,
        status: "INTERNAL_ROUTING_ERROR",
        error: message,
        coordinates: [],
        segment_ids: [],
        road_names: [],
        total_distance_km: 0,
        estimated_travel_time_s: 0,
        snapped_start: undefined,
        snapped_destination: undefined,
        provider: "local",
        traffic_aware: false,
        source: "local",
      });
    } finally {
      routeRequestInFlight.current = false;
    }
  }

  async function submitReport() {
    setReportError(""); setReportState("");
    if (!reportCoord) { setReportError("Select a report location on the map first."); return; }
    try {
      const response = await fetch("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ latitude: reportCoord.lat, longitude: reportCoord.lon, condition, incident }) });
      const data = await response.json();
      if (!response.ok || data.success !== true) { setReportError(data.error || data.message || `Report submission failed (HTTP ${response.status}).`); return; }
      setReportState("Report received by the server. Reports are held in memory and expire after 30 minutes."); await refreshTraffic();
    } catch (error) { setReportError(error instanceof Error ? error.message : "Could not submit the report."); }
  }

  const closePanel = () => { setPanel(null); setSelectMode(null); };
  useEffect(() => {
    if (!panel) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [panel]);
  const etaMinutes = route ? route.estimated_travel_time_s / 60 : null;
  const latest = [...traffic].sort((a, b) => b.report_count - a.report_count).slice(0, 3);

  function renderLocationField(field: LocationField) {
    const isStart = field === "start";
    const selected = isStart ? start : destination;
    const query = isStart ? startQuery : destinationQuery;
    const results = isStart ? startResults : destinationResults;
    return <div className="field-group location-field">
      <label className="field-label" htmlFor={`${field}-place-search`}>{isStart ? "START LOCATION" : "DESTINATION"}</label>
      <div className="location-search-row">
        <input id={`${field}-place-search`} type="search" autoComplete="off" value={query} placeholder={isStart ? "Search a place or address" : "Search destination"} onChange={event => changeSearchQuery(field, event.target.value)} onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); void searchPlaces(field); } }} />
        <button type="button" className="button button--secondary" onClick={() => void searchPlaces(field)} disabled={searchingField === field}>{searchingField === field ? "Searching..." : "Search"}</button>
      </div>
      {selected ? <div className="selected-place"><span className={`selected-place__pin selected-place__pin--${field}`} aria-hidden="true">{isStart ? "S" : "D"}</span><div><strong title={selected.label}>{selected.label}</strong><small>{selected.lat.toFixed(6)}, {selected.lon.toFixed(6)}</small></div><button type="button" className="text-button" onClick={() => clearLocation(field)}>Clear</button></div> : <p className="location-placeholder">{isStart ? "No start selected" : "No destination selected"}</p>}
      {results.length > 0 && <div className="place-results" role="listbox" aria-label={`${isStart ? "Start" : "Destination"} search results`}>{results.map((place: PlaceResult, index: number) => <button type="button" role="option" aria-selected="false" key={`${place.lat}-${place.lon}-${index}`} onClick={() => selectPlace(field, place)}><strong>{place.display_name}</strong><small>{place.lat.toFixed(5)}, {place.lon.toFixed(5)}</small></button>)}</div>}
      <div className="action-row location-actions"><button type="button" className="button button--secondary" aria-pressed={selectMode === field} onClick={() => beginMapSelection(field)}>Choose {isStart ? "start" : "destination"} on map</button>{isStart && <button type="button" className="button button--secondary" onClick={useCurrentLocation} disabled={locating}>{locating ? "Locating..." : "Use my location"}</button>}</div>
    </div>;
  }

  return <main className={`app ${dark ? "theme-dark" : ""} ${emergency ? "is-emergency" : ""} ${selectMode ? "is-selecting-map" : ""}`}>
    {emergency && <div className="emergency-bar"><strong>EMERGENCY ROUTING</strong><span>Live traffic multipliers and blocked-road exclusions are applied by the routing service.</span></div>}
    <div ref={mapNode} className="map-canvas" aria-label="Interactive OpenStreetMap road map" />
    <header className="topbar"><div className="brand"><span className="brand__mark">N</span><div><strong>NEXUS</strong><span>TrustGuard · traffic intelligence</span></div></div><div className="topbar__right"><button className="top-action" onClick={onHome}>NEXUS Home</button><span className="network-status"><i/>{loadingTraffic ? "UPDATING" : apiConnected === false ? "API UNAVAILABLE" : apiConnected ? "API CONNECTED" : "CONNECTING"}<strong>{reports.length} reports</strong></span><button className={`top-action ${panel === "benchmarks" ? "active" : ""}`} onClick={() => setPanel(panel === "benchmarks" ? null : "benchmarks")}>Research benchmarks</button><button className="icon-button" onClick={() => setDark(!dark)} aria-label="Toggle theme">{dark ? "☼" : "☾"}</button></div></header>
    {panel === "planner" && <aside className="sidebar panel drawer" aria-label="Route planning" role="dialog" aria-modal="true"><div className="drawer__head"><div className="panel__eyebrow">PLAN A ROUTE</div><button className="icon-button" onClick={closePanel} aria-label="Close route planner">X</button></div>
      <p className="place-search-attribution">Search a place or address and choose a result. Search queries are sent to <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>.</p>
      {renderLocationField("start")}
      {renderLocationField("destination")}
      <button type="button" className="text-button manual-mode-toggle" aria-expanded={manualMode} onClick={() => { setManualMode(value => !value); setCoordinateErrors({}); setRouteError(""); if (!manualMode) { setStartCoordinates({ lat: start ? String(start.lat) : "", lon: start ? String(start.lon) : "" }); setDestinationCoordinates({ lat: destination ? String(destination.lat) : "", lon: destination ? String(destination.lon) : "" }); } }}>{manualMode ? "Hide manual coordinates" : "Use manual coordinates (debug)"}</button>
      {placeSearchError && <p className="inline-error" role="alert">{placeSearchError}</p>}
      {manualMode && <section className="manual-coordinates" aria-label="Manual coordinate entry"><p className="small-note">Enter decimal degrees. Values are checked only when you calculate the route.</p>
        <div className="manual-coordinate-field"><strong>Start coordinates</strong><div><label>Latitude<input aria-label="Start latitude" inputMode="decimal" type="text" value={startCoordinates.lat} aria-invalid={Boolean(coordinateErrors.start)} onChange={event => { setStartCoordinates(value => ({ ...value, lat: event.target.value })); setStart(null); setRoute(null); setCoordinateErrors(value => ({ ...value, start: undefined })); }} /></label><label>Longitude<input aria-label="Start longitude" inputMode="decimal" type="text" value={startCoordinates.lon} aria-invalid={Boolean(coordinateErrors.start)} onChange={event => { setStartCoordinates(value => ({ ...value, lon: event.target.value })); setStart(null); setRoute(null); setCoordinateErrors(value => ({ ...value, start: undefined })); }} /></label></div>{coordinateErrors.start && <small className="coordinate-error" role="alert">{coordinateErrors.start}</small>}</div>
        <div className="manual-coordinate-field"><strong>Destination coordinates</strong><div><label>Latitude<input aria-label="Destination latitude" inputMode="decimal" type="text" value={destinationCoordinates.lat} aria-invalid={Boolean(coordinateErrors.destination)} onChange={event => { setDestinationCoordinates(value => ({ ...value, lat: event.target.value })); setDestination(null); setRoute(null); setCoordinateErrors(value => ({ ...value, destination: undefined })); }} /></label><label>Longitude<input aria-label="Destination longitude" inputMode="decimal" type="text" value={destinationCoordinates.lon} aria-invalid={Boolean(coordinateErrors.destination)} onChange={event => { setDestinationCoordinates(value => ({ ...value, lon: event.target.value })); setDestination(null); setRoute(null); setCoordinateErrors(value => ({ ...value, destination: undefined })); }} /></label></div>{coordinateErrors.destination && <small className="coordinate-error" role="alert">{coordinateErrors.destination}</small>}</div>
      </section>}
      <p className="small-note location-coverage-note">Routes use supported mapped roads; points more than 0.5 km from the road network are rejected. Browser location usually requires localhost or HTTPS.</p>
      <div className="field-group"><div className="field-label">ROUTING ALGORITHM</div><div className="segmented"><button className="active" disabled>Dijkstra</button><button disabled title="Not implemented by the current routing API">A*</button><button disabled title="Not implemented by the current routing API">Bidirectional</button></div><small className="small-note">The current backend supports Dijkstra routing only.</small></div>
      <div className={`emergency-toggle ${emergency ? "emergency-toggle--active" : ""}`}><span className="emergency-toggle__icon">!</span><span className="emergency-toggle__copy"><strong>Emergency mode</strong><small>Traffic-aware routing is always applied</small></span><button className={`toggle ${emergency ? "toggle--active" : ""}`} role="switch" aria-checked={emergency} onClick={() => setEmergency(!emergency)}><span className="toggle__thumb"/></button></div>
      <Button onClick={calculateRoute} disabled={routeLoading}>{routeLoading ? "Calculating..." : emergency ? "Find safest route" : "Calculate route"}</Button>
      {routeError && <div className="route-feedback"><p className="inline-error" role="alert">{routeError}</p><div className="action-row"><button type="button" className="button button--secondary" onClick={() => beginMapSelection("start")}>Choose start on map</button><button type="button" className="button button--secondary" onClick={() => beginMapSelection("destination")}>Choose destination on map</button></div></div>}
      <div className="panel-divider"><span>COMMUNITY INTELLIGENCE</span></div><Button variant="secondary" onClick={() => { setPanel("report"); setReportError(""); setReportState(""); }}>Report traffic</Button><div className="live-indicator"><span/> {reports.length} active reports - held in memory</div>
    </aside>}
    <nav className="floating-actions" aria-label="Map actions"><button onClick={() => setPanel("planner")} aria-label="Plan route" title="Plan route"><span aria-hidden="true">R</span><b>Plan Route</b></button><button onClick={() => { setPanel("report"); setReportError(""); setReportState(""); }} aria-label="Report traffic" title="Report traffic"><span aria-hidden="true">+</span><b>Report Traffic</b></button><button onClick={() => setPanel("community")} aria-label="Community reports" title="Community reports"><span aria-hidden="true">C</span><b>Community</b></button><button onClick={useCurrentLocation} disabled={locating} aria-label="My location" title="My location"><span aria-hidden="true">L</span><b>My Location</b></button></nav>
    <div className="map-tools"><button className="icon-button" aria-label="Zoom in" onClick={() => mapRef.current?.zoomIn()}>＋</button><button className="icon-button zoom-out" aria-label="Zoom out" aria-disabled={mapZoom <= MIN_MAP_ZOOM} disabled={mapZoom <= MIN_MAP_ZOOM} onClick={() => { if (mapRef.current && mapRef.current.getZoom() > MIN_MAP_ZOOM) mapRef.current.zoomOut(); }}>-</button><button className="icon-button" aria-label="Locate me" onClick={useCurrentLocation}>◎</button><button className={`icon-button ${trafficVisible ? "active" : ""}`} aria-label="Toggle traffic overlay" aria-pressed={trafficVisible} onClick={() => setTrafficVisible(!trafficVisible)}>▤</button></div>
    <div className="right-panels">
      {panel === "route" && route && <section className="route-summary panel drawer" role="dialog" aria-modal="true"><div className="drawer__head"><div><span className="summary-kicker">ROUTE FOUND</span><h2>Traffic-aware route</h2></div><button className="icon-button" onClick={closePanel} aria-label="Close route summary">X</button></div><div className="route-primary"><div><strong>{route.total_distance_km.toFixed(2)}</strong><span>km</span><small>Actual route distance</small></div><i/><div><strong>{etaMinutes!.toFixed(1)}</strong><span>min</span><small>Traffic-adjusted ETA</small></div></div><div className="route-location-summary"><div><small>START</small><strong>{start?.label || "Start location"}</strong><span>{start?.lat.toFixed(5)}, {start?.lon.toFixed(5)}</span></div><div><small>DESTINATION</small><strong>{destination?.label || "Destination"}</strong><span>{destination?.lat.toFixed(5)}, {destination?.lon.toFixed(5)}</span></div></div><div className="route-meta"><span>{route.segment_ids.length} road segments</span><span>{route.road_names.join(" -> ") || "Road names unavailable"}</span></div><div className="summary-meta"><span>Status<strong>{route.status}</strong></span><span>Snapped endpoints<strong>{route.snapped_start?.node.join(", ")} {" -> "} {route.snapped_destination?.node.join(", ")}</strong></span></div></section>}
      {panel === "community" && <section className="report-detail panel drawer" role="dialog" aria-modal="true"><div className="drawer__head"><div className="panel__eyebrow">LIVE COMMUNITY REPORTS</div><button className="icon-button" onClick={closePanel} aria-label="Close traffic reports">×</button></div><div className="overlay-switch"><span>Road condition overlays</span><button className={`toggle ${trafficVisible ? "toggle--active" : ""}`} role="switch" aria-checked={trafficVisible} onClick={() => setTrafficVisible(!trafficVisible)}><span className="toggle__thumb"/></button></div><div className="overlay-switch"><span>Individual reports</span><button className={`toggle ${reportsVisible ? "toggle--active" : ""}`} role="switch" aria-checked={reportsVisible} onClick={() => setReportsVisible(!reportsVisible)}><span className="toggle__thumb"/></button></div>{latest.length ? latest.map((item, index) => <div className="traffic-card" key={`${item.segment_id}-${index}`}><span className="traffic-dot" style={{ background: statusColor[item.status] || "#94a3b8" }}/><div><strong>{item.road_name || "Unmatched road report"}</strong><small>{item.status} · {item.report_count} report(s) · {item.confidence} confidence</small></div></div>) : <p className="empty-copy">No active traffic reports from the API.</p>}<button className="text-button" onClick={refreshTraffic} disabled={loadingTraffic}>{loadingTraffic ? "Refreshing..." : "Refresh data"}</button></section>}
    </div>
    <div className="legend panel"><span>TRAFFIC FLOW</span>{Object.entries(statusColor).map(([label, color]) => <div key={label}><i className="legend-line" style={{ background: color }}/>{label}</div>)}</div><div className="map-source">OpenStreetMap · Local NEXUS road matching</div>
    {selectMode && <div className="selection-hint">{selectMode === "report" ? "Click the map to choose the report location." : `Click the map to choose your ${selectMode} location.`}<button onClick={cancelMapSelection}>Cancel</button></div>}
    {panel === "report" && selectMode !== "report" && <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && closePanel()}><section className="modal" role="dialog" aria-modal="true"><div className="modal__head"><div><span className="panel__eyebrow">COMMUNITY REPORT</span><h2>Report a road condition</h2><p>Submission uses the existing NEXUS reports API.</p></div><button className="icon-button" onClick={closePanel} aria-label="Close report">×</button></div><div className="report-location"><span>⌖</span><div><small>REPORTING AT</small><strong>{reportCoord ? `${reportCoord.lat.toFixed(6)}, ${reportCoord.lon.toFixed(6)}` : "No location selected"}</strong></div><button onClick={() => beginMapSelection("report")}>Choose location on map</button></div><label className="field-label">ROAD CONDITION</label><div className="report-grid">{["Normal", "Moderate", "Heavy", "Blocked"].map(value => <button key={value} className={`report-option report-option--${value.toLowerCase()} ${condition === value ? "selected" : ""}`} onClick={() => setCondition(value)}>{value}</button>)}</div><label className="field-label">INCIDENT TYPE</label><select value={incident} onChange={event => setIncident(event.target.value)}>{["None", "Accident", "Road Work", "Road Block", "Other"].map(value => <option key={value}>{value}</option>)}</select><p className="small-note">The API does not accept notes. Reports are stored in server memory and expire after 30 minutes.</p>{reportError && <p className="inline-error" role="alert">{reportError}</p>}{reportState && <p className="success-message" role="status">{reportState}</p>}<Button onClick={submitReport} disabled={!reportCoord}>Submit report</Button></section></div>}
    {panel === "benchmarks" && <div className="modal-backdrop" onMouseDown={event => event.target === event.currentTarget && closePanel()}><section className="modal benchmark-modal" role="dialog" aria-modal="true"><div className="modal__head"><div><span className="panel__eyebrow">RESEARCH BENCHMARK</span><h2>Algorithm performance</h2></div><button className="icon-button" onClick={closePanel} aria-label="Close benchmarks">×</button></div><p>Measured comparative benchmarks are not available from the current backend. The API currently runs Dijkstra; the Figma sample timings and route comparisons are omitted.</p><div className="benchmark-empty">No measured benchmark data</div><p className="small-note">A route response can provide the actual route distance and traffic-adjusted ETA. It does not expose runtime or memory measurements.</p></section></div>}
  </main>;
}

export default function App() {
  const [view, setView] = useState<"home" | "traffic" | "discovery">("home");
  const [search, setSearch] = useState({ query: "", category: "", city: "" });
  const [routeTarget, setRouteTarget] = useState<DiscoveryPlace | null>(null);
  if (view === "traffic") return <TrafficApp onHome={() => setView("home")} routeTarget={routeTarget} />;
  if (view === "discovery") return <Discovery initialQuery={search.query} initialCategory={search.category} initialCity={search.city} onBack={() => setView("home")} onRoute={place => { setRouteTarget(place); setView("traffic"); }} />;
  return <HomePage onOpenTraffic={() => setView("traffic")} onOpenDiscovery={(query = "", category = "", city = "") => { setSearch({ query, category, city }); setView("discovery"); }} />;
}



