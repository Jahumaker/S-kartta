import requests
import json
import xml.etree.ElementTree as ET
import math
from datetime import datetime, timedelta, timezone


CITIES = {
    "Helsinki": (60.17, 24.94),
    "Tampere": (61.50, 23.79),
    "Oulu": (65.01, 25.47),
    "Rovaniemi": (66.50, 25.73),
    "Turku": (60.45, 22.27),
    "Kuopio": (62.89, 27.68),
    "Joensuu": (62.60, 29.76),
    "Vaasa": (63.10, 21.62),
    u"Sodankyl\u00e4": (67.37, 26.63),
    u"Jyv\u00e4skyl\u00e4": (62.24, 25.75),
    "Lahti": (60.98, 25.66),
    "Pori": (61.49, 21.80),
    "Lappeenranta": (61.06, 28.19),
    "Kajaani": (64.23, 27.73),
    "Ivalo": (68.66, 27.55),
    "Utsjoki": (69.91, 27.03),
    u"Sein\u00e4joki": (62.79, 22.84),
    "Mikkeli": (61.69, 27.27),
    "Kotka": (60.47, 26.94),
    "Kokkola": (63.84, 23.13),
    # Added cities for denser forecast map
    u"H\u00e4meenlinna": (60.99, 24.46),
    "Savonlinna": (61.87, 28.88),
    "Kemi": (65.73, 24.56),
    "Kouvola": (60.87, 26.70),
    u"Maarianhamina": (60.10, 19.93),
    "Rauma": (61.13, 21.51),
    u"Salo": (60.38, 23.13),
    "Iisalmi": (63.56, 27.19),
    u"Ylivieska": (63.84, 24.54),
    u"Muonio": (67.93, 23.68),
    u"Enonteki\u00f6": (68.41, 23.63),
    "Inari": (69.07, 27.02),
    u"Nurmes": (63.54, 29.14),
    "Lieksa": (63.32, 30.02),
    u"Kuusamo": (65.97, 29.19),
}


def find_city(lat, lon):
    best = None
    best_dist = 999
    for name, (clat, clon) in CITIES.items():
        d = math.sqrt((lat - clat)**2 + (lon - clon)**2)
        if d < best_dist:
            best_dist = d
            best = name
    return best if best_dist < 1.0 else None


def fetch_observations():
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=3)

    url = (
        "https://opendata.fmi.fi/wfs?service=WFS&version=2.0.0"
        "&request=getFeature&storedquery_id=fmi::observations::weather::multipointcoverage"
        "&bbox=19,59,32,71&parameters=temperature,windspeedms"
        "&timestep=10"
        f"&starttime={start.strftime('%Y-%m-%dT%H:%M:00Z')}"
        f"&endtime={now.strftime('%Y-%m-%dT%H:%M:00Z')}"
    )

    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    # Station names keyed by coordinates (from gml:Point elements; no index arithmetic)
    ns_gml = '{http://www.opengis.net/gml/3.2}'
    name_by_pos = {}
    for pt in root.iter(ns_gml + 'Point'):
        nm = pt.find(ns_gml + 'name')
        pos = pt.find(ns_gml + 'pos')
        if nm is not None and pos is not None and pos.text:
            p = pos.text.split()
            name_by_pos[(round(float(p[0]), 4), round(float(p[1]), 4))] = (nm.text or '').strip()

    pos_el = root.find('.//{http://www.opengis.net/gmlcov/1.0}positions')
    positions = [l.strip() for l in pos_el.text.strip().split('\n') if l.strip()] if pos_el is not None and pos_el.text else []
    val_el = root.find('.//' + ns_gml + 'doubleOrNilReasonTupleList')
    values = [l.strip() for l in val_el.text.strip().split('\n') if l.strip()] if val_el is not None and val_el.text else []

    def num(v):
        try:
            f = float(v)
            return None if math.isnan(f) else f
        except (ValueError, TypeError):
            return None

    # Per station: latest non-missing temperature and wind separately
    station_map = {}
    for k in range(min(len(positions), len(values))):
        parts = positions[k].split()
        if len(parts) < 3:
            continue
        lat, lon, ts = float(parts[0]), float(parts[1]), int(parts[2])
        vals = values[k].split()
        temp = num(vals[0]) if len(vals) > 0 else None
        wind = num(vals[1]) if len(vals) > 1 else None
        key = (round(lat, 4), round(lon, 4))
        s = station_map.setdefault(key, {'name': name_by_pos.get(key, ''), 'lat': lat, 'lon': lon,
                                         'temperature': None, 'windspeedms': None, 'tts': -1, 'wts': -1})
        if temp is not None and ts > s['tts']:
            s['temperature'] = temp; s['tts'] = ts
        if wind is not None and ts > s['wts']:
            s['windspeedms'] = wind; s['wts'] = ts

    stations = []
    for s in station_map.values():
        if s['temperature'] is None:
            continue
        del s['tts']; del s['wts']
        stations.append(s)
    return stations


