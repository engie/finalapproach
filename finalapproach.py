import asyncio
import aiohttp
import json
import logging
from collections import namedtuple
from time import time

TOO_OLD_AGE = 60 * 5

PlaneUpdate = namedtuple('PlaneUpdate', [
    'callsign',
    'heading',
    'speed',
    'altitude',
    'lat',
    'lon',
    'pos_age',
])

class Plane:
    def __init__(self, pupdate: PlaneUpdate):
        logging.debug('First sight of ' + pupdate.callsign)
        self.callsign = pupdate.callsign
        self.announced = False
        self.update(pupdate)
    def update(self, pupdate: PlaneUpdate):
        logging.debug('Update for ' + pupdate.callsign)
        assert pupdate.callsign == self.callsign, "Callsign can't change"
        self.last_pupdate = pupdate
        self.last_updated = time()
    def get_announcement(self):
        # If it's a good time to announce, return string else None
        if self.announced:
            # Only announce once
            return None
        return None
        
    def get_pos_age(self):
        since_updated = time() - self.last_updated()
        assert since_updated > 0, "Monotonicity FTW"
        return since_updated + self.last_pupdate.pos_age

    def too_old(self):
        return self.get_pos_age() > TOO_OLD_AGE

class AirSpace:
    def __init__(self):
        self.planes = {}
    
    def seen_plane(self, hex_id, pupdate: PlaneUpdate):
        if hex_id in self.planes:
            self.planes[hex_id].update(pupdate)
        else:
            self.planes[hex_id] = Plane(pupdate)
    
    def vacuum(self):
        self.planes = {k:v for (k,v) in self.planes.items() if v.too_old()}

async def fetch_aircraft_details(session, url):
    async with session.get(url) as response:
        # Assuming the server returns a JSON response
        response_json = await response.json()
        return response_json

async def process_aircraft_details(airspace, aircraft_details):
    for plane in aircraft_details['aircraft']:
        try:
            hex_id = plane['hex']
            pupdate = PlaneUpdate(
                callsign = plane['flight'].strip(),
                heading = float(plane['track']),
                speed = float(plane['gs']),
                altitude = 0.0 if plane['alt_baro'] == 'ground' else float(plane['alt_geom']),
                lat = float(plane['lat']),
                lon = float(plane['lon']),
                pos_age = float(plane['seen_pos']),
            )
            assert pupdate.pos_age >= 0, "Position age in future"
        except KeyError as ex:
            # Sometimes we don't have the data yet. Just drop these.
            continue
        airspace.seen_plane(hex_id, pupdate)
    logging.debug(f"Currently tracking {len(airspace.planes)}")

async def poll_aircraft_json(url, interval=1):
    airspace = AirSpace()
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                aircraft_details = await fetch_aircraft_details(session, url)
                await process_aircraft_details(airspace, aircraft_details)
            except Exception as e:
                print(f"Error fetching or processing aircraft details: {e}")
            await asyncio.sleep(interval)

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s", level=logging.DEBUG
    )
    # URL of the aircraft.json file in the tar1090 project
    url = "http://raspberrypi:8504/tar1090/data/aircraft.json"
    interval = 1  # Polling interval in seconds

    asyncio.run(poll_aircraft_json(url, interval))
