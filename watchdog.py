import asyncio
import logging
from time import time

WATCHDOG_CHECK_PERIOD = 1

class WatchdogTask:
    def __init__(self, name, interval):
        self.name = name
        self.interval = interval
        self.last_seen_lock = asyncio.Lock()
        self.last_seen = time()
    async def ack(self):
        async with self.last_seen_lock:
            self.last_seen = time()
    async def healthy(self):
        async with self.last_seen_lock:
            if time() > self.last_seen + self.interval:
                logging.info("Watchdog Task unhealthy: " + self.name)
                return False
            return True

class Watchdog:
    def __init__(self, watchdog_file):
        self.tasks = []
        self.watchdog_file = watchdog_file
    def addTask(self, name, interval):
        t = WatchdogTask(name, interval)
        self.tasks.append(t)
        return t
    async def monitor(self):
        async def healthy():
            return all(await asyncio.gather(*[t.healthy() for t in self.tasks]))

        if self.watchdog_file != None:
            logging.info("Opening watchdog: " + self.watchdog_file)
            with open(self.watchdog_file, "wt") as f:
                while True:
                    if await healthy():
                        # Looking good, keep the watchdog happy
                        f.write("X\n")
                        f.flush()
                    else:
                        logging.error("Tasks STALE, not updating watchdog")
                    await asyncio.sleep(WATCHDOG_CHECK_PERIOD)
        else:
            logging.info("No watchdog enabled")
            while True:
                if not await healthy():
                    logging.error("Tasks STALE")
                await asyncio.sleep(WATCHDOG_CHECK_PERIOD)
