
import time
import inspect
import math

async def run_timed(steps, args = {}):
    timings = {}
    for step in steps:
        start = time.perf_counter()
        result = step(**args)
        if inspect.isawaitable(result):
            result = await result
        end = time.perf_counter()
        timings[step.__name__] = end - start
    return timings