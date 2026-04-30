#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""RTVI Bot Server Implementation.

This FastAPI server manages RTVI bot instances and provides endpoints for both
direct browser access and RTVI client connections. It handles:
- Creating Daily rooms
- Managing bot processes
- Providing connection credentials
- Monitoring bot status

Requirements:
- Daily API key (set in .env file)
- Python 3.10+
- FastAPI
- Running bot implementation
"""

import argparse
import os
import subprocess
from contextlib import asynccontextmanager
from typing import Any, Dict

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pipecat.transports.daily.utils import DailyRESTHelper, DailyRoomParams
from fastapi import UploadFile, File, Form
from pydantic import BaseModel
import shutil
import uuid
from typing import Optional, List


# Load environment variables from .env file
load_dotenv(override=True)

# Maximum number of bot instances allowed per room
MAX_BOTS_PER_ROOM = 1

# Dictionary to track bot processes: {pid: (process, room_url)}
bot_procs = {}

# Store Daily API helpers
daily_helpers = {}

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
        
import mysql.connector

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "password"),
        database=os.getenv("MYSQL_DB", "interview_app")
    )
    
class CandidateInfo(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    institution_name: Optional[str] = None

class ConnectRequest(BaseModel):
    user_id: str
    lang: str | None = None

def cleanup():
    """Cleanup function to terminate all bot processes.

    Called during server shutdown.
    """
    for entry in bot_procs.values():
        proc = entry[0]
        proc.terminate()
        proc.wait()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager that handles startup and shutdown tasks.

    - Creates aiohttp session
    - Initializes Daily API helper
    - Cleans up resources on shutdown
    """
    aiohttp_session = aiohttp.ClientSession()
    daily_helpers["rest"] = DailyRESTHelper(
        daily_api_key=os.getenv("DAILY_API_KEY", ""),
        daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
        aiohttp_session=aiohttp_session,
    )
    yield
    await aiohttp_session.close()
    cleanup()


# Initialize FastAPI app with lifespan manager
fastapi_app = FastAPI(lifespan=lifespan)

# Configure CORS to allow requests from any origin
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def create_room_and_token() -> tuple[str, str]:
    """Helper function to create a Daily room and generate an access token.

    Returns:
        tuple[str, str]: A tuple containing (room_url, token)

    Raises:
        HTTPException: If room creation or token generation fails
    """
    room = await daily_helpers["rest"].create_room(DailyRoomParams())
    if not room.url:
        raise HTTPException(status_code=500, detail="Failed to create room")

    token = await daily_helpers["rest"].get_token(room.url)
    if not token:
        raise HTTPException(status_code=500, detail=f"Failed to get token for room: {room.url}")

    return room.url, token


# @fastapi_app.get("/")
# async def start_agent(request: Request):
#     """Endpoint for direct browser access to the bot.

#     Creates a room, starts a bot instance, and redirects to the Daily room URL.

#     Returns:
#         RedirectResponse: Redirects to the Daily room URL

#     Raises:
#         HTTPException: If room creation, token generation, or bot startup fails
#     """
#     print("Creating room")
#     room_url, token = await create_room_and_token()
#     print(f"Room URL: {room_url}")

#     # Check if there is already an existing process running in this room
#     num_bots_in_room = sum(
#         1 for proc in bot_procs.values() if proc[1] == room_url and proc[0].poll() is None
#     )
#     if num_bots_in_room >= MAX_BOTS_PER_ROOM:
#         raise HTTPException(status_code=500, detail=f"Max bot limit reached for room: {room_url}")

#     # Spawn a new bot process
#     try:
#         proc = subprocess.Popen(
#             [f"python3 bot.py -u {room_url} -t {token}"],
#             shell=True,
#             bufsize=1,
#             cwd=os.path.dirname(os.path.abspath(__file__)),
#         )
#         bot_procs[proc.pid] = (proc, room_url)
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

#     return RedirectResponse(room_url)


