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
import modal

# Load env
load_dotenv(override=True)

# ---------- Modal App ----------
app = modal.App("rtvi-bot-server")

image = (
    modal.Image.from_registry("tyern/mock-interview:v2")
    .pip_install(
        'aenum==3.1.16\naiofiles==24.1.0\naiohappyeyeballs==2.6.1\naiohttp==3.13.2\naioice==0.10.2\naiortc==1.14.0\naiosignal==1.4.0\nannotated-doc==0.0.4\nannotated-types==0.7.0\nanyio==4.12.0\nattrs==25.4.0\nav==16.0.1\ncachetools==6.2.4\ncartesia==2.0.17\ncertifi==2025.11.12\ncffi==2.0.0\ncharset-normalizer==3.4.4\nclick==8.3.1\ncoloredlogs==15.0.1\ncryptography==46.0.3\ndaily-python==0.22.0\ndataclasses-json==0.6.7\ndeepgram-sdk==4.7.0\ndeprecation==2.1.0\ndistro==1.9.0\ndnspython==2.8.0\ndocstring-parser==0.17.0\nemail-validator==2.3.0\nfastapi==0.121.3\nfastapi-cli==0.0.20\nfastapi-cloud-cli==0.8.0\nfastar==0.8.0\nfilelock==3.20.1\nflatbuffers==25.12.19\nfrozenlist==1.8.0\nfsspec==2025.12.0\nfuture==1.0.0\ngoogle-api-core==2.25.2\ngoogle-auth==2.45.0\ngoogle-cloud-speech==2.35.0\ngoogle-cloud-texttospeech==2.33.0\ngoogle-crc32c==1.8.0\ngoogle-genai==1.56.0\ngoogleapis-common-protos==1.72.0\ngrpcio==1.76.0\ngrpcio-status==1.71.2\nh11==0.16.0\nhf-xet==1.2.0\nhttpcore==1.0.9\nhttptools==0.7.1\nhttpx==0.28.1\nhttpx-sse==0.4.0\nhuggingface-hub==0.36.0\nhumanfriendly==10.0\nidna==3.11\nifaddr==0.2.0\niterators==0.2.0\nitsdangerous==2.2.0\njinja2==3.1.6\njiter==0.12.0\njoblib==1.5.3\nllvmlite==0.44.0\nloguru==0.7.3\nmarkdown==3.10\nmarkdown-it-py==4.0.0\nmarkupsafe==3.0.3\nmarshmallow==3.26.2\nmdurl==0.1.2\nmpmath==1.3.0\nmultidict==6.7.0\nmypy-extensions==1.1.0\nnltk==3.9.2\nnodeenv==1.10.0\nnumba==0.61.2\nnumpy==2.2.6\nonnxruntime==1.23.2\nopenai==2.14.0\nopencv-python==4.12.0.88\norjson==3.11.5\npackaging==25.0\npillow==11.3.0\npipecat-ai==0.0.98\npipecat-ai-small-webrtc-prebuilt==2.0.0\npipecatcloud==0.2.16\nprompt-toolkit==3.0.52\npropcache==0.4.1\nproto-plus==1.27.0\nprotobuf==5.29.5\npyasn1==0.6.1\npyasn1-modules==0.4.2\npycparser==2.23\npydantic==2.12.5\npydantic-core==2.41.5\npydantic-extra-types==2.10.6\npydantic-settings==2.12.0\npydub==0.25.1\npyee==13.0.0\npygments==2.19.2\npylibsrtp==1.0.0\npyloudnorm==0.1.1\npyopenssl==25.3.0\npypdf==6.5.0\npyright==1.1.407\npython-dotenv==1.2.1\npython-multipart==0.0.21\npyyaml==6.0.3\nquestionary==2.1.1\nregex==2025.11.3\nrequests==2.32.5\nresampy==0.4.3\nrich==14.2.0\nrich-toolkit==0.17.1\nrignore==0.7.6\nrsa==4.9.1\nruff==0.14.10\nsafetensors==0.7.0\nscipy==1.16.3\nsentry-sdk==2.48.0\nshellingham==1.5.4\nsigtools==4.0.1\nsniffio==1.3.1\nsoxr==0.5.0.post1\nstarlette==0.50.0\nsympy==1.14.0\nsynchronicity==0.7.7\ntenacity==9.1.2\ntokenizers==0.22.1\ntoml==0.10.2\ntqdm==4.67.1\ntransformers==4.57.3\ntyper==0.20.1\ntyping-extensions==4.15.0\ntyping-inspect==0.9.0\ntyping-inspection==0.4.2\nujson==5.11.0\nurllib3==2.6.2\nuvicorn==0.40.0\nuvloop==0.22.1\nwait-for2==0.4.1\nwatchfiles==1.1.1\nwcwidth==0.2.14\nwebsockets==15.0.1\nyarl==1.22.0'.split("\n")
    )
    .add_local_dir(".", "/root", copy=True, ignore=[".env", "__pycache__", "*.pyc"])
)

