import asyncio
import re
from collections import deque
from datetime import datetime

from app.dependencies import get_settings, get_state
from app.services.docker_ctl import get_container


# Ring buffer for recent logs, accessible via routers
RECENT_LOGS = deque(maxlen=500)

async def start_log_watcher():
    """Background task to tail Lavalink logs, parse errors/OAuth codes, and update state."""
    settings = get_settings()
    state = get_state()
    container_name = settings.lavalink_container_name

    # Regex patterns
    # go to https://www.google.com/device and enter code XXXX
    oauth_code_pattern = re.compile(r"enter code ([A-Z0-9-]+)")
    oauth_success_pattern = re.compile(r"OAuth integration was successful", re.IGNORECASE)
    
    # Run loop
    while True:
        try:
            # We must use docker client via async generator.
            # However docker-py's logs() is blocking when follow=True.
            # We'll run a blocking thread to yield lines queue, or since it's an async 
            # environment, we can just use `to_thread` or an executor.
            
            from app.dependencies import get_docker_client
            client = get_docker_client()
            container = client.containers.get(container_name)
            
            # Use lower level API for non-blocking stream if possible, or simple generator in a thread
            log_stream = container.logs(stream=True, follow=True, tail=100)
            
            # Since this is a simple implementation, we iterate over the blocking generator in the async loop
            # using asyncio.to_thread but per chunk.
            while True:
                # Get next chunk in a background thread to avoid blocking event loop
                chunk = await asyncio.to_thread(_get_next_chunk, log_stream)
                if not chunk:
                    break
                    
                line = chunk.decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                    
                RECENT_LOGS.append(line)
                
                # Check patterns
                match = oauth_code_pattern.search(line)
                if match:
                    code = match.group(1)
                    state.set("oauth_device_code", code)
                    state.set("oauth_timestamp", datetime.now().isoformat())
                    print(f"Log_watcher: Found OAuth code {code}")
                    
                if oauth_success_pattern.search(line):
                    state.delete("oauth_device_code")
                    state.set("oauth_success", datetime.now().isoformat())
                    print("Log_watcher: OAuth success detected")
        except Exception as e:
            print(f"Log watcher failed: {e}. Retrying in 10s...")
            await asyncio.sleep(10)

def _get_next_chunk(stream):
    try:
        return next(stream, None)
    except StopIteration:
        return None
    except Exception:
        return None