@fastapi_app.post("/connect")
async def rtvi_connect(req: ConnectRequest) -> Dict[Any, Any]:
    """RTVI connect endpoint that creates a room and returns connection credentials.

    This endpoint is called by RTVI clients to establish a connection.

    Returns:
        Dict[Any, Any]: Authentication bundle containing room_url and token

    Raises:
        HTTPException: If room creation, token generation, or bot startup fails
    """
    user_id = req.user_id
    lang = req.lang
    if lang is None:
        lang = "vi"
    
    print("Creating room for RTVI connection")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Start the bot process
    try:
        proc = subprocess.Popen(
            [f"python3 bot.py -u {room_url} -t {token} -b '{{\"user_id\":\"{user_id}\", \"lang\":\"{lang}\"}}'"],
            # ["python3",
            #     "-m", "bot",
            #     "-u", room_url,
            #     "-t", token,
            #     "-b", f'{{"user_id":"{req.user_id}"}}'
            # ],
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[user_id] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    # Return the authentication bundle in format expected by DailyTransport
    return {"room_url": room_url, "token": token}


@fastapi_app.get("/status/{user_id}")
def get_status(user_id: str):
    """Get the status of a specific bot process.

    Args:
        user_id (str): user id

    Returns:
        JSONResponse: Status information for the bot

    Raises:
        HTTPException: If the specified bot process is not found
    """
    # Look up the subprocess
    proc = bot_procs.get(user_id)

    # If the subprocess doesn't exist, return an error
    if not proc:
        raise HTTPException(status_code=404, detail=f"Bot with process user_id: {user_id} not found")

    # Check the status of the subprocess
    status = "running" if proc[0].poll() is None else "finished"
    return JSONResponse({"user_id": user_id, "status": status})


# Upload CV and interview info endpoint implementation

@fastapi_app.post("/upload_cv")
async def upload_cv(
    user_id: str = Form(...),
    file: UploadFile = File(...)
):

    try:
        ext = file.filename.split(".")[-1]
        filename = f"{uuid.uuid4()}.{ext}"
        path = os.path.join(UPLOAD_DIR, filename)

        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO candidates (id, cv_path)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE cv_path=%s
            """,
            (user_id, path, path),
        )

        conn.commit()

        cursor.close()
        conn.close()

        return {
            "status": "success",
            "user_id": user_id,
            "cv_path": path,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@fastapi_app.post("/new_candidate")
async def new_candidate(info: CandidateInfo):

    conn = get_db_connection()
    cursor = conn.cursor()

    user_id = uuid.uuid4().hex
    cursor.execute(
        """
        INSERT INTO candidates (id, name, department, institution_name)
        VALUES (%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            name=%s,
            department=%s,
            institution_name=%s
        """,
        (
            user_id,
            info.name,
            info.department,
            info.institution_name,
            info.name,
            info.department,
            info.institution_name,
        ),
    )

    conn.commit()

    cursor.close()
    conn.close()

    return {"status": "updated", "user_id": user_id}

@fastapi_app.get("/candidate/{user_id}")
async def get_candidate(user_id: str):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM candidates WHERE id=%s",
        (user_id,),
    )

    result = cursor.fetchone()

    cursor.close()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="User not found")

    return result
    
if __name__ == "__main__":
    import uvicorn

    # Parse command line arguments for server configuration
    default_host = os.getenv("HOST", "0.0.0.0")
    default_port = int(os.getenv("FAST_API_PORT", "7860"))

    parser = argparse.ArgumentParser(description="Daily Storyteller FastAPI server")
    parser.add_argument("--host", type=str, default=default_host, help="Host address")
    parser.add_argument("--port", type=int, default=default_port, help="Port number")
    parser.add_argument("--reload", action="store_true", help="Reload code on change")

    config = parser.parse_args()

    # Start the FastAPI server
    uvicorn.run(
        "server:fastapi_app",
        host=config.host,
        port=config.port,
        reload=config.reload,
    )
