import { useEffect, useState, type FormEvent, type ReactNode } from "react";

type LocalReport = { latitude: number; longitude: number; condition: string; incident: string; time: string };
type IconName = "hotel" | "hostel" | "home" | "shop" | "food" | "salon" | "transport" | "more" | "pin" | "search" | "arrow" | "route" | "clock" | "source" | "check" | "menu";
type Category = { icon: IconName; title: string; detail: string; className?: string };

const categories: Category[] = [
  { icon: "hotel", title: "Hotels", detail: "Places to stay", className: "category-card--feature" },
  { icon: "hostel", title: "Hostels & PGs", detail: "Shared and monthly stays" },
  { icon: "home", title: "Rooms & houses", detail: "Find a place to call home" },
  { icon: "shop", title: "Shops", detail: "Everyday essentials" },
  { icon: "food", title: "Food", detail: "Meals and local favorites" },
  { icon: "salon", title: "Salons", detail: "Personal care nearby" },
  { icon: "transport", title: "Transport", detail: "Get around your area" },
  { icon: "more", title: "Other services", detail: "More of local life" },
];

function LineIcon({ name, size = 22 }: { name: IconName; size?: number }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths: Record<IconName, ReactNode> = {
    hotel: <><path d="M3 20V8l9-5 9 5v12"/><path d="M7 20v-6h10v6M8 9h.01M12 9h.01M16 9h.01"/></>,
    hostel: <><path d="M4 20V6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5V20"/><path d="M4 11h16M8 8h.01M12 8h.01M16 8h.01M8 15h3v5H8zM15 15h2"/></>,
    home: <><path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-6h6v6"/></>,
    shop: <><path d="M4 9h16l-1.5-5h-13zM5 9v11h14V9M9 20v-7h6v7"/><path d="M4 9a2 2 0 0 0 4 0 2 2 0 0 0 4 0 2 2 0 0 0 4 0 2 2 0 0 0 4 0"/></>,
    food: <><path d="M4 3v7a3 3 0 0 0 6 0V3M7 3v18M17 3v18M17 3c3 2 3 7 0 9"/></>,
    salon: <><circle cx="8" cy="7" r="3"/><circle cx="8" cy="17" r="3"/><path d="m10.2 9.2 9.3 9.3M10.2 14.8l9.3-9.3"/></>,
    transport: <><rect x="4" y="3" width="16" height="16" rx="3"/><path d="M4 11h16M8 7h.01M16 7h.01M8 15h.01M16 15h.01M8 22l2-3M16 19l2 3"/></>,
    more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="12" cy="12" r="9"/></>,
    pin: <><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></>,
    search: <><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 5 5"/></>,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
    route: <><circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h2a3 3 0 0 0 3-3v-2a3 3 0 0 1 3-3h2"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    source: <><path d="M12 3 4 7v5c0 5 3.5 8 8 9 4.5-1 8-4 8-9V7z"/><path d="m9 12 2 2 4-4"/></>,
    check: <><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16"/></>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" {...common}>{paths[name]}</svg>;
}

function Brand({ footer = false }: { footer?: boolean }) {
  return <a className={`brand${footer ? " brand--footer" : ""}`} href="#home" aria-label="NEXUS home">
    <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M8 24V8l16 16V8"/></svg></span>
    <span className="brand-word">NEXUS<span>LOCAL INTELLIGENCE</span></span>
  </a>;
}

export default function HomePage({ onOpenTraffic, onOpenDiscovery }: { onOpenTraffic: () => void; onOpenDiscovery: (query?: string, category?: string, city?: string) => void }) {
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [searchMessage, setSearchMessage] = useState("");
  const [categoryMessage, setCategoryMessage] = useState("");
  const [locationMessage, setLocationMessage] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeSection, setActiveSection] = useState<"home" | "categories" | "fair-price">("home");
  const [reports, setReports] = useState<LocalReport[]>([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [reportsError, setReportsError] = useState("");

  useEffect(() => {
    const scrollTargets = [document.documentElement, document.body, document.getElementById("root")]
      .filter((target): target is HTMLElement => target instanceof HTMLElement);
    scrollTargets.forEach(target => target.classList.add("nexus-home-scroll"));
    return () => scrollTargets.forEach(target => target.classList.remove("nexus-home-scroll"));
  }, []);

  async function loadReports() {
    setReportsLoading(true);
    setReportsError("");
    try {
      const response = await fetch("/api/reports");
      if (!response.ok) throw new Error(`Reports could not be loaded (HTTP ${response.status}).`);
      const data: unknown = await response.json();
      if (!Array.isArray(data)) throw new Error("The reports service returned an unexpected response.");
      setReports(data as LocalReport[]);
    } catch (error) {
      setReportsError(error instanceof Error ? error.message : "Recent reports are temporarily unavailable.");
    } finally {
      setReportsLoading(false);
    }
  }

  useEffect(() => { void loadReports(); }, []);

  useEffect(() => {
    const sections = ["home", "categories", "fair-price"].map(id => document.getElementById(id)).filter((item): item is HTMLElement => item !== null);
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]) setActiveSection(visible[0].target.id as "home" | "categories" | "fair-price");
    }, { rootMargin: "-18% 0px -72% 0px", threshold: 0 });
    sections.forEach(section => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!profileOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setProfileOpen(false); };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [profileOpen]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const term = query.trim();
    if (!term && !location.trim()) {
      setSearchMessage("Add a place or an area to preview the discovery search.");
      return;
    }
    onOpenDiscovery(term, "", location.trim());
  }

  function useLocation() {
    setLocationMessage("");
    if (!navigator.geolocation) {
      setLocationMessage("Location is not supported by this browser. You can enter a city or area instead.");
      return;
    }
    setLocationMessage("Requesting your location…");
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => setLocationMessage(`Location shared (${coords.latitude.toFixed(4)}, ${coords.longitude.toFixed(4)}). To filter nearby listings, open Local Discovery and select Use my location there.`),
      error => setLocationMessage(error.code === error.PERMISSION_DENIED
        ? "Location permission was denied. Enter a city or area instead."
        : "Could not get your location. Enter a city or area instead."),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 },
    );
  }

  function openTraffic() {
    setMenuOpen(false);
    onOpenTraffic();
  }

  return <main className="home-page">
    <header className="site-header">
      <Brand />
      <button className="mobile-menu-toggle" type="button" aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"} aria-expanded={menuOpen} aria-controls="main-navigation" onClick={() => setMenuOpen(!menuOpen)}><LineIcon name="menu" /></button>
      <nav className={`main-navigation${menuOpen ? " is-open" : ""}`} id="main-navigation" aria-label="Main navigation">
        <a className={`nav-link${activeSection === "home" ? " is-current" : ""}`} href="#home" aria-current={activeSection === "home" ? "page" : undefined} onClick={() => setMenuOpen(false)}>Home</a>
        <a className={`nav-link${activeSection === "categories" ? " is-current" : ""}`} href="#categories" aria-current={activeSection === "categories" ? "page" : undefined} onClick={() => setMenuOpen(false)}>Explore</a>
        <a className={`nav-link${activeSection === "fair-price" ? " is-current" : ""}`} href="#fair-price" aria-current={activeSection === "fair-price" ? "page" : undefined} onClick={() => setMenuOpen(false)}>Fair Price</a>
        <button className="nav-link nav-link--button" type="button" onClick={() => onOpenDiscovery()}>Local Discovery</button>
        <button className="nav-link nav-link--button" type="button" onClick={openTraffic}>Traffic Intelligence</button>
        <button className="sign-in-button sign-in-button--mobile" type="button" onClick={() => { setProfileOpen(true); setMenuOpen(false); }}>Sign in <LineIcon name="arrow" size={16} /></button>
      </nav>
      <button className="sign-in-button sign-in-button--desktop" type="button" onClick={() => setProfileOpen(true)}>Sign in <LineIcon name="arrow" size={16} /></button>
    </header>

    <section className="hero-section" id="home" aria-labelledby="hero-title">
      <div className="hero-content">
        <div className="eyebrow"><span className="eyebrow-mark" /> ARRIVE WITH A LITTLE MORE KNOWLEDGE</div>
        <h1 id="hero-title">Know the place.<br /><span>Know the price.</span><br />Know the way.</h1>
        <p className="hero-description">Discover local places, compare reported prices and extra charges, and make better-informed decisions wherever you go.</p>
        <form className="search-panel" onSubmit={submitSearch} role="search">
          <div className="search-field search-field--what"><LineIcon name="search" size={21} /><div className="search-field-copy"><label htmlFor="discovery-query">What are you looking for?</label><input id="discovery-query" value={query} onChange={event => { setQuery(event.target.value); setSearchMessage(""); }} placeholder="Hotels, food, a service…" autoComplete="off" /></div></div>
          <span className="search-divider" aria-hidden="true" />
          <div className="search-field search-field--where"><LineIcon name="pin" size={21} /><div className="search-field-copy"><label htmlFor="discovery-location">Where?</label><input id="discovery-location" value={location} onChange={event => { setLocation(event.target.value); setSearchMessage(""); }} placeholder="City or area" autoComplete="address-level2" /></div></div>
          <button className="search-submit" type="submit">Search <LineIcon name="arrow" size={18} /></button>
        </form>
        <div className="hero-search-footer"><button className="location-shortcut" type="button" onClick={useLocation}><LineIcon name="pin" size={16} /> Use my location</button><span>Searches the place records currently available</span></div>
        {searchMessage && <p className="form-message" role="status">{searchMessage}</p>}
        {locationMessage && <p className="form-message" role="status">{locationMessage}</p>}
        <button className="hero-traffic-link" type="button" onClick={openTraffic}>Already know where? Plan your route <LineIcon name="arrow" size={16} /></button>
      </div>

      <div className="hero-art" role="img" aria-label="Conceptual illustration connecting discovery, price context, and route planning">
        <div className="hero-art-topline"><span>NEXUS / LOCAL INTELLIGENCE</span><span>01 — 03</span></div>
        <svg className="hero-route-drawing" viewBox="0 0 620 450" aria-hidden="true">
          <path className="art-road art-road--wide" d="M-20 114C100 100 106 207 213 207s109-81 191-54 110 91 236 66" />
          <path className="art-road art-road--wide" d="M66-16c46 90 20 142 94 185s132 2 153 100-21 115 45 197" />
          <path className="art-road art-road--wide" d="M433-27c-40 94-5 132 48 184s15 116 91 174" />
          <path className="art-road art-road--fine" d="M-20 114C100 100 106 207 213 207s109-81 191-54 110 91 236 66" />
          <path className="art-road art-road--fine" d="M66-16c46 90 20 142 94 185s132 2 153 100-21 115 45 197" />
          <path className="art-path" d="M111 318c61-79 121-5 168-50s58-152 145-148 63 100 113 111" />
          <circle className="art-node art-node--start" cx="111" cy="318" r="8" /><circle className="art-node art-node--mid" cx="279" cy="268" r="7" /><circle className="art-node art-node--end" cx="537" cy="231" r="9" />
          <circle className="art-ring" cx="537" cy="231" r="24" />
          <g className="art-label" transform="translate(36 60)"><rect width="148" height="44" rx="8"/><text x="14" y="18">A NEW AREA</text><text className="art-label-sub" x="14" y="33">Start with local context</text></g>
          <g className="art-label art-label--price" transform="translate(337 313)"><rect width="165" height="44" rx="8"/><text x="14" y="18">PRICE CONTEXT</text><text className="art-label-sub" x="14" y="33">Source matters</text></g>
        </svg>
        <div className="hero-art-caption"><span>CONCEPTUAL ILLUSTRATION</span><span>Not live map or place data</span></div>
        <div className="hero-art-index" aria-hidden="true">N<span>.</span></div>
      </div>
      <div className="hero-bottom-rule"><span>LOCAL PLACES</span><i /><span>PRICE TRANSPARENCY</span><i /><span>TRAFFIC INTELLIGENCE</span></div>
    </section>

    <section className="category-section section-shell" id="categories" aria-labelledby="category-title">
      <div className="section-header"><div><p className="section-kicker">A GOOD PLACE TO BEGIN</p><h2 id="category-title">Make the unfamiliar<br className="desktop-break" /> feel a little more familiar.</h2></div><p className="section-intro">From your first night in town to the places that make it feel like yours.</p></div>
      <div className="category-grid">{categories.map((category, index) => <button className={`category-card ${category.className ?? ""}`} type="button" key={category.title} onClick={() => onOpenDiscovery("", ({Hotels:"hotels", "Hostels & PGs":"hostels_pgs", "Rooms & houses":"rental_rooms", Shops:"shops_groceries", Food:"food", Salons:"salons_personal_care", Transport:"transport"} as Record<string,string>)[category.title] || "other")}><span className="category-number">0{index + 1}</span><span className="category-icon"><LineIcon name={category.icon} size={23} /></span><span className="category-title">{category.title}</span><span className="category-detail">{category.detail}</span><span className="category-arrow" aria-hidden="true"><LineIcon name="arrow" size={17} /></span></button>)}</div>
      <p className="category-status" role="status">{categoryMessage || "Browse categories in the Local Discovery directory."}</p>
    </section>

    <section className="city-section section-shell" id="explore-city" aria-labelledby="city-title">
      <div className="city-heading"><div><p className="section-kicker">YOUR NEXT NEIGHBORHOOD</p><h2 id="city-title">Explore your city.</h2></div><div className="area-context"><LineIcon name="pin" size={17} /><span>Choose a city or area in the search above</span></div></div>
      <div className="city-empty-state">
        <div className="city-empty-copy"><span className="empty-state-index">N / DISCOVERY</span><h3>Start with a local search.</h3><p>Browse available listings with their source and update information. Search results only include records currently in the directory.</p><button className="outline-action" type="button" onClick={() => onOpenDiscovery()}>Open Local Discovery <LineIcon name="arrow" size={17} /></button></div>
        <div className="city-empty-art" aria-hidden="true"><div className="empty-art-grid"/><div className="empty-art-orbit empty-art-orbit--one"/><div className="empty-art-orbit empty-art-orbit--two"/><div className="empty-art-monogram">N</div><span className="empty-art-tag empty-art-tag--one">PLACES <LineIcon name="hotel" size={15} /></span><span className="empty-art-tag empty-art-tag--two">LOCAL LIFE <LineIcon name="shop" size={15} /></span><span className="empty-art-tag empty-art-tag--three">MORE TO COME <LineIcon name="arrow" size={15} /></span></div>
      </div>
    </section>

    <section className="price-section section-shell" id="fair-price" aria-labelledby="price-title">
      <div className="price-header"><div><p className="section-kicker">A CLEARER KIND OF PRICE TAG</p><h2 id="price-title">Know what you might<br className="desktop-break" /> actually pay.</h2></div><p className="section-intro">A number only means something when you know who gave it, when, and what it includes. Price transparency is planned; no prices are available yet.</p></div>
      <div className="price-explainer">
        <div className="price-explainer-lead"><span className="price-preview-label"><i /> PLANNED PRICE CONTEXT</span><h3>Same place.<br /><span>Different sources.</span></h3><p>Illustrative labels only — no local prices or provider quotes are displayed.</p><div className="price-source-legend"><span><i className="legend-provider" /> Provider supplied</span><span><i className="legend-community" /> Community shared</span></div></div>
        <div className="price-types">
          <article className="price-type-row"><span className="price-type-mark price-type-mark--provider"><LineIcon name="source" size={18} /></span><div><h4>Advertised price</h4><p>Published by the provider. Terms, unit, and date should travel with it.</p></div><span className="price-type-status">PLANNED</span></article>
          <article className="price-type-row"><span className="price-type-mark price-type-mark--provider"><LineIcon name="route" size={18} /></span><div><h4>Quoted price</h4><p>Communicated directly by a provider; a quote can change with its terms.</p></div><span className="price-type-status">PLANNED</span></article>
          <article className="price-type-row"><span className="price-type-mark price-type-mark--community"><LineIcon name="source" size={18} /></span><div><h4>Community-reported</h4><p>Shared by a user with its reported date and applicable unit.</p></div><span className="price-type-status">PLANNED</span></article>
          <article className="price-type-row"><span className="price-type-mark price-type-mark--verified"><LineIcon name="check" size={18} /></span><div><h4>Verified price</h4><p>Would require identifiable evidence and a documented review process.</p></div><span className="price-type-status">NOT ACTIVE</span></article>
          <article className="price-type-row"><span className="price-type-mark price-type-mark--estimate">≈</span><div><h4>Estimated price</h4><p>An indicative calculation or range, never a guaranteed quote.</p></div><span className="price-type-status">PLANNED</span></article>
        </div>
      </div>
      <p className="price-disclaimer"><LineIcon name="source" size={16} /> NEXUS has no local business or price-reporting service yet. No estimates, confirmations, or verification are being represented as active.</p>
    </section>

    <section className="trust-section section-shell" id="community" aria-labelledby="trust-title">
      <div className="trust-intro"><p className="section-kicker">PEOPLE MAKE A PLACE</p><h2 id="trust-title">Local knowledge.<br /><span>Better decisions.</span></h2><p>Community details can give context to prices, extra charges, and changing services. NEXUS plans to show how each detail reached the page.</p></div>
      <div className="trust-list"><article className="trust-item"><span className="trust-item-icon"><LineIcon name="source" /></span><div><h3>Who shared it?</h3><p>Show whether a detail came from a provider, a community report, or another source.</p></div><span className="trust-item-state">SOURCE</span></article><article className="trust-item"><span className="trust-item-icon"><LineIcon name="clock" /></span><div><h3>When was it reported?</h3><p>Include the date so people can judge whether the information may be out of date.</p></div><span className="trust-item-state">RECENCY</span></article><article className="trust-item"><span className="trust-item-icon"><LineIcon name="check" /></span><div><h3>Was it checked?</h3><p>Evidence review and independent confirmations are planned, not available today.</p></div><span className="trust-item-state">PLANNED</span></article><p className="trust-disclaimer">No trust scores, contributor totals, testimonials, or verification claims are shown.</p></div>
    </section>

    <section className="traffic-section section-shell" aria-labelledby="traffic-title">
      <div className="traffic-visual" aria-hidden="true"><div className="traffic-grid"/><div className="traffic-lines"><i/><i/><i/><i/><b/></div><span className="traffic-visual-label">TRAFFIC INTELLIGENCE <LineIcon name="route" size={16} /></span><span className="traffic-visual-caption">Existing route planner</span></div>
      <div className="traffic-copy"><p className="section-kicker">ONE PART OF NEXUS IS READY TODAY</p><h2 id="traffic-title">Know the way<br /><span>before you go.</span></h2><p>Open the existing Traffic Intelligence tool for community-informed road reports and route planning. Map interactions and traffic reporting use the current NEXUS service.</p><button className="primary-action" type="button" onClick={openTraffic}>Open Traffic Intelligence <LineIcon name="arrow" size={18} /></button><span className="traffic-availability"><i /> Existing feature · routing and reports</span></div>
    </section>

    <section className="reports-section section-shell" id="recent-reports" aria-labelledby="reports-title">
      <div className="section-header section-header--compact"><div><p className="section-kicker">COMMUNITY TRAFFIC REPORTS</p><h2 id="reports-title">What’s happening on the road?</h2></div><button className="inline-action" type="button" onClick={openTraffic}>Open traffic reports <LineIcon name="arrow" size={16} /></button></div>
      {reportsLoading ? <div className="reports-state" role="status"><span className="loading-dot" /> Loading reports from NEXUS…</div>
        : reportsError ? <div className="reports-state reports-state--error" role="alert"><span>{reportsError}</span><button className="inline-action" type="button" onClick={() => void loadReports()}>Try again <LineIcon name="arrow" size={16} /></button></div>
          : reports.length === 0 ? <div className="reports-empty"><span className="reports-empty-icon"><LineIcon name="route" size={22} /></span><div><h3>No active traffic reports</h3><p>There are no current reports. NEXUS traffic reports are held in memory and expire after 30 minutes.</p></div><button className="inline-action" type="button" onClick={openTraffic}>Open Traffic Intelligence <LineIcon name="arrow" size={16} /></button></div>
            : <div className="report-list">{[...reports].sort((a, b) => b.time.localeCompare(a.time)).slice(0, 3).map((report, index) => <article className="local-report" key={`${report.time}-${index}`}><span className={`report-condition-dot condition-${report.condition.toLowerCase()}`} /><div><strong>{report.condition}{report.incident !== "None" ? ` · ${report.incident}` : " road condition"}</strong><span>{report.latitude.toFixed(4)}, {report.longitude.toFixed(4)}</span></div><time dateTime={report.time}>{new Date(report.time).toLocaleString()}</time></article>)}</div>}
    </section>

    <section className="closing-cta"><div><p className="section-kicker">A BETTER WAY TO ARRIVE</p><h2>Start with what you know.<br /><span>Discover what’s nearby.</span></h2></div><button type="button" className="closing-action" onClick={() => onOpenDiscovery()}>Explore NEXUS <LineIcon name="arrow" size={18} /></button><p>Local Discovery shows available records. Traffic Intelligence is available now.</p></section>

    <footer className="site-footer"><div className="footer-main"><div className="footer-brand-block"><Brand footer /><p>Know the place. Know the price. Know the way.</p></div><div className="footer-links"><div><h2>Explore</h2><a href="#categories">Categories</a><a href="#explore-city">Explore your city</a><a href="#fair-price">Fair Price</a></div><div><h2>About NEXUS</h2><a href="#community">Community approach</a><a href="#recent-reports">Traffic reports</a><button type="button" onClick={openTraffic}>Traffic Intelligence</button></div><div><h2>Project status</h2><p>Discovery and fair pricing are prototypes. Traffic Intelligence uses the existing NEXUS service.</p></div></div></div><div className="footer-bottom"><span>© NEXUS · Local information, with context.</span><span>Listings and price comparisons are not live yet.</span></div></footer>

    {profileOpen && <div className="signin-backdrop" onMouseDown={event => event.target === event.currentTarget && setProfileOpen(false)}><section className="signin-dialog" role="dialog" aria-modal="true" aria-labelledby="signin-title"><button className="dialog-close" type="button" autoFocus onClick={() => setProfileOpen(false)} aria-label="Close sign in dialog">×</button><span className="dialog-mark">N</span><p className="section-kicker">NEXUS ACCOUNT</p><h2 id="signin-title">Profiles are coming soon.</h2><p>Accounts and contributor profiles are not available in this prototype. NEXUS is not asking for or storing sign-in details.</p><button className="primary-action" type="button" onClick={() => setProfileOpen(false)}>Understood <LineIcon name="arrow" size={18} /></button></section></div>}
  </main>;
}
