#!/usr/bin/env python3
"""
Tutors Map — dynamic filters, date pickers, field hints, and geolocation

- Country: radio (single, no "Any"); auto-selects first country on load/reset
- Levels / Types / Courses: checkboxes (multi) with live narrowing
- Availability: checkboxes (multi: True/False). Selecting none or both = Any (CamelCase labels)
- Relations: radio — "Include tutors with no relations?" with only Yes / No (no "Any" option shown)
- Date pickers: native <input type="date"> with hint text (inclusive range)
- Numeric fields: min/max and helper text; legends show ranges
- "Use my location" fills Lat/Lon (does NOT auto-fill max distance)
- My location: green pin when coordinates are present (manual or geolocation)
- Single circle highlight on click; popup links to profile when available
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from flask import Flask, jsonify, Response
import csv, os, math
from datetime import datetime

app = Flask(__name__)

# In-memory dataset
TUTORS: List[Dict[str, Any]] = []

# --------------------------------
# Helpers
# --------------------------------
def csv_path(default_name: str, env_var: str) -> str:
    p = os.getenv(env_var)
    if p and os.path.exists(p):
        return p
    local = os.path.join(os.getcwd(), default_name)
    if os.path.exists(local):
        return local
    return os.path.join("/mnt/data", default_name)

def norm_key(s: str) -> str:
    return "".join(ch for ch in (s or "").replace("\ufeff", "").strip().lower() if ch not in " _-")

def norm_country(c: str) -> str:
    c = (c or "").strip().lower()
    return {
        "nl": "Netherlands", "nld": "Netherlands", "netherlands": "Netherlands",
        "de": "Germany",     "deu": "Germany",     "germany": "Germany",
    }.get(c, c.title() if c else "Netherlands")

def parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return datetime.strptime(s, "%Y-%m-%d")
        if len(s) == 10 and s[2] == "-" and s[5] == "-":
            return datetime.strptime(s, "%d-%m-%Y")
        return datetime.fromisoformat(s.split()[0])
    except Exception:
        return None

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))

COUNTRY_BOUNDS: Dict[str, Tuple[float,float,float,float]] = {
    "Netherlands": (50.750, 3.360, 53.600, 7.227),
    "Germany":     (47.270, 5.866, 55.058, 15.043),
}

# --------------------------------
# Data loader (schema auto-detect with aliases)
# --------------------------------
def load_data() -> None:
    global TUTORS

    tutor_csv   = csv_path("Tutor.csv",   "TUTOR_CSV")
    courses_csv = csv_path("Courses.csv", "COURSES_CSV")

    print("========== STARTUP ==========")
    print(f"Tutor CSV path: {tutor_csv}")
    print(f"Courses CSV path: {courses_csv}")
    print(f"Tutor CSV exists: {os.path.exists(tutor_csv)}")
    print(f"Courses CSV exists: {os.path.exists(courses_csv)}")
    print("=============================")

    tutors_tmp: Dict[str, Dict[str, Any]] = {}

    tutor_headers: List[str] = []
    if os.path.exists(tutor_csv):
        with open(tutor_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            tutor_headers = reader.fieldnames or []
    courses_headers: List[str] = []
    if os.path.exists(courses_csv):
        with open(courses_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            courses_headers = reader.fieldnames or []

    print(f"[startup] Tutor.csv headers: {tutor_headers}")
    print(f"[startup] Courses.csv headers: {courses_headers}")

    hdrs_map: Dict[str, str] = {norm_key(h): h for h in tutor_headers}
    def pick(*aliases: str) -> Optional[str]:
        for a in aliases:
            nk = norm_key(a)
            if nk in hdrs_map:
                return hdrs_map[nk]
        return None

    # Aliases matching your files (and common variations)
    COL_TUTOR     = pick("tutor", "tutor_id", "id")
    COL_LAT       = pick("latitude", "lat", "y")
    COL_LON       = pick("longitude", "lon", "x")
    COL_COUNTRY   = pick("country", "country_code")
    COL_MAXDIST   = pick("max_travel_distance", "max_distance_km", "max_distance", "radius_km")
    COL_EXCLUDED  = pick("excluded_from_search", "excluded")
    COL_TOTAL     = pick("total_lessons", "lessons_total")
    COL_REL       = pick("number_of_relations", "relations_count")
    COL_MINREL    = pick("lessons_per_relation", "min_accepted_lessons_per_relation")
    COL_LATEST    = pick("recent_lesson", "latest_lesson_date", "last_lesson_date")
    COL_AVAILABLE = pick("available_for_new_students", "availability", "available")
    COL_NAME      = pick("name", "tutor_name")
    COL_PHOTO     = pick("photo_url", "image_url", "avatar")
    COL_PROFILE   = pick("profile_url", "link", "url")

    essential = all([COL_TUTOR, COL_LAT, COL_LON, COL_MAXDIST])
    schema_used = "B" if essential else "unknown"
    print(f"[startup] Detected schema: {schema_used}")

    # Build aggregates from Courses.csv
    courses_rows: List[Dict[str, Any]] = []
    if os.path.exists(courses_csv):
        with open(courses_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                courses_rows.append(r)

    def cget(row: Dict[str, Any], *aliases: str) -> Optional[str]:
        for a in aliases:
            if a in row and row[a] not in (None, ""):
                return row[a]
        return None

    if schema_used == "B" and os.path.exists(tutor_csv):
        agg: Dict[str, Dict[str, Any]] = {}
        for r in courses_rows:
            tid = str(cget(r, "tutor", "tutor_id", "id") or "").strip()
            if not tid:
                continue
            a = agg.setdefault(tid, {
                "courses": set(), "levels": set(), "years": set(),
                "types": set(), "types_num": set(), "availability": set()
            })
            course = cget(r, "course_name", "course")
            level  = cget(r, "school_level", "level")
            stype  = cget(r, "school_type",  "type")
            syear  = cget(r, "school_year",  "year")
            tcat   = cget(r, "tutor_category", "category")
            avail  = cget(r, "availability", "available_for_new_students", "available")

            if course: a["courses"].add(str(course))
            if level:  a["levels"].add(str(level))
            if stype:  a["types"].add(str(stype))
            try:
                if syear not in (None, ""): a["years"].add(float(syear))
            except Exception: pass
            try:
                if tcat  not in (None, ""): a["types_num"].add(float(tcat))
            except Exception: pass
            if avail not in (None, ""):
                a["availability"].add(str(avail).strip().lower() in ("true","1","yes","y"))

        with open(tutor_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    tid = str(row.get(COL_TUTOR) or "").strip()
                    if not tid:
                        continue
                    lat_s = row.get(COL_LAT) or "0"
                    lon_s = row.get(COL_LON) or "0"
                    md_s  = row.get(COL_MAXDIST) or "0"
                    country_s = row.get(COL_COUNTRY) or ""

                    name  = (row.get(COL_NAME) or f"Tutor {tid}").strip()
                    photo = (row.get(COL_PHOTO) or "https://placehold.co/512x320/png").strip()
                    prof  = (row.get(COL_PROFILE) or "").strip()

                    T = {
                        "id": tid,
                        "name": name,
                        "lat": float(lat_s),
                        "lon": float(lon_s),
                        "country": norm_country(country_s),
                        "max_distance_km": float(md_s),
                        "courses":        sorted(list(agg.get(tid, {}).get("courses", set()))),
                        "school_levels":  sorted(list(agg.get(tid, {}).get("levels", set()))),
                        "school_years":   sorted(list(agg.get(tid, {}).get("years", set()))),
                        "school_types":   sorted(list(agg.get(tid, {}).get("types", set()))),
                        "available_for_new_students": (str(row.get(COL_AVAILABLE) or "").strip().lower() in ("true","1","yes","y")) if COL_AVAILABLE else (True in agg.get(tid, {}).get("availability", {True})),
                        "excluded_from_search": (str(row.get(COL_EXCLUDED) or "").strip().lower() in ("true","1","yes","y")) if COL_EXCLUDED else False,
                        "tutor_types":     sorted(list(agg.get(tid, {}).get("types_num", set()))),
                        "min_accepted_lessons_per_relation": float(row.get(COL_MINREL) or 0.0) if COL_MINREL else 0.0,
                        "total_lessons":   int(float(row.get(COL_TOTAL) or 0)) if COL_TOTAL else 0,
                        "profile_url": prof,
                        "photo_url": photo,
                        "latest_lesson_date": str(row.get(COL_LATEST) or ""),
                        "relations_count":   int(float(row.get(COL_REL) or 0)) if COL_REL else 0,
                    }
                    tutors_tmp[tid] = T
                except Exception as e:
                    print(f"[warn] skipping tutor row due to error: {e}")

    global COUNTRY_BOUNDS
    COUNTRY_BOUNDS = {
        "Netherlands": (50.750, 3.360, 53.600, 7.227),
        "Germany":     (47.270, 5.866, 55.058, 15.043),
    }

    TUTORS = list(tutors_tmp.values())
    print(f"[startup] tutors loaded: {len(TUTORS)}")

# --------------------------------
# API
# --------------------------------
@app.get("/api/tutors")
def api_tutors() -> Response:
    return jsonify({"items": TUTORS})

@app.get("/api/filters")
def api_filters() -> Response:
    levels   = sorted({lvl for t in TUTORS for lvl in (t.get("school_levels") or [])})
    years    = sorted({float(y) for t in TUTORS for y in (t.get("school_years") or [])})
    types    = sorted({typ for t in TUTORS for typ in (t.get("school_types") or [])})
    courses  = sorted({c for t in TUTORS for c in (t.get("courses") or [])})
    ttypes   = sorted({float(x) for t in TUTORS for x in (t.get("tutor_types") or [])})
    countries = sorted({t.get("country") for t in TUTORS if t.get("country")})
    availability = sorted({bool(t.get("available_for_new_students")) for t in TUTORS})
    return jsonify({
        "school_levels": levels,
        "school_years":  years,
        "school_types":  types,
        "courses":       courses,
        "tutor_types":   ttypes,
        "countries":     countries,
        "availability":  availability,
    })

@app.get("/api/outliers")
def api_outliers() -> Response:
    outliers = []
    for t in TUTORS:
        lat, lon = float(t.get("lat", 0)), float(t.get("lon", 0))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            outliers.append({**t, "_reason": "invalid lat/lon"})
            continue
        c = t.get("country")
        bb = COUNTRY_BOUNDS.get(c)
        if bb:
            miny, minx, maxy, maxx = bb
            if not (miny <= lat <= maxy and minx <= lon <= maxx):
                outliers.append({**t, "_reason": f"outside {c} bounds"})
    return jsonify({"outliers": outliers, "count": len(outliers)})

@app.get("/api/diagnostics")
def diagnostics() -> Response:
    return jsonify({
        "count": len(TUTORS),
        "countries_in_data": sorted({t.get("country") for t in TUTORS}),
        "sample": TUTORS[:3],
    })

# --------------------------------
# Frontend (HTML+JS)
# --------------------------------
INDEX_HTML = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Tutors Map</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.3/dist/leaflet.css"/>
    <style>
      html, body { height: 100%; margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
      #app { display: grid; grid-template-columns: 520px 1fr; height: 100%; }
      #sidebar { padding: 14px; border-right: 1px solid #ddd; overflow:auto; }
      #map { height: 100%; width: 100%; }
      fieldset { border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; }
      legend { padding: 0 6px; font-size: 12px; color:#475569; }
      label { font-size:13px; }
      .hint { font-size: 11px; color:#6b7280; margin-top:4px; }
      .row { display:grid; grid-template-columns: 1fr 1fr; gap:8px; }
      .row.onecol { grid-template-columns: 1fr; } /* << make one-per-line for specific groups */
      .radio-grid { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:6px; }
      .checkbox-grid { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:6px; }
      .btn { padding: 10px 12px; border-radius: 8px; background: #2563eb; color:#fff; border:none; cursor:pointer; }
      .btn.secondary { background:#64748b; }
      #log { font-size: 12px; color:#475569; margin-top:8px; }
      a.btnlink { color:#2563eb; text-decoration:underline; }
      .inline { display:flex; gap:8px; align-items:center; }
      .badge { display:inline-block; padding:2px 6px; border-radius:6px; font-size:11px; background:#e2fbe2; color:#166534; border:1px solid #bbf7d0; }
    </style>
  </head>
  <body>
    <div id="app">
      <div id="sidebar">
        <h2>📍 Tutors Map</h2>

        <fieldset>
          <legend>Country (one)</legend>
          <div id="countryBox" class="radio-grid"></div>
        </fieldset>

        <fieldset>
          <legend>School Levels (multi)</legend>
          <div id="levelsBox" class="checkbox-grid"></div>
        </fieldset>

        <fieldset>
          <legend>School Years (Integer 1–13)</legend>
          <div class="row">
            <div>
              <label>From year</label>
              <input id="yearMin" type="number" step="1" min="1" max="13" placeholder="1" />
              <div class="hint">Inclusive</div>
            </div>
            <div>
              <label>To year</label>
              <input id="yearMax" type="number" step="1" min="1" max="13" placeholder="13" />
              <div class="hint">Inclusive</div>
            </div>
          </div>
        </fieldset>

        <fieldset>
          <legend>School Types (multi)</legend>
          <div id="typesBox" class="checkbox-grid"></div>
        </fieldset>

        <fieldset>
          <legend>Courses (multi)</legend>
          <div id="coursesBox" class="checkbox-grid"></div>
        </fieldset>

        <fieldset>
          <legend>Availability (Select True and/or False. Selecting none or both = Any)</legend>
          <div id="availBox" class="checkbox-grid"></div>
        </fieldset>

        <fieldset>
          <legend>Tutor metadata</legend>
          <!-- One line per field (stacked vertically) -->
          <div class="row onecol">
            <div>
              <label>Tutor Types (multi)</label>
              <div id="tutorTypesBox" class="checkbox-grid"></div>
              <div class="hint">1 = Junior, 2 = Senior, 3 = Supreme</div>
            </div>
            <div>
              <label>Min lessons per relation</label>
              <input id="minLPR" type="number" step="0.1" min="0" max="50" placeholder="e.g., 4.5" />
              <div class="hint">0.0–50.0</div>
            </div>
          </div>
        </fieldset>

        <fieldset>
          <legend>Latest lesson date range <span class="hint">(YYYY-MM-DD, inclusive)</span></legend>
          <div class="row">
            <div>
              <label>From</label>
              <input id="dateFrom" type="date" />
            </div>
            <div>
              <label>To</label>
              <input id="dateTo" type="date" />
            </div>
          </div>
        </fieldset>

        <fieldset>
          <legend>Relations — include tutors with no relations?</legend>
          <div id="relBox" class="radio-grid"></div>
          <div class="hint">Pick Yes or No. (No “Any” option.)</div>
        </fieldset>

        <fieldset>
          <legend>Filter by distance from coordinates <span class="badge">my location pin shown on map</span></legend>
          <div class="row">
            <div>
              <label>Latitude</label>
              <input id="refLat" type="number" step="0.000001" />
            </div>
            <div>
              <label>Longitude</label>
              <input id="refLon" type="number" step="0.000001" />
            </div>
          </div>
          <div class="inline" style="margin-top:6px;">
            <div style="flex:1">
              <label>Max Distance (km)</label>
              <input id="refMaxKm" type="number" step="0.1" min="0" max="500" placeholder="e.g., 10" />
            </div>
            <button id="geoBtn" class="btn secondary" title="Use your device location">Use my location</button>
          </div>
          <div class="hint">Geolocation works on http://localhost and https://</div>
        </fieldset>

        <div class="controls" style="margin-top:10px">
          <button id="applyBtn" class="btn">Apply</button>
          <button id="resetBtn" class="btn secondary">Reset</button>
          <button id="outliersBtn" class="btn secondary" title="Find and zoom to outliers">Find Outliers</button>
          <a href="/api/diagnostics" target="_blank" style="margin-left:8px; font-size:12px;">diagnostics</a>
        </div>
        <div id="log"></div>
      </div>

      <div id="map"></div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.3/dist/leaflet.js"></script>
    <script>
      // --- Tutor types
      const TUTOR_TYPE_LABELS = {
        1: 'Junior',
        2: 'Senior',
        3: 'Supreme',
      };
      const TUTOR_TYPE_VALUES = [1, 2, 3]; 

      // --- Map & layers
      const baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
      });
      const map = L.map('map', { center: [52.1, 5.3], zoom: 6, layers: [baseLayer] });
      const layerGroup = L.layerGroup().addTo(map);
      const myLocationLayer = L.layerGroup().addTo(map);

      // Highlight control
      let currentHighlight = null;
      const DEFAULT_CIRCLE_STYLE = { color: '#2563eb', weight: 1, fillOpacity: 0.1 };
      const HIGHLIGHT_STYLE      = { color: '#1e40af', weight: 2, fillOpacity: 0.2 };

      // My location icon (green)
      const greenIcon = new L.Icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
      });

      // State
      let ALL = [];
      let ALL_COUNTRIES = [];
      const boundsByCountry = {
        "Netherlands": [[50.750, 3.360],[53.600, 7.227]],
        "Germany":     [[47.270, 5.866],[55.058, 15.043]],
      };

      // Utils
      const byId = id => document.getElementById(id);
      const setLog = msg => { console.log('[MAP]', msg); byId('log').textContent = String(msg); };
      const parseFloatOrNull = s => (s === '' || s == null ? null : Number(s));

      // UI builders
      function radioHtml(name, values, selectedValue, labelsMap = null, includeAny = false) {
        const parts = [];
        if (includeAny) {
          const anyId = name + '_any';
          parts.push(`<label><input type="radio" name="${name}" value="" id="${anyId}" ${selectedValue===''?'checked':''}/> Any</label>`);
        }
        values.forEach(v => {
          const id = name + '_' + btoa(unescape(encodeURIComponent(String(v)))).replace(/=/g,'');
          const sel = (String(v) === String(selectedValue)) ? 'checked' : '';
          const label = labelsMap && (v in labelsMap) ? labelsMap[v] : String(v);
          parts.push(`<label><input type="radio" name="${name}" value="${v}" id="${id}" ${sel}/> ${label}</label>`);
        });
        return parts.join('');
      }
      function radioCountryHtml(values, selectedValue) {
        return radioHtml('country', values, selectedValue, null, false);
      }
      function checkboxGroupHtml(name, values, selectedSet, disabledSet=new Set(), labelsMap=null) {
        return values.map(v => {
          const id = name + '_' + btoa(unescape(encodeURIComponent(String(v)))).replace(/=/g,'');
          const sel = selectedSet.has(v) ? 'checked' : '';
          const dis = disabledSet.has(v) ? 'disabled' : '';
          const label = labelsMap && (v in labelsMap) ? labelsMap[v] : v;
          return `<label><input type="checkbox" name="${name}" value="${v}" id="${id}" ${sel} ${dis}/> ${label}</label>`;
        }).join('');
      }
      function getChecked(name) {
        return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map(el => el.value);
      }
      function getRadioValue(name) {
        const el = document.querySelector(`input[name="${name}"]:checked`);
        return el ? el.value : '';
      }
      function getCountry() { return getRadioValue('country'); }

      function dateFromInput(id) {
        const v = byId(id).value;
        return v ? new Date(v + 'T00:00:00') : null; // yyyy-mm-dd
      }

      // Build meta from a subset (for narrowing)
      function metaFromSubset(sub) {
        const levels = new Set(), types = new Set(), courses = new Set();
        const years = new Set();
        const avail = new Set();
        const ttypes = new Set();

      sub.forEach(t => {
        (t.school_levels || []).forEach(x => levels.add(x));
        (t.school_types || []).forEach(x => types.add(x));
        (t.courses || []).forEach(x => courses.add(x));
        (t.school_years || []).forEach(y => {
        if (isFinite(Number(y))) years.add(Number(y));
        });
        (t.tutor_types || []).forEach(x => {
          const n = Number(x);
        if (isFinite(n)) ttypes.add(n);
        });
        avail.add(Boolean(t.available_for_new_students));
      });

      return {
        levels: Array.from(levels).sort(),
        types: Array.from(types).sort(),
        courses: Array.from(courses).sort(),
        years: Array.from(years).sort((a, b) => a - b),
        availability: avail, // Set{true,false}
        tutor_types: ttypes, // Set{1,2,3,...}
      };
}

      // Collect current filters
      function collectFilters() {
        const country    = getCountry();                // radio
        const levels     = getChecked('levels');        // multi
        const types      = getChecked('types');         // multi
        const courses    = getChecked('courses');       // multi

        // Availability: multiselect 'True'/'False' labels; none or both = Any
        const availVals  = new Set(getChecked('available')); // 'True'/'False'
        const availSet   = new Set(Array.from(availVals).map(v => v === 'True'));

        // Relations: radio yes/no (no Any in UI). If nothing picked, treat as Any.
        const relChoice  = getRadioValue('noRel'); // 'yes' or 'no' or ''

        const tutorTypes = getChecked('tutorType')
          .map(v => Number(v))
          .filter(v => !isNaN(v));

        const minLPR   = parseFloatOrNull(byId('minLPR').value);
        const yearMin    = parseFloatOrNull(byId('yearMin').value);
        const yearMax    = parseFloatOrNull(byId('yearMax').value);
        const dateFrom   = dateFromInput('dateFrom');
        const dateTo     = dateFromInput('dateTo');
        const refLat     = parseFloatOrNull(byId('refLat').value);
        const refLon     = parseFloatOrNull(byId('refLon').value);
        const refMaxKm   = parseFloatOrNull(byId('refMaxKm').value);
        return {
          country, levels, types, courses,
          availSet, relChoice,
          tutorTypes, minLPR,
          yearMin, yearMax, dateFrom, dateTo,
          refLat, refLon, refMaxKm
        };
      }

      // Core match
      function matchesTutor(t, f) {
        if (f.country && (t.country || '') !== f.country) return false;

        // Availability filter:
        if (f.availSet && f.availSet.size === 1) {
          const want = Array.from(f.availSet)[0];
          if (Boolean(t.available_for_new_students) !== want) return false;
        }

        // Tutor types (multi) & min lessons
        if (Array.isArray(f.tutorTypes) && f.tutorTypes.length) {
          const tutorArr = Array.isArray(t.tutor_types)
            ? t.tutor_types.map(x => Number(x)).filter(v => !isNaN(v))
            : [];
          const tutorSet = new Set(tutorArr);
          const anyMatch = f.tutorTypes.some(v => tutorSet.has(v));
          if (!anyMatch) return false;
        }

        if (f.minLPR != null &&
            Number(t.min_accepted_lessons_per_relation || 0) < f.minLPR) {
          return false;
        }

        // Levels / Types / Courses (any overlap)
        if (f.levels.length) {
          const set = new Set(t.school_levels || []);
          if (!f.levels.some(v => set.has(v))) return false;
        }
        if (f.types.length) {
          const set = new Set(t.school_types || []);
          if (!f.types.some(v => set.has(v))) return false;
        }
        if (f.courses.length) {
          const set = new Set(t.courses || []);
          if (!f.courses.some(v => set.has(v))) return false;
        }

        // Years (inclusive)
        if (f.yearMin != null || f.yearMax != null) {
          const yrs = (t.school_years || []).map(Number).filter(isFinite);
          const minOK = f.yearMin == null || yrs.some(y => y >= f.yearMin);
          const maxOK = f.yearMax == null || yrs.some(y => y <= f.yearMax);
          if (!(minOK && maxOK)) return false;
        }

        // Date range (inclusive)
        if (f.dateFrom || f.dateTo) {
          const dd = t.latest_lesson_date ? new Date(t.latest_lesson_date) : null;
          if (dd && !isNaN(dd)) {
            if (f.dateFrom && dd < f.dateFrom) return false;
            if (f.dateTo   && dd > f.dateTo)   return false;
          }
        }

        // Relations filter (include tutors with no relations?) — apply only if user picked Yes/No
        if (f.relChoice) {
          const hasNone = Number(t.relations_count || 0) === 0;
          if (f.relChoice === 'yes' && !hasNone) return false;
          if (f.relChoice === 'no'  &&  hasNone) return false;
        }

        // Distance filter
        if (f.refLat != null && f.refLon != null && f.refMaxKm != null) {
          const lat = Number(t.lat), lon = Number(t.lon);
          if (!isFinite(lat) || !isFinite(lon)) return false;
          const R = 6371.0088, toRad = d => d * Math.PI / 180;
          const p1 = toRad(f.refLat), p2 = toRad(lat);
          const dphi = toRad(lat - f.refLat), dl = toRad(lon - f.refLon);
          const a = Math.sin(dphi/2)**2 + Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
          const dist = 2*R*Math.asin(Math.sqrt(a));
          if (!(dist <= f.refMaxKm)) return false;
        }
        return true;
      }

      // Subset helpers for narrowing
      function subsetRespectingAll(f) { return ALL.filter(t => matchesTutor(t, f)); }
      function subsetIgnoringAvailability(f) {
        // For availability meta, ignore availability selection entirely
        const g = { ...f, availSet: new Set() };
        return ALL.filter(t => matchesTutor(t, g));
      }

      // Subset ignoring tutorTypes (for building tutor-type options)
      function subsetIgnoringTutorTypes(f) {
        const g = { ...f, tutorTypes: [] };  // empty array ⇒ no tutorTypes filter
        return ALL.filter(t => matchesTutor(t, g));
      }

      // Rebuild dynamic option groups (checkboxes + availability checkboxes + relations radio)
      function rebuildDynamicOptions() {
        const f = collectFilters();

        // 1) Checkbox lists respect all current filters (so Courses shrink as Levels/Types change)
        const subAll = subsetRespectingAll(f);
        const metaAll = metaFromSubset(subAll);

        const selLevels  = new Set(f.levels.filter(v => metaAll.levels.includes(v)));
        const selTypes   = new Set(f.types.filter(v => metaAll.types.includes(v)));
        const selCourses = new Set(f.courses.filter(v => metaAll.courses.includes(v)));

        byId('levelsBox').innerHTML  = checkboxGroupHtml('levels',  metaAll.levels,  selLevels);
        byId('typesBox').innerHTML   = checkboxGroupHtml('types',   metaAll.types,   selTypes);
        byId('coursesBox').innerHTML = checkboxGroupHtml('courses', metaAll.courses, selCourses);

        // Tutor Types: 1=Junior, 2=Senior, 3=Supreme
        const subNoTT = subsetIgnoringTutorTypes(f);
        const metaNoTT = metaFromSubset(subNoTT);
        const presentTT = metaNoTT.tutor_types; // Set of available tutor types after other filters

        const selTutorTypes = new Set(
          (f.tutorTypes || []).filter(v => TUTOR_TYPE_VALUES.includes(v))
        );

        const disabledTutor = new Set(
          TUTOR_TYPE_VALUES.filter(v => !presentTT.has(v))
        );

        byId('tutorTypesBox').innerHTML = checkboxGroupHtml(
          'tutorType',
          TUTOR_TYPE_VALUES,
          selTutorTypes,
          disabledTutor,
          TUTOR_TYPE_LABELS
        );

        // 2) Availability checkboxes (True / False) with CamelCase labels; disable ones not present
        const subNoAvail = subsetIgnoringAvailability(f);
        const metaNoAvail = metaFromSubset(subNoAvail);
        const presentSet = metaNoAvail.availability; // Set {true/false}
        const selAvailVals = new Set(getChecked('available'));  // 'True'/'False'
        const options = ['True','False'];
        const disabled = new Set();
        if (!presentSet.has(true))  disabled.add('True');
        if (!presentSet.has(false)) disabled.add('False');

        byId('availBox').innerHTML = checkboxGroupHtml('available', options, selAvailVals, disabled, {True:'True', False:'False'});

        // 3) Relations radio (Yes / No only) — no "Any" option shown
        const current = getRadioValue('noRel'); // may be ''
        byId('relBox').innerHTML = radioHtml('noRel', ['yes','no'], current, {yes:'Yes', no:'No'}, false);
      }

      // Render markers
      function render(items) {
        layerGroup.clearLayers();
        currentHighlight = null;
        if (!items || items.length === 0) { setLog('No items after filter.'); return; }

        const markers = [];
        items.forEach(t => {
          const lat = Number(t.lat), lon = Number(t.lon);
          if (!isFinite(lat) || !isFinite(lon)) return;

          const marker = L.marker([lat, lon]).addTo(layerGroup);
          const circle = L.circle([lat, lon], {
            radius: Math.max(0, Number(t.max_distance_km || 0))*1000,
            ...DEFAULT_CIRCLE_STYLE
          }).addTo(layerGroup);

          marker.on('click', () => {
            if (currentHighlight && currentHighlight.setStyle) currentHighlight.setStyle(DEFAULT_CIRCLE_STYLE);
            circle.setStyle(HIGHLIGHT_STYLE);
            currentHighlight = circle;

            const courses = Array.isArray(t.courses) ? t.courses.join(', ') : '';
            const profile = (t.profile_url && t.profile_url.trim() !== '') ?
              `<div><a class="btnlink" href="${t.profile_url}" target="_blank" rel="noopener">Open profile ↗</a></div>` : '';

            marker.bindPopup(
              `<div style="font-size:12px;line-height:1.2;">
                <div><b>${t.name || t.id}</b></div>
                <div><b>Country:</b> ${t.country || ''}</div>
                <div><b>Courses:</b> ${courses}</div>
                <div><b>Max travel:</b> ${t.max_distance_km ?? '—'} km</div>
                <div><b>Available:</b> ${t.available_for_new_students ? 'True' : 'False'}</div>
                <div><b>Excluded:</b> ${t.excluded_from_search ? 'True' : 'False'}</div>
                <div><b>Total lessons:</b> ${t.total_lessons ?? '—'}</div>
                <div><b>Per relation:</b> ${t.min_accepted_lessons_per_relation ?? '—'} lesson(s)</div>
                ${profile}
              </div>`
            ).openPopup();
          });

        markers.push(marker);
        });

        if (markers.length) {
          const group = L.featureGroup(markers);
          try { map.fitBounds(group.getBounds().pad(0.2)); } catch(e) {}
        }
        setLog(`Plotted ${markers.length} markers.`);
      }

      // Build Country radios (single, no Any)
      function buildCountryRadios(countries) {
        ALL_COUNTRIES = countries.slice();
        const current = getRadioValue('country');
        const initial = countries.includes(current) ? current : (countries[0] || '');
        byId('countryBox').innerHTML = radioCountryHtml(countries, initial);
      }

      // --- My location pin management ---
      function updateMyLocationPin({zoom=false} = {}) {
        myLocationLayer.clearLayers();
        const lat = parseFloat(byId('refLat').value);
        const lon = parseFloat(byId('refLon').value);
        if (isFinite(lat) && isFinite(lon)) {
          const m = L.marker([lat, lon], { icon: greenIcon }).addTo(myLocationLayer);
          m.bindPopup('<b>My location</b>').openPopup();
          if (zoom) map.setView([lat, lon], Math.max(map.getZoom(), 12));
        }
      }

      // Geolocation
      byId('geoBtn').addEventListener('click', (e) => {
        e.preventDefault();
        if (!('geolocation' in navigator)) {
          setLog('Geolocation not available in this browser.');
          return;
        }
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const { latitude, longitude } = pos.coords;
            byId('refLat').value = latitude.toFixed(6);
            byId('refLon').value = longitude.toFixed(6);
            // Do NOT auto-fill max distance (as requested)
            updateMyLocationPin({zoom:true});
            setLog('Filled coordinates from your location.');
          },
          (err) => setLog('Geolocation error: ' + err.message),
          { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
        );
      });

      // Also update the green pin when user manually types coordinates
      ['refLat','refLon'].forEach(id => {
        byId(id).addEventListener('change', () => updateMyLocationPin({zoom:false}));
        byId(id).addEventListener('blur',   () => updateMyLocationPin({zoom:false}));
        byId(id).addEventListener('input',  () => updateMyLocationPin({zoom:false}));
      });

      // Boot & events
      async function loadAll() {
        const [tRes, fRes] = await Promise.all([
          fetch('/api/tutors', {cache:'no-store'}),
          fetch('/api/filters', {cache:'no-store'})
        ]);
        const t = await tRes.json();
        const f = await fRes.json();
        ALL = Array.isArray(t.items) ? t.items : [];

        buildCountryRadios(f.countries || []);

        if ((f.school_years||[]).length) {
          const yrs = (f.school_years || []).filter(y => y >= 1 && y <= 13);
          if (yrs.length) {
            byId('yearMin').value = Math.min(...yrs);
            byId('yearMax').value = Math.max(...yrs);
          }
        }

        rebuildDynamicOptions();
        setLog(`Loaded ${ALL.length} tutors.`);
      }

      // Re-narrow options whenever any relevant input changes (live)
      document.getElementById('sidebar').addEventListener('change', () => {
        rebuildDynamicOptions();
      });

      byId('applyBtn').addEventListener('click', () => {
        const f = collectFilters();
        const filtered = ALL.filter(t => matchesTutor(t, f));
        if (f.country && boundsByCountry[f.country]) map.fitBounds(boundsByCountry[f.country]);
        render(filtered);
        // Ensure my location pin stays visible
        updateMyLocationPin({zoom:false});
      });

      byId('resetBtn').addEventListener('click', () => {
        document.querySelectorAll('#sidebar input').forEach(el => {
          if (el.type === 'radio' && el.name === 'country') el.checked = false;
          else if (el.type === 'radio' && el.name === 'noRel') el.checked = false;
          else if (el.type === 'checkbox') el.checked = false;
          else el.value = '';
        });

        if (ALL_COUNTRIES.length) {
          byId('countryBox').innerHTML = radioCountryHtml(ALL_COUNTRIES, ALL_COUNTRIES[0]);
        }

        map.setView([52.1, 5.3], 6);
        layerGroup.clearLayers();
        myLocationLayer.clearLayers();
        currentHighlight = null;

        rebuildDynamicOptions();
        setLog('Reset.');
      });

      byId('outliersBtn').addEventListener('click', async () => {
        try {
          const res = await fetch('/api/outliers', {cache:'no-store'});
          const data = await res.json();
          if (!data.outliers || data.outliers.length === 0) { setLog('No outliers found.'); return; }
          const t = data.outliers[0];
          map.setView([t.lat, t.lon], 10);
          layerGroup.clearLayers();
          currentHighlight = null;
          const marker = L.marker([t.lat, t.lon]).addTo(layerGroup);
          const circle = L.circle([t.lat, t.lon], { radius: Math.max(0, Number(t.max_distance_km||0))*1000, color:'#e11d48', weight:2, fillOpacity:0.2 }).addTo(layerGroup);
          marker.bindPopup(`<b>Outlier:</b> ${t.name || t.id}<br/><b>Reason:</b> ${t._reason || ''}<br/>lat=${t.lat}, lon=${t.lon}`).openPopup();
          setLog(`Outliers: ${data.count}. Centered on first (${t.id}).`);
        } catch (e) {
          setLog('Failed to fetch outliers.');
        }
      });

      // Boot
      loadAll();
    </script>
  </body>
</html>
'''

@app.get("/")
def index() -> Response:
    return Response(INDEX_HTML, mimetype="text/html")

# --------------------------------
# Main
# --------------------------------
if __name__ == "__main__":
    load_data()
    app.run(debug=True, host="127.0.0.1", port=5000)
