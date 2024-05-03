import asyncio
import aiohttp
import json
import logging
import time
import sys
import json

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

async def stream_aircraft(watchdog, airspace, host, port):
    reader, writer = await asyncio.open_connection(host, port)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                plane = json.loads(line.decode().strip())
                await process_aircraft_details(airspace, {
                    'aircraft' : [plane],
                })
                await airspace.vacuum()
                await watchdog.ack()
            except json.JSONDecodeError:
                logging.error(
                    f"Error fetching or processing aircraft details", exc_info=ex
                )
    finally:
        writer.close()
        await writer.wait_closed()

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

async def spin_plates(mode, host, port, watchdog_file):
    queue = asyncio.Queue()
    airspace = AirSpace()
    watchdog = Watchdog(watchdog_file)
    poll_task_watch = watchdog.addTask('poll', 5)

    if mode == 'stream':
        poll_json_task = asyncio.create_task(stream_aircraft(poll_task_watch, airspace, host, port))
    else:
        poll_json_task = asyncio.create_task(poll_aircraft_json(poll_task_watch, airspace, host))
        
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
    # Remove all handlers associated with the root logger object.
    logging.basicConfig(
        format="%(asctime)s %(levelname)s: %(message)s",
        level=logging.INFO,
        force=True,
    )

    import argparse
    # Create the top-level parser
    parser = argparse.ArgumentParser(description="Process some command line arguments for different modes.")
    subparsers = parser.add_subparsers(dest="mode", required=True, help="Modes of operation")
    # Create the parser for the "stream" mode
    parser_stream = subparsers.add_parser('stream', help='Stream mode settings')
    parser_stream.add_argument('--host', type=str, required=True, help='Host address')
    parser_stream.add_argument('--port', type=int, required=True, help='Port number')
    # Create the parser for the "tar1090" mode
    parser_tar1090 = subparsers.add_parser('tar1090', help='Tar1090 mode settings')
    parser_tar1090.add_argument('--host', type=str, required=True, help='Host URL')
    # Add an optional watchdog argument applicable to all modes
    parser.add_argument('--watchdog', type=str, help='File path to watchdog device', required=False)
    # Parse the arguments
    args = parser.parse_args()

    # Don't watchdog if there's a network adapter connected
    watchdog = args.watchdog
    try:
        if watchdog and open("/sys/class/net/eth0/operstate").read().strip() == 'up':
            logging.info("Ethernet connected so watchdog disabled")
            watchdog = None
    except:
        pass

    asyncio.run(spin_plates(args.mode, args.host, args.port, watchdog))
