import asyncio
import aiohttp
import json

async def fetch_aircraft_details(session, url):
    async with session.get(url) as response:
        # Assuming the server returns a JSON response
        response_json = await response.json()
        return response_json

async def process_aircraft_details(aircraft_details):
    # Process the aircraft details here
    # This is a placeholder function to demonstrate processing
    print(json.dumps(aircraft_details, indent=2))

async def poll_aircraft_json(url, interval=1):
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                aircraft_details = await fetch_aircraft_details(session, url)
                await process_aircraft_details(aircraft_details)
            except Exception as e:
                print(f"Error fetching or processing aircraft details: {e}")
            await asyncio.sleep(interval)

if __name__ == "__main__":
    # URL of the aircraft.json file in the tar1090 project
    url = "http://raspberrypi:8504/tar1090/data/aircraft.json"
    interval = 1  # Polling interval in seconds

    asyncio.run(poll_aircraft_json(url, interval))
