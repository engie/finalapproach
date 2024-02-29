import json
from collections import namedtuple
import math
import logging
from time import time
import asyncio

# TODO: Max altitude!
TOO_OLD_AGE = 60 * 5
FINAL_APPROACH_LINE_START = (37.57016396511524, -122.31635912055852)
FINAL_APPROACH_LINE_END = (37.63241984031554, -122.27826708675539)

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

ROUTES_FILE = "sfo-routes.json"
try:
    callsigns = json.load(open(ROUTES_FILE))
except FileNotFoundError:
    logging.error("Callsigns not found")
    callsigns = {}

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
        self.update(pupdate)

    def update(self, pupdate: PlaneUpdate):
        logging.debug("Update for " + pupdate.callsign)
        assert pupdate.callsign == self.callsign, "Callsign can't change"
        self.last_pupdate = pupdate

        self.last_updated = time()

    def get_announcement(self):
        # If it's a good time to announce, return string else None
        if self.announced:
            # Only announce once
            return None
        if not self.path_crossed_line():
            return None

        self.announced = True
        origin = callsigns.get(self.callsign)
        if origin:
            announcement = f"{self.callsign} from {origin}"
        else:
            announcement = self.callsign

        logging.info(announcement)
        return announcement

    def path_crossed_line(self):
        # Calculate a current position, ish.
        # TODO: This is a guess, probably OK during final approach but should
        # probably sanity check the resulting path
        new_lat, new_lon = calculate_new_position(
            self.last_pupdate.lat,
            self.last_pupdate.lon,
            self.last_pupdate.speed,
            self.last_pupdate.heading,
            self.get_pos_age(),
        )

        # Calculate if the plane has crossed the line
        def ccw(A, B, C):
            """Checks whether the turn formed by A, B, and C is counterclockwise."""
            return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

        def intersect(A, B, C, D):
            """Returns True if line segments AB and CD intersect"""
            return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)

        return intersect(
            (self.last_pupdate.lat, self.last_pupdate.lon),
            (new_lat, new_lon),
            FINAL_APPROACH_LINE_START,
            FINAL_APPROACH_LINE_END,
        )

    def get_pos_age(self):
        since_updated = time() - self.last_updated
        assert since_updated > 0, "Monotonicity FTW"
        return since_updated + self.last_pupdate.pos_age

    def too_old(self):
        return self.get_pos_age() > TOO_OLD_AGE

class AirSpace:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.planes = {}

    async def seen_plane(self, hex_id, pupdate: PlaneUpdate):
        async with self.lock:
            if hex_id in self.planes:
                self.planes[hex_id].update(pupdate)
            else:
                self.planes[hex_id] = Plane(pupdate)

    async def get_announcements(self):
        async with self.lock:
            return filter(None, [p.get_announcement() for p in self.planes.values()])

    async def vacuum(self):
        async with self.lock:
            self.planes = {k: v for (k, v) in self.planes.items() if not v.too_old()}
