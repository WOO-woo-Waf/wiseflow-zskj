import asyncio
from insights import pipeline, pb, logger
from pathlib import Path
from dotenv import load_dotenv

# 找到上层目录（例如上一级或两级，按实际调整）
ROOT = Path(__file__).resolve().parents[2]  
load_dotenv(ROOT / ".env", override=True)

counter = 1


async def process_site(site, counter):
    if not site['per_hours'] or not site['url']:
        return
    if counter % site['per_hours'] == 0:
        logger.info(f"applying {site['url']}")
        await pipeline(
            site['url'].rstrip('/'),
            category=(site.get('category') or ""),
            within_days=int(site.get('within_days') or 30)
        )



async def schedule_pipeline(interval):
    global counter
    while True:
        sites = pb.read('sites', filter='activated=True')
        logger.info(f'task execute loop {counter}')
        await asyncio.gather(*[process_site(site, counter) for site in sites])

        counter += 1
        logger.info(f'task execute loop finished, work after {interval} seconds')
        await asyncio.sleep(interval)


async def main():
    interval_hours = 1
    interval_seconds = interval_hours * 60 * 60
    await schedule_pipeline(interval_seconds)

asyncio.run(main())
