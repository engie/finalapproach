import json
import requests

ROUTES_FILE = 'sfo-routes.json'

j = json.loads(requests.get("https://www.flysfo.com/flysfo/api/flight-status").content)
data = j['data']
arrivals = [d for d in data if d['flight_kind'] == 'Arrival']

try:
    callsigns = json.load(open(ROUTES_FILE))
except:
    callsigns = {}

print(f'Starting with {len(callsigns)} routes')

for flight in arrivals:
    callsign = flight['callsign']

    try:
        origin = flight['airport']['airport_city']
    except KeyError:
        origin = flight['airport']['airport_name']

    if callsign in callsigns:
        assert callsigns[callsign] == origin, 'THINGS ARE CHANGING'
    else:
        callsigns[callsign] = origin

print(f'Ending with {len(callsigns)} routes')
json.dump(callsigns, open(ROUTES_FILE, 'wt'))
