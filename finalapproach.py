import asyncio
import aiohttp
import json
import logging
from collections import namedtuple
from time import time
import math

# TODO: Cleaner peer module import. Cleaner module.
import sys
import os
sys.path.append(os.path.join(os.getcwd(),'../pyled1248'))
from led1248 import send_stream, PACKET_TYPE, handle_rx, scroll, SCROLL
from ble import BLEConnection
from image import text_payload

TOO_OLD_AGE = 60 * 5
FINAL_APPROACH_LINE_START = (37.57016396511524, -122.31635912055852)
FINAL_APPROACH_LINE_END = (37.63241984031554, -122.27826708675539)
SHOW_FLIGHT_FOR = 10
#TODO: Max altitude!

PlaneUpdate = namedtuple(
    "PlaneUpdate",
    [
        "callsign",
        "heading",  # Should this be bearing?
        "speed",
        "altitude",
        "lat",
        "lon",
        "pos_age",
    ],
)


ROUTES_FILE = 'sfo-routes.json'
callsigns = json.load(open(ROUTES_FILE))

def calculate_new_position(lat, lon, speed_knots, bearing_degrees, elapsed_seconds):
    # Earth radius in nautical miles
    earth_radius_nm = 3440.065
    # Convert speed from knots to nautical miles per second
    speed_nm_per_sec = speed_knots / 3600
    # Calculate distance traveled in N seconds
    distance_nm = speed_nm_per_sec * elapsed_seconds
    # Convert bearing to radians
    bearing_rad = math.radians(bearing_degrees)
    # Convert original lat and lon to radians
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    # Calculate new latitude in radians
    new_lat_rad = math.asin(
        math.sin(lat_rad) * math.cos(distance_nm / earth_radius_nm)
        + math.cos(lat_rad)
        * math.sin(distance_nm / earth_radius_nm)
        * math.cos(bearing_rad)
    )
    # Calculate new longitude in radians
    new_lon_rad = lon_rad + math.atan2(
        math.sin(bearing_rad)
        * math.sin(distance_nm / earth_radius_nm)
        * math.cos(lat_rad),
        math.cos(distance_nm / earth_radius_nm)
        - math.sin(lat_rad) * math.sin(new_lat_rad),
    )
    # Convert new lat and lon from radians to degrees
    new_lat = math.degrees(new_lat_rad)
    new_lon = math.degrees(new_lon_rad)

    return new_lat, new_lon


class Plane:
    def __init__(self, pupdate: PlaneUpdate):
        logging.debug("First sight of " + pupdate.callsign)
        self.callsign = pupdate.callsign
        self.announced = False
        # Path of (lat, lon) coordinates
        self.path = []
        self.update(pupdate)

    def update(self, pupdate: PlaneUpdate):
        logging.debug("Update for " + pupdate.callsign)
        assert pupdate.callsign == self.callsign, "Callsign can't change"
        self.last_pupdate = pupdate

        # Calculate a current position, ish.
        # TODO: This is a guess, probably OK during final approach but should
        # probably sanity check the resulting path
        new_lat, new_lon = calculate_new_position(
            self.last_pupdate.lat,
            self.last_pupdate.lon,
            self.last_pupdate.speed,
            self.last_pupdate.heading,
            self.last_pupdate.pos_age,
        )
        self.path.append((new_lat, new_lon))
        self.last_updated = time()

    def get_announcement(self):
        # If it's a good time to announce, return string else None
        if self.announced:
            # Only announce once
            return None
        if self.path_crossed_line():
            self.announced = True

            origin = callsigns.get(self.callsign)
            if origin:
                announcement = f'{self.callsign} from {origin}'
            else:
                announcement = self.callsign

            logging.info(announcement)
            return announcement
        return None
        
    def path_crossed_line(self):
        assert len(self.path) > 0, "Need a path"
        # Calculate if the plane has crossed the line
        def ccw(A, B, C):
            """Checks whether the turn formed by A, B, and C is counterclockwise."""
            return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
        def intersect(A, B, C, D):
            """Returns True if line segments AB and CD intersect"""
            return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)
        
        for i in range(len(self.path)-1):
            segment_start = self.path[i]
            segment_end = self.path[i + 1]
            if intersect(segment_start, segment_end, FINAL_APPROACH_LINE_START, FINAL_APPROACH_LINE_END):
                return True 
        return False

    def get_pos_age(self):
        since_updated = time() - self.last_updated
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

    def get_accouncements(self):
        return filter(None, [p.get_announcement() for p in self.planes.values()])

    def vacuum(self):
        self.planes = {k: v for (k, v) in self.planes.items() if not v.too_old()}


