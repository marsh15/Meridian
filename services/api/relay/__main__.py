import asyncio
import logging

from relay.main import main

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

asyncio.run(main())
