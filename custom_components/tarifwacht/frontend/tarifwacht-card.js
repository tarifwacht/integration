/*
 * Tarifwacht card: what the current tariff costs, whether another tariff
 * would have been cheaper and what PV and battery save – today, this month
 * and this calendar year – without extra cards from HACS. Served and
 * registered by the integration itself (cards.py, frontend_resource.py).
 *
 *   type: custom:tarifwacht-card
 *   entity: sensor.haus_gunstigster_tarif   (the entry's "Cheapest tariff";
 *                                            any sensor of the entry will do)
 *   parts: [tariffs, solar, chart]          (optional; default: all the entry has)
 *   periods: [day, month, year]             (optional; default: all)
 *   title: …                                (optional; a single space hides the heading)
 *
 * The card finds the entry's tariffs and sensors through the websocket
 * command "tarifwacht/tariffs" (no entity ids in the config, renamed
 * entities need no change). Values per day, month and year are the change
 * of the cumulative sensors in the long-term statistics, as the statistic
 * card shows them (calendar periods in the server's time zone); the monthly
 * bars come from the monthly statistics. Statistics are asked again after
 * each five-minute compile, shared by all cards on the page and not while
 * the page is hidden.
 */

// The integration loads the file with "?v=<version>" (cards.py).
const CARD_VERSION = new URL(import.meta.url).searchParams.get("v") || "dev";
const DOMAIN = "tarifwacht";
const PARTS = ["tariffs", "solar", "chart"];
const PERIODS = ["day", "month", "year"];
const DOCS = "https://github.com/tarifwacht/integration#karte";

const TEXT = {
  de: {
    title: "Tarifvergleich",
    describe: "Was dein Tarif kostet, ob ein anderer günstiger wäre und was PV und Speicher sparen – heute, im Monat und im Jahr.",
    noEntry: "Kein Tarifwacht-Eintrag gefunden. Wähle im Editor den Sensor „Günstigster Tarif“ eines Eintrags.",
    yourTariff: "Dein Tarif:",
    cheapestThisYear: "dieses Jahr am günstigsten",
    cheaper: (name, amount) => `${name} wäre dieses Jahr ${amount} günstiger gewesen`,
    cheapestIs: "Dieses Jahr am günstigsten:",
    periods: { day: "Heute", month: "Monat", year: "Jahr" },
    average: "Ø",
    averageHint: "Durchschnittspreis seit der Einrichtung, mit Grundpreis",
    yours: "dein Tarif",
    difference: "Unterschied",
    differenceNote: "Unterschied zu deinem Tarif: + teurer, − günstiger",
    solar: (battery) => (battery ? "PV und Speicher sparen" : "PV spart"),
    withTariff: (name) => `mit ${name}`,
    withYours: (name) => `mit deinem Tarif ${name}`,
    together: "zusammen",
    pv: "PV",
    battery: "Speicher",
    costsPerMonth: "Kosten je Monat in € (letzte 12 Monate)",
    savingPerMonth: (name) => `Ersparnis je Monat in € (mit ${name}, letzte 12 Monate)`,
    paybackOf: (saved, cost) => `${saved} von ${cost}`,
    paidBack: (when) => `bezahlt seit ${when}`,
    forecast: (year) => `voraussichtlich bezahlt ${year}`,
    rough: "grob",
    roughHint: "Geschätzt aus weniger als einem Jahr – Sommer und Winter fehlen noch.",
    countedSince: (day) => `Ersparnis gezählt ab ${day} (Langzeitstatistik); davor fehlt sie in der Rechnung.`,
    noStatistics: "Noch keine Langzeitstatistik.",
    parts: { tariffs: "Tarife", solar: "PV und Speicher", chart: "Diagramm je Monat" },
    editor: {
      entity: "Eintrag (Sensor „Günstigster Tarif“)",
      title: "Überschrift (leer: Tarifvergleich, ein Leerzeichen: keine)",
      parts: "Teile (leer: alle)",
      periods: "Zeiträume (leer: alle)",
    },
  },
  en: {
    title: "Tariff comparison",
    describe: "What your tariff costs, whether another one would be cheaper and what PV and battery save – today, this month and this year.",
    noEntry: "No Tarifwacht entry found. Choose an entry's sensor “Cheapest tariff” in the editor.",
    yourTariff: "Your tariff:",
    cheapestThisYear: "cheapest this year",
    cheaper: (name, amount) => `${name} would have been ${amount} cheaper this year`,
    cheapestIs: "Cheapest this year:",
    periods: { day: "Today", month: "Month", year: "Year" },
    average: "Ø",
    averageHint: "Average price since the setup, base price included",
    yours: "your tariff",
    difference: "Difference",
    differenceNote: "Difference to your tariff: + more expensive, − cheaper",
    solar: (battery) => (battery ? "PV and battery save" : "PV saves"),
    withTariff: (name) => `with ${name}`,
    withYours: (name) => `with your tariff ${name}`,
    together: "together",
    pv: "PV",
    battery: "Battery",
    costsPerMonth: "Costs per month in € (last 12 months)",
    savingPerMonth: (name) => `Saving per month in € (with ${name}, last 12 months)`,
    paybackOf: (saved, cost) => `${saved} of ${cost}`,
    paidBack: (when) => `paid back since ${when}`,
    forecast: (year) => `expected to be paid back in ${year}`,
    rough: "rough",
    roughHint: "Estimated from less than a year – summer and winter are not both in it yet.",
    countedSince: (day) => `Saving counted from ${day} (long-term statistics); before that it is missing.`,
    noStatistics: "No long-term statistics yet.",
    parts: { tariffs: "Tariffs", solar: "PV and battery", chart: "Chart per month" },
    editor: {
      entity: "Entry (sensor “Cheapest tariff”)",
      title: "Heading (empty: tariff comparison, a single space: none)",
      parts: "Parts (empty: all)",
      periods: "Periods (empty: all)",
    },
  },
};