# ---------- Globals ----------
MAX_BOTS_PER_ROOM = 1
bot_procs = {}
daily_helpers = {}

# ---------- Lifespan ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    aiohttp_session = aiohttp.ClientSession()
    daily_helpers["rest"] = DailyRESTHelper(
        daily_api_key=os.getenv("DAILY_API_KEY", ""),
        daily_api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
        aiohttp_session=aiohttp_session,
    )
    yield
    await aiohttp_session.close()
    # terminate all bot processes on shutdown
    for entry in bot_procs.values():
        proc = entry[0]
        proc.terminate()
        proc.wait()

# ---------- FastAPI App ----------
fastapi_app = FastAPI(lifespan=lifespan)

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Routes ----------
async def create_room_and_token() -> tuple[str, str]:
    room = await daily_helpers["rest"].create_room(DailyRoomParams())
    if not room.url:
        raise HTTPException(status_code=500, detail="Failed to create room")
    token = await daily_helpers["rest"].get_token(room.url)
    if not token:
        raise HTTPException(status_code=500, detail=f"Failed to get token for room: {room.url}")
    return room.url, token

@fastapi_app.get("/")
async def start_agent(request: Request):
    room_url, token = await create_room_and_token()
    num_bots_in_room = sum(
        1 for proc in bot_procs.values() if proc[1] == room_url and proc[0].poll() is None
    )
    if num_bots_in_room >= MAX_BOTS_PER_ROOM:
        raise HTTPException(status_code=500, detail=f"Max bot limit reached for room: {room_url}")
    # Spawn a new bot process
    try:
        proc = subprocess.Popen(
            [f"python3 bot.py -u {room_url} -t {token}"],
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")
    return RedirectResponse(room_url)

@fastapi_app.post("/connect")
async def rtvi_connect(request: Request) -> Dict[Any, Any]:
    room_url, token = await create_room_and_token()
    try:
        proc = subprocess.Popen(
            [f"python3 -m bot -u {room_url} -t {token}"],
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")
    return {"room_url": room_url, "token": token}

@fastapi_app.get("/status/{pid}")
def get_status(pid: int):
    proc = bot_procs.get(pid)
    if not proc:
        raise HTTPException(status_code=404, detail=f"Bot with process id: {pid} not found")
    status = "running" if proc[0].poll() is None else "finished"
    return JSONResponse({"bot_id": pid, "status": status})

# ---------- Expose FastAPI on Modal ----------
# @app.function(secrets=[modal.Secret.from_name("secrets")])    
@app.function(image=image, 
              secrets=[modal.Secret.from_name("secrets")], 
            #   include_files=["server_modal.py", "bot.py", "prompt_helper.py", "pdf_helper.py", "bot_gemini.py", "ta_helper.py"]
            )
@modal.asgi_app()
def fastapi_entry():
    return fastapi_app