async def fetch_aircraft_details(session, url):
    async with session.get(url) as response:
        # Assuming the server returns a JSON response
        response_json = await response.json()
        return response_json


async def process_aircraft_details(airspace, aircraft_details):
    for plane in aircraft_details["aircraft"]:
        try:
            hex_id = plane["hex"]
            pupdate = PlaneUpdate(
                callsign=plane["flight"].strip(),
                heading=float(plane["track"]),
                speed=float(plane["gs"]),
                altitude=(
                    0.0 if plane["alt_baro"] == "ground" else float(plane["alt_geom"])
                ),
                lat=float(plane["lat"]),
                lon=float(plane["lon"]),
                pos_age=float(plane["seen_pos"]),
            )
            assert pupdate.pos_age >= 0, "Position age in future"
        except KeyError as ex:
            # Sometimes we don't have the data yet. Just drop these.
            continue
        airspace.seen_plane(hex_id, pupdate)
    logging.debug(f"Currently tracking {len(airspace.planes)}")

async def poll_aircraft_json(announcement_queue, url, interval=1):
    airspace = AirSpace()
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                aircraft_details = await fetch_aircraft_details(session, url)
                await process_aircraft_details(airspace, aircraft_details)
                for announcement in airspace.get_accouncements():
                    await announcement_queue.put(announcement)
            except Exception as ex:
                logging.error(
                    f"Error fetching or processing aircraft details", exc_info=ex
                )
            airspace.vacuum()
            await asyncio.sleep(interval)

async def update_led(announcement_queue):
    UUID = "2BD223FA-4899-1F14-EC86-ED061D67B468"
    display_dirty = False
    while True:
        # TODO: Timeout & clear display
        # TODO: Rotate colors

        try:
            announcement = await asyncio.wait_for(announcement_queue.get(), SHOW_FLIGHT_FOR)
            logging.debug(f"Announcing {announcement}")
            async with BLEConnection(UUID, handle_rx) as connection:
                await scroll(connection, SCROLL.SCROLLLEFT)
                await send_stream(
                    connection,
                    PACKET_TYPE.TEXT,
                    text_payload(announcement, "red", 16),
                )
                display_dirty = True
                announcement_queue.task_done()
        except asyncio.exceptions.TimeoutError:
            if display_dirty:
                async with BLEConnection(UUID, handle_rx) as connection:
                    # Figure out a better way to clear the display
                    await send_stream(
                        connection,
                        PACKET_TYPE.TEXT,
                        text_payload("SFO Arrivals", "red", 16),
                    )
                display_dirty = False

async def spin_plates(url, interval):
    queue = asyncio.Queue()
    aircraft_task = asyncio.create_task(poll_aircraft_json(queue, url, interval))
    led_task = asyncio.create_task(update_led(queue))
    await aircraft_task
    await queue.join()
    led_task.cancel()
    
    # TODO: Understand this!
    try:
        await led_task
    except asyncio.CancelledError:
        pass  # Task cancellation should not be considered an error

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO
    )
    # URL of the aircraft.json file in the tar1090 project
    url = "http://raspberrypi:8504/tar1090/data/aircraft.json"
    interval = 0.1  # Polling interval in seconds

    asyncio.run(spin_plates(url, interval))
