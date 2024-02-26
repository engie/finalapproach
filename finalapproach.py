import asyncio
import aiohttp
import json
import logging

from airspace import AirSpace, PlaneUpdate
from display import update_display


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


async def spin_plates(url, interval):
    queue = asyncio.Queue()
    aircraft_task = asyncio.create_task(poll_aircraft_json(queue, url, interval))
    display_task = asyncio.create_task(update_display(queue))
    # Block on the data source
    await aircraft_task
    # Flush out anything left in the queue
    await queue.join()
    # Ask the display task to stop please
    display_task.cancel()

    # Wait for it to die
    try:
        await display_task
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
