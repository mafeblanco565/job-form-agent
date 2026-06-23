import asyncio
import os
import sys

import uvicorn

# Playwright necesita ProactorEventLoop en Windows para lanzar subprocesos.
# uvicorn por defecto usa SelectorEventLoop, lo que causa NotImplementedError.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

port = int(os.environ.get("PORT", 8000))
uvicorn.run("web.app:app", host="0.0.0.0", port=port)
