#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import asyncio
import os
import sys
import argparse
import json

import aiohttp
from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecatcloud.agent import DailySessionArguments


import os
import argparse
import asyncio
import aiohttp

from dotenv import load_dotenv
from loguru import logger
from PIL import Image
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    LLMRunFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frameworks.rtvi import RTVIObserver, RTVIProcessor
from pipecat.runner.types import DailyRunnerArguments, RunnerArguments, SmallWebRTCRunnerArguments
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.services.tavus.video import TavusVideoService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pdf_helper import get_pdf_context
from ta_helper import quiet_frame, talking_frame, TalkingAnimation
from prompt_helper import prompt_dict
from google.genai import types
import mysql.connector

# from bot_gemini import run_bot as main

load_dotenv(override=True)
TAVUS = False

parser = argparse.ArgumentParser()
parser.add_argument("-b", "--body", type=str, default="{}")
args, _ = parser.parse_known_args()
body = json.loads(args.body)
user_id = body.get("user_id")
lang = body.get("lang")
sys_prompt, next_question_prompt, message_prompt = prompt_dict[lang]

# Check if we're in local development mode
# LOCAL = os.getenv("LOCAL_RUN")

logger.remove()
logger.add(sys.stderr, level="DEBUG")


sprites = []
script_dir = os.path.dirname(__file__)

def summarize_answer(text: str) -> str:
    return text[:200]  # replace with smarter logic

def merge_summaries(old: str, new: str) -> str:
    if not old:
        return new
    return old + " | " + new


def load_candidate_data(user_id):

    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "password"),
        database=os.getenv("MYSQL_DB", "interview_app"),
    )

    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        "SELECT * FROM candidates WHERE id=%s",
        (user_id,)
    )

    data = cursor.fetchone()

    cursor.close()
    conn.close()

    return data

class InterviewState:
    def __init__(self):
        self.question_index = 0
        self.scores = []
        self.weaknesses = []

class InterviewMemory:
    def __init__(self):
        self.summary = ""
        
class InterviewController:
    def __init__(self, state: InterviewState, memory: InterviewMemory):
        self.state = state
        self.memory = memory

    def build_system_prompt(self) -> str:
        return (
            sys_prompt + \
            f"Interview state:\n"
            f"- Question index: {self.state.question_index}\n"
            f"- Scores: {self.state.scores}\n"
            f"- Weaknesses: {', '.join(self.state.weaknesses)}\n\n"
            f"Interview summary so far:\n"
            f"{self.memory.summary}\n"
        )

    def next_question(self) -> str:
        questions = next_question_prompt
        return questions[self.state.question_index % len(questions)]
    
def evaluate_answer(text: str) -> float:
    if len(text.split()) < 20:
        return 0.3
    if "because" in text.lower():
        return 0.7
    return 0.5
        
state = InterviewState()
memory = InterviewMemory()
controller = InterviewController(state, memory)

async def run_bot(transport: BaseTransport, user_id: str, lang: str):
    """Main bot execution function.

    Sets up and runs the bot pipeline including:
    - Gemini Live model integration
    - Voice activity detection
    - Animation processing
    - RTVI event handling
    """
    logger.info(f"Running bot for user_id={user_id}, lang={lang}")
    candidate = load_candidate_data(user_id)
    
    # Initialize the Gemini Live model
    async with aiohttp.ClientSession() as session:

        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        llm = GeminiLiveLLMService(
            api_key=os.getenv("GOOGLE_API_KEY"),
            voice_id="Charon" if not TAVUS else "Aoede",  # Aoede, Charon, Fenrir, Kore, Puck
            tools=[grounding_tool],
        )
        if TAVUS:
            ta = TavusVideoService(
                api_key=os.getenv("TAVUS_API_KEY"),
                replica_id=os.getenv("TAVUS_REPLICA_ID"),
                session=session
            )
        else:
            ta = TalkingAnimation()
            
        cv_text = get_pdf_context(candidate["cv_path"])
        
        messages = [
            {
                "role": "user",
                "content": message_prompt
            }, {
                "role": "system",
                "content": cv_text
            }, 
            {
                "role": "system",# TODO
                "content": f"""
    Candidate Information:
    Name: {candidate["name"]}
    Department: {candidate["department"]}
    Institution Name: {candidate["institution_name"]}
    """
            }
        ]

        # Set up conversation context and management
        # The context_aggregator will automatically collect conversation context
        context = LLMContext(messages)
        context_aggregator = LLMContextAggregatorPair(context)

        rtvi = RTVIProcessor()

        # Pipeline - assembled from reusable components
        pipeline = Pipeline(
            [
                transport.input(),
                rtvi,
                context_aggregator.user(),
                llm,
                ta,
                transport.output(),
                # context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=[
                RTVIObserver(rtvi),
            ],
        )

        # # Queue initial static frame so video starts immediately
        # await task.queue_frame(quiet_frame)

        @rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi):
            logger.info("on_client_ready")
            
            await rtvi.set_bot_ready()
            # Kick off the conversation
            await task.queue_frames([LLMRunFrame()])

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Client connected")

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Client disconnected")
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False)

        await runner.run(task)

async def bot(args: DailySessionArguments):
    """Main bot entry point compatible with the FastAPI route handler.

    Args:
        room_url: The Daily room URL
        token: The Daily room token
        body: The configuration object from the request body
        session_id: The session ID for logging
    """
    from pipecat.audio.filters.krisp_filter import KrispFilter

    logger.info(f"Bot process initialized {args.room_url} {args.token}")
    logger.info(f"Running bot for user {user_id}")
    
    async with aiohttp.ClientSession() as session:
        transport = DailyTransport(
            args.room_url,
            args.token,
            "Smart Turn Bot",
            params=DailyParams(
                audio_in_enabled=True,
                audio_in_filter=KrispFilter(),
                audio_out_enabled=True,
                video_out_enabled=True,
                video_out_width=1024,
                video_out_height=576,
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                turn_analyzer=LocalSmartTurnAnalyzerV3(),
            ),
        )

        try:
            await run_bot(transport, user_id, lang)
            logger.info("Bot process completed")
        except Exception as e:
            logger.exception(f"Error in bot process: {str(e)}")
            raise


# Local development
async def local_daily():
    """Daily transport for local development."""
    from runner import configure

    try:
        async with aiohttp.ClientSession() as session:
            room_url, token = await configure(session)
            logger.info(f"Starting local bot with room_url={room_url}, token={token}, user_id={user_id}")
                
            transport = DailyTransport(
                room_url,
                token,
                "Smart Turn Bot",
                params=DailyParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    video_out_enabled=True,
                    video_out_width=1024,
                    video_out_height=576,
                    vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                    turn_analyzer=LocalSmartTurnAnalyzerV3(),
                ),
            )

            await run_bot(transport, user_id, lang)
    except Exception as e:
        logger.exception(f"Error in local development mode: {e}")


# Local development entry point
if __name__ == "__main__":
    try:
        asyncio.run(local_daily())
    except Exception as e:
        logger.exception(f"Failed to run in local mode: {e}")