// Home Assistant's chart palette; the current tariff takes the first colour.
const TARIFF_COLORS = [
  "var(--graph-color-1, #4269d0)",
  "var(--graph-color-2, #f4bd4a)",
  "var(--graph-color-3, #ff725c)",
  "var(--graph-color-4, #6cc5b0)",
  "var(--graph-color-5, #3ca951)",
  "var(--graph-color-7, #a463f2)",
];
const PV_COLOR = "var(--energy-solar-color, #ff9800)";
const BATTERY_COLOR = "var(--energy-battery-out-color, #4db6ac)";

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; height: 100%; box-sizing: border-box; container-type: inline-size; }
  .head { display: flex; align-items: center; gap: 8px; margin: 0 0 12px; font-size: 16px; font-weight: 500;
    color: var(--primary-text-color); }
  .head ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
  .head .device { margin-left: auto; font-size: 12px; font-weight: 400; color: var(--secondary-text-color); }
  .summary { font-size: 14px; color: var(--primary-text-color); margin: 0 0 8px; padding: 4px; border-radius: 8px;
    cursor: pointer; }
  .summary:hover, td.link:hover, .chart:hover { background: var(--secondary-background-color); }
  .summary .good { color: var(--success-color, #43a047); white-space: nowrap; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; }
  th, td { padding: 6px 4px 6px 10px; text-align: right; border-bottom: 1px solid var(--divider-color);
    color: var(--primary-text-color); white-space: nowrap; }
  th { font-weight: 500; color: var(--secondary-text-color); }
  th:first-child, td:first-child { text-align: left; white-space: normal; padding-left: 4px; }
  td.link { cursor: pointer; }
  .name { display: flex; align-items: center; gap: 6px; }
  .name > span:last-child { min-width: 0; }
  .sub.avg-inline { display: none; }
  .dot { flex: none; width: 10px; height: 10px; border-radius: 50%; background: var(--c); }
  .sub { display: block; font-size: 12px; color: var(--secondary-text-color); font-weight: 400; }
  tr.current td { background: color-mix(in srgb, var(--primary-color, #03a9f4) 8%, transparent); }
  tr.current .name { font-weight: 500; }
  tr.diff td { font-size: 13px; color: var(--secondary-text-color); padding-top: 2px; }
  tr.diff td:first-child { padding-left: 20px; }
  tr.parent td { border-bottom: 0; padding-bottom: 2px; }
  tr td.more { color: var(--error-color, #db4437); }
  tr td.less { color: var(--success-color, #43a047); }
  tr.section th { text-align: left; padding: 16px 4px 6px; color: var(--primary-text-color); font-size: 14px;
    white-space: normal; }
  tr.section ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); vertical-align: -3px; margin-right: 4px; }
  tr.section .with { font-weight: 400; color: var(--secondary-text-color); }
  tr.total td { font-weight: 500; }
  tr.other td { color: var(--secondary-text-color); }
  tr.payback td { font-size: 13px; color: var(--secondary-text-color); text-align: left; white-space: normal; }
  tr.note td { font-size: 12px; color: var(--secondary-text-color); border-bottom: 0; padding-top: 4px;
    text-align: left; white-space: normal; }
  .chart { margin-top: 16px; border-radius: 8px; cursor: pointer; min-width: 0; }
  .chart:first-child { margin-top: 0; }
  .lead { font-size: 14px; color: var(--secondary-text-color); margin: 0 0 8px; padding: 4px; }
  .chart .caption { font-size: 13px; font-weight: 500; color: var(--primary-text-color); margin-bottom: 4px; }
  svg { width: 100%; height: auto; display: block; overflow: visible; }
  svg text { font-size: 11px; fill: var(--secondary-text-color); }
  svg .axis { stroke: var(--divider-color); stroke-width: 1; }
  svg .zero { stroke: var(--secondary-text-color); stroke-width: 1; opacity: 0.5; }
  svg .turn { stroke: var(--secondary-text-color); stroke-width: 1; opacity: 0.6; }
  svg text.year { font-size: 10px; }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
  .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    margin-right: 4px; vertical-align: -1px; background: var(--c); }
  .empty { color: var(--secondary-text-color); font-size: 14px; }
  /* Narrow (phone): the average moves under the tariff's name. */
  @container (max-width: 440px) {
    .avg { display: none; }
    .sub.avg-inline { display: block; }
    th, td { padding-left: 6px; }
  }
  @container (max-width: 360px) {
    table { font-size: 13px; }
    tr.diff td { font-size: 12px; }
    tr.diff td:first-child { padding-left: 14px; }
  }
`;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** A round axis step (1, 2 or 5 times a power of ten) of at least `raw`. */
function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw - 1e-9);
}

/** The entry's sensors "Cheapest tariff" (for the editor and the stub). */
function cheapestSensors(hass) {
  return Object.values(hass?.entities || {})
    .filter((e) => e.platform === DOMAIN && e.translation_key === "cheapest")
    .map((e) => e.entity_id)
    .sort();
}

// ---- Data shared by all cards on the page ---------------------------------------
// Per connection (a demo or a reconnect brings a new one): what the
// websocket command said per entity, the statistics per period and the
// monthly series.

const STORES = new WeakMap();
function store(hass) {
  const key = hass.connection || hass.callWS;
  let found = STORES.get(key);
  if (!found) {
    found = { info: new Map(), stats: new Map(), months: new Map() };
    STORES.set(key, found);
  }
  return found;
}

const CARDS = new Set();
let generation = 0; // counts arrived data: cards re-render when it moves
let timer = null;
function dataArrived() {
  generation += 1;
  for (const card of CARDS) card._update();
}

const RETRY_MS = 30000; // entry still starting
const STAT_EVERY_MS = 300000; // the recorder compiles statistics every 5 minutes
const STAT_DELAY_MS = 40000; // ... and commits them a little later
const MONTHS_EVERY_MS = 1800000;

/** The next refresh: just after the next five-minute compile. */
function nextCompile() {
  return Math.ceil((Date.now() + 1) / STAT_EVERY_MS) * STAT_EVERY_MS + STAT_DELAY_MS;
}

/** What the integration says about the entry of `entityId`; undefined while
 * asking, null if it is no (loaded) Tarifwacht entry. */
function entryInfo(hass, entityId) {
  const known = store(hass).info.get(entityId);
  const fresh = known && known.entities === hass.entities && (known.value || Date.now() - known.at < RETRY_MS);
  if (!fresh && !known?.loading) {
    const infos = store(hass).info;
    infos.set(entityId, { ...known, loading: true });
    hass.callWS({ type: `${DOMAIN}/tariffs`, entity_id: entityId })
      .then((value) => infos.set(entityId, { value, entities: hass.entities, at: Date.now() }))
      .catch(() => infos.set(entityId, { value: null, entities: hass.entities, at: Date.now() }))
      .finally(dataArrived);
  }
  return known?.value;
}

/** The change of a statistic in the current calendar period; undefined while
 * asking, null without statistics. */
function statValue(hass, id, period) {
  return store(hass).stats.get(`${period}|${id}`)?.value;
}

function fetchStats(hass, ids, periods) {
  const stats = store(hass).stats;
  const now = Date.now();
  const asked = [];
  for (const id of ids) {
    for (const period of periods) {
      const key = `${period}|${id}`;
      const known = stats.get(key);
      if (known?.loading || (known && (known.due > now || document.hidden))) continue;
      stats.set(key, { ...known, loading: true });
      asked.push(
        hass.callWS({
          type: "recorder/statistic_during_period",
          statistic_id: id,
          calendar: { period },
          types: ["change"],
        })
          .then((result) => {
            const change = result?.change;
            stats.set(key, { value: typeof change === "number" ? change : null, due: nextCompile() });
          })
          .catch(() => stats.set(key, { value: known?.value ?? null, due: Date.now() + 60000 })),
      );
    }
  }
  if (asked.length) Promise.allSettled(asked).then(dataArrived);
}

/** Monthly changes {statistic id: [{start, change}]}; undefined while asking. */
function monthRows(hass, ids) {
  if (!ids.length) return {};
  const months = store(hass).months;
  const key = [...ids].sort().join(",");
  const known = months.get(key);
  if (!known?.loading && (!known || (known.due < Date.now() && !document.hidden))) {
    months.set(key, { ...known, loading: true });
    // Over a year back; the recorder cuts months in the server's time zone,
    // the current month and the eleven before are shown.
    hass.callWS({
      type: "recorder/statistics_during_period",
      start_time: new Date(Date.now() - 400 * 86400000).toISOString(),
      statistic_ids: ids,
      period: "month",
      types: ["change"],
    })
      .then((rows) => months.set(key, { rows: rows || {}, due: Date.now() + MONTHS_EVERY_MS }))
      .catch(() => months.set(key, { rows: known?.rows || {}, due: Date.now() + 60000 }))
      .finally(dataArrived);
  }
  return known?.rows;
}

function startTimer() {
  if (timer) return;
  // Quiet installations hardly update hass: look for due statistics anyway.
  timer = setInterval(() => {
    for (const card of CARDS) card._fetch();
  }, 60000);
  document.addEventListener("visibilitychange", onVisible);
}

function stopTimer() {
  if (CARDS.size || !timer) return;
  clearInterval(timer);
  timer = null;
  document.removeEventListener("visibilitychange", onVisible);
}

function onVisible() {
  if (!document.hidden) for (const card of CARDS) card._fetch();
}

// ---- The card -----------------------------------------------------------------------

class TarifwachtCard extends HTMLElement {
  connectedCallback() {
    CARDS.add(this);
    startTimer();
    if (!this._resize && window.ResizeObserver) {
      // The charts are drawn at the card's width, so their text keeps its size.
      this._resize = new ResizeObserver(() => {
        const width = this.clientWidth;
        if (width && Math.abs(width - (this._width || 0)) > 16) {
          this._width = width;
          if (this._hass && this._config) this._render();
        }
      });
    }
    this._resize?.observe(this);
  }

  disconnectedCallback() {
    CARDS.delete(this);
    this._resize?.disconnect();
    stopTimer();
  }

  setConfig(config) {
    for (const key of ["parts", "periods"]) {
      if (config[key] !== undefined && !Array.isArray(config[key])) throw new Error(`${key} must be a list`);
    }
    this._config = { ...config };
    this._seen = null;
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    // Sections view: the table likes the section's full width.
    return { columns: "full", min_columns: 6 };
  }

  static getConfigElement() {
    return document.createElement("tarifwacht-card-editor");
  }

  static getStubConfig(hass) {
    const first = cheapestSensors(hass)[0];
    return first ? { entity: first } : {};
  }

  _entity() {
    return this._config?.entity || cheapestSensors(this._hass)[0];
  }

  _info() {
    const entity = this._entity();
    return entity ? entryInfo(this._hass, entity) : null;
  }

  _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return TEXT[lang] || TEXT.en;
  }

  _periods() {
    const wanted = this._config?.periods;
    return Array.isArray(wanted) && wanted.length ? PERIODS.filter((p) => wanted.includes(p)) : PERIODS;
  }

  /** The parts shown: the chosen ones (or all) the entry has. */
  _parts(info) {
    const wanted = this._config?.parts;
    const chosen = Array.isArray(wanted) && wanted.length ? PARTS.filter((p) => wanted.includes(p)) : PARTS;
    return chosen.filter((p) => p !== "solar" || info?.solar);
  }

  /** Which monthly charts: costs with the tariffs, savings with PV; a card
   * with only the chart shows both. */
  _charts(info, parts) {
    if (!parts.includes("chart")) return [];
    const alone = !parts.includes("tariffs") && !parts.includes("solar");
    const charts = [];
    if (parts.includes("tariffs") || alone) charts.push("costs");
    if (info?.solar && (parts.includes("solar") || alone)) charts.push("savings");
    return charts;
  }

  /** The tariffs, the current one first; the tariff PV and battery are
   * shown under (the current one, else the first). */
  _tariffs(info) {
    const tariffs = [...(info.tariffs || [])];
    tariffs.sort((a, b) => Number(b.current) - Number(a.current));
    return tariffs.map((tariff, i) => ({ ...tariff, color: TARIFF_COLORS[i % TARIFF_COLORS.length] }));
  }

  /** Start what is due: the entry's info, the statistics, the months. */
  _fetch() {
    if (!this._hass || !this._config) return;
    const info = this._info();
    if (!info) return;
    const parts = this._parts(info);
    const tariffs = this._tariffs(info);
    const ids = new Set();
    if (parts.includes("tariffs")) {
      for (const t of tariffs) {
        if (t.entities.cost) ids.add(t.entities.cost);
        if (t.entities.difference) ids.add(t.entities.difference);
      }
    }
    if (parts.includes("solar")) {
      for (const t of tariffs) {
        if (t.entities.saving_pv) ids.add(t.entities.saving_pv);
        if (t.entities.saving_battery) ids.add(t.entities.saving_battery);
      }
    }
    fetchStats(this._hass, [...ids], this._periods());
    // The summary counts the calendar year, also without the column "Year".
    if (parts.includes("tariffs")) fetchStats(this._hass, this._summaryIds(tariffs), ["year"]);
    for (const chart of this._charts(info, parts)) {
      const series = this._series(chart, tariffs, this._t());
      if (series.length) monthRows(this._hass, series.map((s) => s.id));
    }
  }

  /** The series of a monthly chart: cost per tariff, or the saving by PV
   * and battery under the tariff they are shown under. */
  _series(chart, tariffs, t) {
    if (chart === "costs") {
      return tariffs.filter((x) => x.entities.cost)
        .map((x) => ({ key: x.key, id: x.entities.cost, label: x.title, color: x.color }));
    }
    const base = tariffs[0];
    return [
      { key: "pv", id: base?.entities.saving_pv, label: t.pv, color: PV_COLOR },
      { key: "battery", id: base?.entities.saving_battery, label: t.battery, color: BATTERY_COLOR },
    ].filter((s) => s.id);
  }

  /** Fetch what is due; render when something shown changed. */
  _update() {
    if (!this._hass || !this._config) return;
    this._fetch();
    const info = this._info();
    // The savings of the first tariff: their attributes carry the payback.
    const first = info?.tariffs ? this._tariffs(info)[0] : undefined;
    const watched = [
      this._entity(),
      ...(info?.tariffs || []).map((t) => t.entities.average_price),
      first?.entities.saving_pv,
      first?.entities.saving_battery,
    ].map((id) => (id ? this._hass.states[id] : undefined));
    const seen = [generation, this._hass.locale?.language, this._hass.locale?.number_format, ...watched];
    if (this._seen && seen.length === this._seen.length && seen.every((v, i) => v === this._seen[i])) return;
    this._seen = seen;
    this._render();
  }

  // ---- Formatting ---------------------------------------------------------------------

  /** Locale for numbers as the user's number format says (HA's mapping). */
  _numberLocale() {
    const locale = this._hass?.locale || {};
    return {
      comma_decimal: ["en-US", "en"],
      decimal_comma: ["de", "es", "it"],
      space_comma: ["fr", "sv", "cs"],
      system: undefined,
    }[locale.number_format] ?? locale.language ?? "en";
  }

  _num(value, digits) {
    if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "–";
    return new Intl.NumberFormat(this._numberLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(value));
  }

  /** Euros: "68,59 €", from 1,000 without cents ("1.205 €"); "…" while
   * asking, "–" without statistics. */
  _eur(value, sign = false) {
    if (value === undefined) return "…";
    if (value === null || Number.isNaN(Number(value))) return "–";
    const digits = Math.abs(value) >= 999.995 ? 0 : 2;
    return new Intl.NumberFormat(this._numberLocale(), {
      style: "currency",
      currency: "EUR",
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      signDisplay: sign ? "exceptZero" : "auto",
    }).format(Number(value));
  }

  _timeZone() {
    return this._hass?.locale?.time_zone === "local" ? undefined : this._hass?.config?.time_zone;
  }

  // ---- Rendering ----------------------------------------------------------------------

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (event) => {
        const target = event.composedPath().find((el) => el.dataset && el.dataset.entity);
        if (target) {
          this.dispatchEvent(new CustomEvent("hass-more-info", {
            detail: { entityId: target.dataset.entity }, bubbles: true, composed: true,
          }));
        }
      });
    }
    const t = this._t();
    const info = this._info();
    let body;
    if (info === undefined) {
      body = `<div class="empty">…</div>`;
    } else if (!info) {
      body = `<div class="empty">${escapeHtml(t.noEntry)}</div>`;
    } else {
      const parts = this._parts(info);
      const tariffs = this._tariffs(info);
      body = this._heading(t, info, parts)
        + (parts.includes("tariffs") ? this._summary(t, info, tariffs) : "")
        + this._table(t, info, parts, tariffs)
        + this._charts(info, parts).map((chart) => this[`_${chart}Chart`](t, tariffs)).join("");
    }
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${body}</ha-card>`;
  }

  _heading(t, info, parts) {
    if (!this._headingShown()) return "";
    const title = this._config.title === undefined ? "" : String(this._config.title);
    const solarOnly = parts.includes("solar") && !parts.includes("tariffs");
    const text = title || (solarOnly ? t.solar(info.battery) : t.title);
    const icon = solarOnly ? "mdi:solar-power-variant" : "mdi:scale-balance";
    return `<div class="head"><ha-icon icon="${icon}"></ha-icon>${escapeHtml(text)}`
      + `<span class="device">${escapeHtml(info.title)}</span></div>`;
  }

  /** The statistics the summary compares in the calendar year: the
   * difference of every other tariff to the current one; without a current
   * tariff the cost of each. */
  _summaryIds(tariffs) {
    const current = tariffs.some((x) => x.current);
    return tariffs
      .map((x) => (current ? !x.current && x.entities.difference : x.entities.cost))
      .filter(Boolean);
  }

  /** "Your tariff: Fixed ✓ cheapest this year" or "… · Dynamic would have
   * been 52.81 € cheaper this year": the calendar year, as the column
   * "Year" counts it (the change of the differences in the long-term
   * statistics; within the year of the setup from the setup, with imported
   * statistics from 1 January). Nothing is claimed while a value is asked. */
  _summary(t, info, tariffs) {
    const current = tariffs.find((x) => x.current);
    const key = current ? "difference" : "cost";
    const values = tariffs
      .filter((x) => (current ? !x.current : true) && x.entities[key])
      .map((x) => ({ tariff: x, id: x.entities[key], value: statValue(this._hass, x.entities[key], "year") }));
    const asking = values.some((v) => v.value === undefined);
    const known = asking ? [] : values.filter((v) => typeof v.value === "number");
    const best = known.reduce((a, b) => (a && a.value <= b.value ? a : b), null);
    let target = info.cheapest;
    let text;
    if (!current) {
      if (!best || known.length < values.length) return "";
      text = `${escapeHtml(t.cheapestIs)} <b>${escapeHtml(best.tariff.title)}</b>`;
      target = best.id;
    } else {
      text = `${escapeHtml(t.yourTariff)} <b>${escapeHtml(current.title)}</b>`;
      if (best && best.value <= -0.005) {
        text += ` · ${escapeHtml(t.cheaper(best.tariff.title, this._eur(-best.value)))}`;
        target = best.id;
      } else if (!asking && known.length === values.length) {
        text += ` <span class="good">✓ ${escapeHtml(t.cheapestThisYear)}</span>`;
      }
    }
    const link = target ? ` data-entity="${escapeHtml(target)}"` : "";
    return `<div class="summary"${link}>${text}</div>`;
  }

  _cell(id, period, sign = false) {
    if (!id) return "<td>–</td>";
    const value = statValue(this._hass, id, period);
    const tone = sign && typeof value === "number" && Math.abs(value) >= 0.005 ? (value > 0 ? " more" : " less") : "";
    return `<td class="link${tone}" data-entity="${escapeHtml(id)}">${escapeHtml(this._eur(value, sign))}</td>`;
  }

  /** One table, so the columns of tariffs and savings line up. */
  _table(t, info, parts, tariffs) {
    const periods = this._periods();
    const showTariffs = parts.includes("tariffs");
    const showSolar = parts.includes("solar");
    if (!showTariffs && !showSolar) return "";
    const average = showTariffs;
    const columns = 1 + periods.length + (average ? 1 : 0);
    const head = `<tr><th></th>${periods.map((p) => `<th>${escapeHtml(t.periods[p])}</th>`).join("")}`
      + `${average ? `<th class="avg" title="${escapeHtml(t.averageHint)}">${escapeHtml(t.average)}</th>` : ""}</tr>`;
    let rows = "";
    let differences = false;
    if (showTariffs) {
      for (const tariff of tariffs) {
        const e = tariff.entities;
        const avg = e.average_price && this._hass.states[e.average_price];
        const avgText = avg && !["unknown", "unavailable"].includes(avg.state) ? `${this._num(avg.state, 1)} ct` : "–";
        const hasDiff = !tariff.current && Boolean(e.difference);
        differences ||= hasDiff;
        const name = `<td><div class="name"><span class="dot" style="--c:${tariff.color}"></span><span>${escapeHtml(tariff.title)}`
          + `${tariff.current ? `<span class="sub">${escapeHtml(t.yours)}</span>` : ""}`
          + `<span class="sub avg-inline">${escapeHtml(t.average)} ${escapeHtml(avgText)}</span></span></div></td>`;
        rows += `<tr class="${tariff.current ? "current" : ""}${hasDiff ? " parent" : ""}">${name}`
          + periods.map((p) => this._cell(e.cost, p)).join("")
          + `<td class="avg${e.average_price ? ` link" data-entity="${escapeHtml(e.average_price)}` : ""}">${escapeHtml(avgText)}</td></tr>`;
        if (hasDiff) {
          rows += `<tr class="diff"><td>${escapeHtml(t.difference)}</td>`
            + periods.map((p) => this._cell(e.difference, p, true)).join("") + `<td class="avg"></td></tr>`;
        }
      }
    }
    if (differences) {
      rows += `<tr class="note"><td colspan="${columns}">${escapeHtml(t.differenceNote)}</td></tr>`;
    }
    let before = "";
    if (showSolar) {
      const base = tariffs[0];
      const pad = average ? `<td class="avg"></td>` : "";
      const sum = (tariff, p) => {
        const values = [tariff.entities.saving_pv, tariff.entities.saving_battery]
          .filter(Boolean).map((id) => statValue(this._hass, id, p));
        if (!values.length) return null;
        if (values.some((v) => v === undefined)) return undefined;
        return values.some((v) => v === null) ? null : values.reduce((a, b) => a + b, 0);
      };
      const sumRow = (cls, label, tariff) => `<tr class="${cls}"><td>${escapeHtml(label)}</td>`
        + periods.map((p) => `<td class="link" data-entity="${escapeHtml(tariff.entities.saving_pv || "")}">${escapeHtml(this._eur(sum(tariff, p)))}</td>`).join("")
        + `${pad}</tr>`;
      // Alone under its own heading ("PV and battery save"), the tariff
      // goes above the table; else a heading row in the table.
      const with_ = base.current ? t.withYours(base.title) : t.withTariff(base.title);
      if (!showTariffs && this._headingShown() && this._config.title === undefined) {
        before = `<div class="lead">${escapeHtml(with_)}</div>`;
      } else {
        rows += `<tr class="section"><th colspan="${columns}"><ha-icon icon="mdi:solar-power-variant"></ha-icon>`
          + `${escapeHtml(t.solar(info.battery))} <span class="with">(${escapeHtml(with_)})</span></th></tr>`;
      }
      if (info.battery) rows += sumRow("total", t.together, base);
      rows += `<tr><td>${escapeHtml(t.pv)}</td>${periods.map((p) => this._cell(base.entities.saving_pv, p)).join("")}${pad}</tr>`;
      if (info.battery) {
        rows += `<tr><td>${escapeHtml(t.battery)}</td>${periods.map((p) => this._cell(base.entities.saving_battery, p)).join("")}${pad}</tr>`;
      }
      rows += this._payback(t, t.pv, base.entities.saving_pv, columns);
      if (info.battery) rows += this._payback(t, t.battery, base.entities.saving_battery, columns);
      for (const tariff of tariffs.slice(1)) rows += sumRow("other", t.withTariff(tariff.title), tariff);
    }
    return `${before}<table>${head}${rows}</table>`;
  }

  /** "Battery: 1,240 € of 4,500 € – expected to be paid back in 2031", from
   * the attributes of a saving sensor; nothing without a purchase cost. */
  _payback(t, label, id, columns) {
    const a = id && this._hass.states[id]?.attributes;
    if (!a || typeof a.purchase_cost_eur !== "number") return "";
    const date = (iso, options) => new Date(`${iso}T12:00:00`).toLocaleDateString(this._numberLocale(), options);
    let text = t.paybackOf(this._eur(a.saved_since_commissioning_eur), this._eur(a.purchase_cost_eur));
    let hint = "";
    if (a.paid_back && a.paid_back_on) {
      text += ` – ${t.paidBack(date(a.paid_back_on, { month: "long", year: "numeric" }))}`;
    } else if (a.paid_back_forecast) {
      text += ` – ${t.forecast(a.paid_back_forecast.slice(0, 4))}`;
      if (a.forecast_rough) {
        text += ` (${t.rough})`;
        hint = t.roughHint;
      }
    }
    if (a.counted_since && a.commissioned_on && a.counted_since > a.commissioned_on) {
      hint = [hint, t.countedSince(date(a.counted_since, { day: "2-digit", month: "2-digit", year: "numeric" }))]
        .filter(Boolean).join(" ");
    }
    const title = hint ? ` title="${escapeHtml(hint)}"` : "";
    return `<tr class="payback"><td colspan="${columns}" class="link" data-entity="${escapeHtml(id)}"${title}>`
      + `${escapeHtml(label)}: ${escapeHtml(text)}</td></tr>`;
  }

  /** False when the title is a single space (no heading). */
  _headingShown() {
    const title = this._config.title === undefined ? undefined : String(this._config.title);
    return !(title !== undefined && title !== "" && title.trim() === "");
  }

  // ---- Charts -------------------------------------------------------------------------

  /** "2026-11": year and month of a moment in the server's time zone. */
  _ym(ms) {
    return new Date(ms).toLocaleDateString("en-CA", { timeZone: this._timeZone(), year: "numeric", month: "2-digit" });
  }

  /** Months of the series: [[start, {series key: change}]], the last twelve
   * months (the current one and the eleven before); the current month as
   * the table shows it (the monthly statistics lag up to an hour). */
  _monthData(ids, series) {
    const rows = monthRows(this._hass, ids);
    if (rows === undefined) return undefined;
    const months = new Map();
    for (const s of series) {
      for (const row of rows[s.id] || []) {
        if (typeof row.change !== "number") continue;
        const start = typeof row.start === "number" ? row.start : Date.parse(row.start);
        const m = months.get(start) || {};
        m[s.key] = row.change;
        months.set(start, m);
      }
    }
    const now = this._ym(Date.now());
    const [year, month] = now.split("-").map(Number);
    const back = year * 12 + month - 1 - 11;
    const first = `${Math.floor(back / 12)}-${String((back % 12) + 1).padStart(2, "0")}`;
    const sorted = [...months.entries()]
      .filter(([start]) => this._ym(start) >= first && this._ym(start) <= now)
      .sort((a, b) => a[0] - b[0]);
    if (sorted.length) {
      const last = sorted[sorted.length - 1];
      if (this._ym(last[0]) === now) {
        for (const s of series) {
          const value = statValue(this._hass, s.id, "month");
          if (typeof value === "number") last[1][s.key] = value;
        }
      }
    }
    return sorted;
  }

  _costsChart(t, tariffs) {
    const series = this._series("costs", tariffs, t);
    return this._chartBlock(t, t.costsPerMonth, series, false, series[0]?.id);
  }

  _savingsChart(t, tariffs) {
    const series = this._series("savings", tariffs, t);
    return this._chartBlock(t, t.savingPerMonth(tariffs[0].title), series, true, series[0]?.id);
  }

  _chartBlock(t, caption, series, stacked, target) {
    if (!series.length) return "";
    const months = this._monthData(series.map((s) => s.id), series);
    let inner;
    if (months === undefined) inner = `<div class="empty">…</div>`;
    else if (!months.length) inner = `<div class="empty">${escapeHtml(t.noStatistics)}</div>`;
    else inner = this._barChart(caption, months, series, stacked);
    const legend = series.map((s) => `<span style="--c:${s.color}">${escapeHtml(s.label)}</span>`).join("");
    return `<div class="chart" data-entity="${escapeHtml(target || "")}"><div class="caption">${escapeHtml(caption)}</div>`
      + `${inner}<div class="legend">${legend}</div></div>`;
  }

  /** Bars per month: side by side (costs per tariff) or stacked (PV and
   * battery; a negative part goes below zero). Drawn at the card's width.
   * Months of the previous calendar year are paler; a thin line before
   * January with the two years marks the turn of the year (as the column
   * "Year" counts the calendar year). */
  _barChart(caption, months, series, stacked) {
    const thisYear = this._ym(Date.now()).slice(0, 4);
    const turn = months.findIndex(([start]) => this._ym(start).slice(0, 4) === thisYear);
    const W = Math.max(260, Math.round((this._width || 520) - 32));
    const H = turn > 0 ? 184 : 170;
    const L = 40;
    const R = 4;
    const T = turn > 0 ? 22 : 8;
    const B = 20;
    let lo = 0;
    let hi = 0;
    for (const [, m] of months) {
      if (stacked) {
        const values = series.map((s) => m[s.key] || 0);
        hi = Math.max(hi, values.filter((v) => v > 0).reduce((a, b) => a + b, 0));
        lo = Math.min(lo, values.filter((v) => v < 0).reduce((a, b) => a + b, 0));
      } else {
        for (const s of series) {
          hi = Math.max(hi, m[s.key] ?? 0);
          lo = Math.min(lo, m[s.key] ?? 0);
        }
      }
    }
    if (hi - lo <= 0) hi = 1;
    const step = niceStep((hi - lo) / 4);
    const y0 = Math.floor(lo / step + 1e-9) * step;
    const y1 = Math.ceil(hi / step - 1e-9) * step || step;
    const y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
    const lang = this._hass.locale?.language || "en";
    const zone = this._timeZone();
    let grid = "";
    for (let v = y0; v <= y1 + step / 2; v += step) {
      grid += `<line class="${Math.abs(v) < step / 2 ? "zero" : "axis"}" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"`
        + `${Math.abs(v) < step / 2 ? "" : ` stroke-dasharray="2 3"`}/>`
        + `<text x="${L - 4}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${this._num(v, 0)}</text>`;
    }
    const slot = (W - L - R) / months.length;
    const every = slot < 30 ? 2 : 1;
    let bars = "";
    if (turn > 0) {
      const x = (L + turn * slot).toFixed(1);
      const year = (start) => new Date(start).toLocaleDateString(lang, { year: "numeric", timeZone: zone });
      bars += `<line class="turn" x1="${x}" x2="${x}" y1="2" y2="${H - B}"/>`
        + `<text class="year" x="${(L + turn * slot - 4).toFixed(1)}" y="12" text-anchor="end">${escapeHtml(year(months[turn - 1][0]))}</text>`
        + `<text class="year" x="${(L + turn * slot + 4).toFixed(1)}" y="12">${escapeHtml(year(months[turn][0]))}</text>`;
    }
    months.forEach(([start, m], i) => {
      const date = new Date(start);
      const label = date.toLocaleDateString(lang, { month: "short", timeZone: zone });
      const long = date.toLocaleDateString(lang, { month: "long", year: "numeric", timeZone: zone });
      const past = turn > 0 && i < turn ? ` fill-opacity="0.45"` : "";
      const rect = (x, from, to, width, s, value) => {
        const top = Math.min(y(from), y(to));
        const height = Math.max(Math.abs(y(from) - y(to)), value ? 1 : 0);
        return `<rect x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${width.toFixed(1)}" height="${height.toFixed(1)}" fill="${s.color}"${past} rx="1">`
          + `<title>${escapeHtml(long)} · ${escapeHtml(s.label)}: ${escapeHtml(this._eur(value))}</title></rect>`;
      };
      if (stacked) {
        const width = Math.min(36, Math.max(3, slot * 0.55));
        const x = L + i * slot + (slot - width) / 2;
        let up = 0;
        let down = 0;
        for (const s of series) {
          const v = m[s.key];
          if (typeof v !== "number" || !v) continue;
          if (v > 0) {
            bars += rect(x, up, up + v, width, s, v);
            up += v;
          } else {
            bars += rect(x, down, down + v, width, s, v);
            down += v;
          }
        }
      } else {
        const inner = Math.min(slot * 0.8, 24 * series.length);
        const width = Math.max(1.5, inner / series.length - 1);
        const left = L + i * slot + (slot - inner) / 2;
        series.forEach((s, j) => {
          const v = m[s.key];
          if (typeof v !== "number") return;
          bars += rect(left + j * (inner / series.length), 0, v, width, s, v);
        });
      }
      if ((months.length - 1 - i) % every === 0) {
        bars += `<text x="${(L + i * slot + slot / 2).toFixed(1)}" y="${H - 5}" text-anchor="middle">${escapeHtml(label)}</text>`;
      }
    });
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(caption)}">${grid}${bars}</svg>`;
  }
}

// ---- Editor -------------------------------------------------------------------------

class TarifwachtCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    CARDS.add(this); // re-render when the entry's info arrives
  }

  disconnectedCallback() {
    CARDS.delete(this);
  }

  _update() {
    this._render();
  }

  _fetch() {}

  _render() {
    if (!this._hass || !this._config) return;
    const lang = (this._hass.locale?.language || "en").slice(0, 2);
    const t = TEXT[lang] || TEXT.en;
    const sensors = cheapestSensors(this._hass);
    const entity = this._config.entity || sensors[0];
    const info = entity ? entryInfo(this._hass, entity) : undefined;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (event) => {
        const value = { ...event.detail.value };
        for (const key of Object.keys(value)) {
          if (value[key] === "" || value[key] === null || value[key] === undefined
            || (Array.isArray(value[key]) && !value[key].length)) delete value[key];
        }
        this._config = { type: this._config.type, ...value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const entitySelector = { filter: { integration: DOMAIN, domain: "sensor" } };
    if (sensors.length) entitySelector.include_entities = sensors;
    // PV and battery only where the entry has them (all while unknown).
    const parts = PARTS.filter((p) => p !== "solar" || !info || info.solar);
    this._form.computeLabel = (schema) => t.editor[schema.name] || schema.name;
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: entitySelector } },
      { name: "title", selector: { text: {} } },
      { name: "parts", selector: { select: { multiple: true, options: parts.map((p) => ({ value: p, label: t.parts[p] })) } } },
      { name: "periods", selector: { select: { multiple: true, options: PERIODS.map((p) => ({ value: p, label: t.periods[p] })) } } },
    ];
  }
}

if (!customElements.get("tarifwacht-card")) {
  customElements.define("tarifwacht-card-editor", TarifwachtCardEditor);
  customElements.define("tarifwacht-card", TarifwachtCard);
  window.customCards = window.customCards || [];
  const lang = (navigator.language || "en").slice(0, 2);
  const t = TEXT[lang] || TEXT.en;
  window.customCards.push({
    type: "tarifwacht-card",
    name: "Tarifwacht",
    description: t.describe,
    preview: true,
    documentationURL: DOCS,
  });
  console.info(`%c TARIFWACHT %c ${CARD_VERSION} `, "color:#fff;background:#96497D", "color:#96497D");
}
