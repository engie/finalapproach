import asyncio
import aiohttp
import json
import logging
import time

from airspace import AirSpace, PlaneUpdate
from display import update_display
from watchdog import Watchdog


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
        await airspace.seen_plane(hex_id, pupdate)
    logging.debug(f"Currently tracking {len(airspace.planes)}")

WEB_POLL_INTERVAL = 2
async def poll_aircraft_json(watchdog, airspace, url):
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                aircraft_details = await fetch_aircraft_details(session, url)
                await process_aircraft_details(airspace, aircraft_details)
            except Exception as ex:
                logging.error(
                    f"Error fetching or processing aircraft details", exc_info=ex
                )
            await airspace.vacuum()
            await watchdog.ack()
            await asyncio.sleep(WEB_POLL_INTERVAL)

UPDATE_ANNOUNCEMENT_INTERVAL = 0.1
async def update_announcements(watchdog, airspace, announcement_queue):
    while True:
        announcements = await airspace.get_announcements()
        for announcement in announcements:
            await announcement_queue.put(announcement)
        await watchdog.ack()
        await asyncio.sleep(UPDATE_ANNOUNCEMENT_INTERVAL)

async def spin_plates(url, watchdog_file):
    queue = asyncio.Queue()
    airspace = AirSpace()
    watchdog = Watchdog(watchdog_file)
    poll_task_watch = watchdog.addTask('poll', 5)
    poll_json_task = asyncio.create_task(poll_aircraft_json(poll_task_watch, airspace, url))
    aircraft_task_watch = watchdog.addTask('airspace', 5)
    aircraft_task = asyncio.create_task(update_announcements(aircraft_task_watch, airspace, queue))
    display_task_watch = watchdog.addTask('display', 5)
    display_task = asyncio.create_task(update_display(display_task_watch, queue))

    watchdog_task = asyncio.create_task(watchdog.monitor())

    # Block on the data source
    await poll_json_task
    aircraft_task.cancel()
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
    
    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s", level=logging.DEBUG
    )
    # URL of the aircraft.json file in the tar1090 project
    url = "http://192.168.8.137:8504/tar1090/data/aircraft.json"

    asyncio.run(spin_plates(url, None))