def fetch_forecasts():
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)

    ns_bswfs = '{http://xml.fmi.fi/schema/wfs/2.0}'
    ns_gml = '{http://www.opengis.net/gml/3.2}'
    ns_wfs = '{http://www.opengis.net/wfs/2.0}'

    cities_list = list(CITIES.keys())
    place_params = "&".join([f"place={c}" for c in cities_list])

    # --- Temperature forecast at +24h ---
    temp_url = (
        f"https://opendata.fmi.fi/wfs?service=WFS&version=2.0.0"
        f"&request=getFeature"
        f"&storedquery_id=fmi::forecast::harmonie::surface::point::simple"
        f"&{place_params}"
        f"&parameters=temperature"
        f"&starttime={end.strftime('%Y-%m-%dT%H:00:00Z')}"
        f"&endtime={end.strftime('%Y-%m-%dT%H:00:00Z')}"
    )

    resp = requests.get(temp_url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    temp_forecasts = []
    for member in root.findall(ns_wfs + 'member'):
        el = member.find(ns_bswfs + 'BsWfsElement')
        if el is None:
            continue
        pos = el.find(ns_bswfs + 'Location/' + ns_gml + 'Point/' + ns_gml + 'pos')
        val = el.find(ns_bswfs + 'ParameterValue')
        if pos is None or val is None:
            continue
        parts = pos.text.strip().split()
        lat, lon = float(parts[0]), float(parts[1])
        try:
            temp = float(val.text)
        except (ValueError, TypeError):
            continue
        city = find_city(lat, lon)
        if city:
            temp_forecasts.append({'name': city, 'lat': lat, 'lon': lon, 'temperature': round(temp, 1)})

    # --- Precipitation: sum over next 24h ---
    precip_url = (
        f"https://opendata.fmi.fi/wfs?service=WFS&version=2.0.0"
        f"&request=getFeature"
        f"&storedquery_id=fmi::forecast::harmonie::surface::point::simple"
        f"&{place_params}"
        f"&parameters=precipitation1h"
        f"&starttime={now.strftime('%Y-%m-%dT%H:00:00Z')}"
        f"&endtime={end.strftime('%Y-%m-%dT%H:00:00Z')}"
        f"&timestep=60"
    )

    resp = requests.get(precip_url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    precip_by_city = {}
    for member in root.findall(ns_wfs + 'member'):
        el = member.find(ns_bswfs + 'BsWfsElement')
        if el is None:
            continue
        pos = el.find(ns_bswfs + 'Location/' + ns_gml + 'Point/' + ns_gml + 'pos')
        val = el.find(ns_bswfs + 'ParameterValue')
        if pos is None or val is None:
            continue
        parts = pos.text.strip().split()
        lat, lon = float(parts[0]), float(parts[1])
        try:
            precip = float(val.text)
        except (ValueError, TypeError):
            precip = 0.0
        city = find_city(lat, lon)
        if city:
            if city not in precip_by_city:
                precip_by_city[city] = {'name': city, 'lat': lat, 'lon': lon, 'total': 0.0}
            precip_by_city[city]['total'] += precip

    precip_forecasts = [
        {'name': d['name'], 'lat': d['lat'], 'lon': d['lon'], 'precipitation': round(d['total'], 1)}
        for d in precip_by_city.values()
    ]

    forecast_time = end.strftime('%Y-%m-%dT%H:00:00Z')
    return temp_forecasts, precip_forecasts, forecast_time


def main():
    now = datetime.now(timezone.utc)

    import time
    try:
        with open('data.json', encoding='utf-8') as f:
            prev = json.load(f)
    except Exception:
        prev = {}

    MIN_STATIONS = 100
    print("Fetching observations...")
    stations = []
    for attempt in range(3):
        try:
            stations = fetch_observations()
        except Exception as e:
            print(f"  attempt {attempt + 1} failed: {e}")
            stations = []
        print(f"  attempt {attempt + 1}: {len(stations)} stations")
        if len(stations) >= MIN_STATIONS:
            break
        time.sleep(30)
    prev_st = prev.get('stations') or []
    if len(stations) < MIN_STATIONS and len(prev_st) > len(stations):
        print(f"  WARNING: only {len(stations)} stations, keeping previous {len(prev_st)}")
        stations = prev_st

    print("Fetching forecasts...")
    try:
        temp_fc, precip_fc, fc_time = fetch_forecasts()
    except Exception as e:
        print(f"  forecast fetch failed: {e}")
        temp_fc, precip_fc, fc_time = [], [], None
    prev_fc = prev.get('forecast') or {}
    if len(temp_fc) < 10 and prev_fc.get('temperature'):
        print("  WARNING: forecast incomplete, keeping previous")
        temp_fc, precip_fc, fc_time = prev_fc.get('temperature', []), prev_fc.get('precipitation', []), prev_fc.get('time')
    print(f"  {len(temp_fc)} temp forecasts, {len(precip_fc)} precip forecasts")

    result = {
        'updated': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stations': stations,
        'forecast': {
            'time': fc_time,
            'temperature': temp_fc,
            'precipitation': precip_fc,
        },
    }

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)

    print(f"OK: {len(stations)} obs + {len(temp_fc)} temp fc + {len(precip_fc)} precip fc")


if __name__ == '__main__':
    main()
