import requests
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

def fetch_fmi_data():
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=2)
    
    url = (
        "https://opendata.fmi.fi/wfs?service=WFS&version=2.0.0"
        "&request=getFeature&storedquery_id=fmi::observations::weather::multipointcoverage"
        "&bbox=19,59,32,71&parameters=temperature,windspeedms"
        "&timestep=60"
        f"&starttime={start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        f"&endtime={now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    
    root = ET.fromstring(resp.text)
    
    ns = {
        'wfs': 'http://www.opengis.net/wfs/2.0',
        'gml': 'http://www.opengis.net/gml/3.2',
        'om': 'http://www.opengis.net/om/2.0',
        'sams': 'http://www.opengis.net/samplingSpatial/2.0',
        'sam': 'http://www.opengis.net/sampling/2.0',
        'target': 'http://xml.fmi.fi/namespace/om/atmosphericfeatures/1.1',
        'gmlcov': 'http://www.opengis.net/gmlcov/1.0',
        'swe': 'http://www.opengis.net/swe/2.0',
    }
    
    station_names = []
    for loc in root.iter('{http://xml.fmi.fi/namespace/om/atmosphericfeatures/1.1}Location'):
        name = ''
        for gml_name in loc.findall('{http://www.opengis.net/gml/3.2}name'):
            if gml_name.get('codeSpace') == 'http://xml.fmi.fi/namespace/locationcode/name':
                name = gml_name.text or ''
                break
        station_names.append(name)
    
    pos_el = root.find('.//{http://www.opengis.net/gmlcov/1.0}positions')
    positions = [line.strip() for line in pos_el.text.strip().split('\n') if line.strip()] if pos_el is not None else []
    
    val_el = root.find('.//{http://www.opengis.net/gml/3.2}doubleOrNilReasonTupleList')
    values = [line.strip() for line in val_el.text.strip().split('\n') if line.strip()] if val_el is not None else []
    
    num_stations = len(station_names)
    time_steps = round(len(positions) / num_stations) if num_stations > 0 else 1
    
    station_map = {}
    for k in range(len(positions)):
        parts = positions[k].split()
        lat = float(parts[0])
        lon = float(parts[1])
        ts = int(parts[2])
        
        vals = values[k].split() if k < len(values) else []
        temp = float(vals[0]) if len(vals) > 0 and vals[0] != 'NaN' else None
        wind = float(vals[1]) if len(vals) > 1 and vals[1] != 'NaN' else None
        
        st_idx = k // time_steps
        name = station_names[st_idx] if st_idx < len(station_names) else ''
        key = name or f"{lat},{lon}"
        
        if key not in station_map or ts > station_map[key]['ts']:
            station_map[key] = {
                'name': name,
                'lat': lat,
                'lon': lon,
                'ts': ts,
                'temperature': temp,
                'windspeedms': wind,
            }
    
    stations = [s for s in station_map.values() if s['temperature'] is not None]
    for s in stations:
        del s['ts']
    
    result = {
        'updated': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'stations': stations,
    }
    
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    
    print(f"OK: {len(stations)} stations written to data.json")

if __name__ == '__main__':
    fetch_fmi_data()
