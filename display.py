from itertools import cycle
import logging
import asyncio
from datetime import datetime

# TODO: Cleaner peer module import. Cleaner module.
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "../"))
import pyled1248

UUID = "2BD223FA-4899-1F14-EC86-ED061D67B468"
SHOW_FLIGHT_FOR = 10


async def update_display(announcement_queue):
    # Not quite sure what to do with the colors. Seems a shame to ignore them though
    colors = cycle(["red", "green", "blue", "purple", "yellow"])

    async def send_text(text):
        async with pyled1248.BLEConnection(UUID, pyled1248.handle_rx) as connection:
            await pyled1248.scroll(connection, pyled1248.SCROLL_TYPE.SCROLLLEFT)
            await pyled1248.send_text(
                connection,
                text,
                next(colors),
            )

    async def clear_display():
        something_vaguely_useful = datetime.now().strftime("%Y-%m-%d %H:%M")
        await send_text(something_vaguely_useful)

    while True:
        try:
            await clear_display()
            try:
                announcement = await asyncio.wait_for(
                    announcement_queue.get(), SHOW_FLIGHT_FOR
                )
                logging.debug(f"Announcing {announcement}")
                await send_text(announcement)
                announcement_queue.task_done()
                # Keep that flight on screen for a bit
                await asyncio.sleep(SHOW_FLIGHT_FOR)
            except asyncio.exceptions.TimeoutError:
                pass
        except Exception as ex:
            logging.error("Exception driving display", exc_info=ex)
            await asyncio.sleep(2)
