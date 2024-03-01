from itertools import cycle
import logging
import asyncio
from datetime import datetime
import time
import pyled1248
import random

UUID = "2BD223FA-4899-1F14-EC86-ED061D67B468"
SHOW_FLIGHT_FOR = 15
UPDATE_CLOCK_EVERY = 30
HEARTBEAT_PERIOD = 1

planefacts = [x.strip() for x in open('planefacts.txt').readlines()]

async def update_display(watchdog, announcement_queue):
    # Not quite sure what to do with the colors. Seems a shame to ignore them though
    colors = cycle(["red", "green", "blue", "purple", "yellow"])

    async def send_text(connection, text):
            await pyled1248.send_text(
                connection,
                text,
                next(colors),
            )

    async def clear_display(connection):
        # Pi doesn't have an RTC!
        # something_vaguely_useful = datetime.now().strftime("%Y-%m-%d %H:%M")
        something_vaguely_useful = random.choice(planefacts)
        await send_text(connection, something_vaguely_useful)

    async def monitor_queue(watchdog):
        # Track these times (seconds since epoch)
        last_cleared = 0
        last_announced = 0
        async with pyled1248.BLEConnection(pyled1248.handle_rx) as connection:
            while True:
                now = time.time()
                # We're going to trigger the heartbeat every second
                # Driven by the queue timeout
                logging.debug("Heartbeat")
                await pyled1248.heartbeat(connection)
                # ACK the watchdog if a heartbeat has written successfully (no exception)
                await watchdog.ack()

                # Are we just spinning while an announcement is live?
                announcement_live = now < (last_announced + SHOW_FLIGHT_FOR)
                if announcement_live:
                    await asyncio.sleep(HEARTBEAT_PERIOD)
                    continue

                # Look for new things to talk about
                try:
                    announcement = await asyncio.wait_for(
                        announcement_queue.get(), HEARTBEAT_PERIOD
                    )
                    logging.debug(f"Announcing {announcement}")
                    await send_text(connection, announcement)
                    announcement_queue.task_done()
                    last_announced = now
                except asyncio.exceptions.TimeoutError:
                    # Nothing in the queue, consider updating the time
                    update_clock = now > (last_cleared + UPDATE_CLOCK_EVERY)
                    if update_clock:
                        await clear_display(connection)
                        last_cleared = now
    
    while True:
        try:
            await monitor_queue(watchdog)
        except Exception as ex:
            logging.error("Exception driving display", exc_info=ex)
            # TODO: Is there more we can do to reset the ble system?
            await asyncio.sleep(5)
