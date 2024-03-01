import json
from collections import namedtuple
import math
import logging
from time import time
import asyncio
import utm

# TODO: Max altitude!
TOO_OLD_AGE = 60 * 5

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
    origins = json.load(open(ROUTES_FILE))
except FileNotFoundError:
    logging.error("Callsigns not found")
    origins = {}


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


# Line intersect check. Thanks ChatGPT!
def intersect(l1, l2):
    def ccw(A, B, C):
        """Checks whether the turn formed by A, B, and C is counterclockwise."""
        return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

    def direction_check(l1, l2):
        """Checks if l1 crosses l2 from left to right"""
        l1_start, l1_end = l1
        l2_start, l2_end = l2

        def sub(a, o):
            return a[0] - o[0], a[1] - o[1]

        # l1_start as a test point, compare to l2
        # find l1_start & l2_end relative to l2_start
        l1_start_r = sub(l1_start, l2_start)
        l2_end_r = sub(l2_end, l2_start)
        # Cross product of l2_end_r & l1_start_r
        cross = l1_start_r[0] * l2_end_r[1] - l1_start_r[1] * l2_end_r[0]
        return cross > 0

    A, B = l1
    C, D = l2

    def xy(p):
        """Get a flattened easting/northing from a point"""
        return utm.from_latlon(*p)[:2]

    # Need to adjust projection or this doesn't work!
    # Don't ask how long it took me to figure this out
    A, B, C, D = xy(A), xy(B), xy(C), xy(D)

    """Returns True if line segments AB and CD intersect and AB crosses CD in the specified direction"""
    return (
        ccw(A, C, D) != ccw(B, C, D)
        and ccw(A, B, C) != ccw(A, B, D)
        and direction_check((A, B), (C, D))
    )


FINAL_APPROACH_DEPART = (
    (37.59181966551272, -122.3534828009497),
    (37.62148312786485, -122.33152168162613),
)
FINAL_APPROACH_ARRIVE = (
    (37.6242887372424, -122.31957671230637),
    (37.58451399745505, -122.33739512977348),
)

def test_intersect():
    TAKE_OFF_PATH = (
        (37.61247553658761, -122.36042044995115),
        (37.5966251358627, -122.31117464179822),
    )
    LANDING_PATH = (
        (37.592081279869774, -122.30554834016358),
        (37.611191374259015, -122.35544056250757),
    )

    intersect(FINAL_APPROACH_DEPART, TAKE_OFF_PATH)
    intersect(FINAL_APPROACH_ARRIVE, LANDING_PATH)
    not intersect(FINAL_APPROACH_DEPART, LANDING_PATH)
    not intersect(FINAL_APPROACH_ARRIVE, TAKE_OFF_PATH)


class Plane:
    def __init__(self, pupdate: PlaneUpdate):
        logging.debug("First sight of " + pupdate.callsign)
        self.callsign = pupdate.callsign
        self.last_pupdate = None

        # An announcement to share if that's worthwhile
        self.to_announce = None
        # Set to true once announced.
        self.announced = False

        self.update(pupdate)

    def update(self, pupdate: PlaneUpdate):
        logging.debug("Update for " + pupdate.callsign)
        assert pupdate.callsign == self.callsign, "Callsign can't change"
        # Check whether update shows we've crossed a line
        if self.last_pupdate != None:
            self.set_announcement(
                (
                    (self.last_pupdate.lat, self.last_pupdate.lon),
                    (pupdate.lat, pupdate.lon),
                ),
            )
        self.last_pupdate = pupdate
        self.last_updated = time()

    def set_announcement(self, line):
        if intersect(FINAL_APPROACH_DEPART, line):
            self.to_announce = f"{self.callsign} Departing"
        if intersect(FINAL_APPROACH_ARRIVE, line):
            origin = origins.get(self.callsign)
            if origin:
                self.to_announce = f"{self.callsign} from {origin}"
            else:
                self.to_announce = f"{self.callsign} Arriving"

    def get_announcement(self):
        # If it's a good time to announce, return string else None
        if self.announced:
            # Only announce once
            return None

        # Calculate an estimated *now* position, also check that.
        # Should make us more prompt on displaying.
        new_lat, new_lon = calculate_new_position(
            self.last_pupdate.lat,
            self.last_pupdate.lon,
            self.last_pupdate.speed,
            self.last_pupdate.heading,
            self.get_pos_age(),
        )
        # Check whether predicted_location crosses a line
        self.set_announcement(
            ((self.last_pupdate.lat, self.last_pupdate.lon), (new_lat, new_lon)),
        )

        if self.to_announce:
            self.announced = True
            logging.info(self.to_announce)
            return self.to_announce

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


if __name__ == "__main__":
    test_intersect()
