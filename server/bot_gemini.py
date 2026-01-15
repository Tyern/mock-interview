# TODO:
# -> Control the initial system context (easy, recommended) ⭕️
# -> Manually edit context before each LLM call (important) ⭕️
# -> Inject structured state instead of raw conversation (very important) ⭕️
# -> Stop auto-aggregating assistant responses (advanced) ⭕️
# -> Replace conversation memory with summaries (recommended) ⭕️
# -> Hard control: custom LLMContext logic (expert) ❌

#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""simple-chatbot - Pipecat Voice Agent

This module implements a chatbot using Google's Gemini Live model for natural language
processing. It includes:
- Real-time audio/video interaction through Daily
- Animated robot avatar

The bot runs as part of a pipeline that processes audio/video frames and manages
the conversation flow.

Required AI services:
- Gemini Live (LLM)

Run the bot using::

    uv run bot.py
"""

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

LANG = 'ja'
sys_prompt, next_question_prompt, message_prompt = prompt_dict[LANG]
TAVUS = False

load_dotenv(override=True)

sprites = []
script_dir = os.path.dirname(__file__)

def summarize_answer(text: str) -> str:
    return text[:200]  # replace with smarter logic

def merge_summaries(old: str, new: str) -> str:
    if not old:
        return new
    return old + " | " + new

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

async def run_bot(transport: BaseTransport):
    """Main bot execution function.

    Sets up and runs the bot pipeline including:
    - Gemini Live model integration
    - Voice activity detection
    - Animation processing
    - RTVI event handling
    """

    # Initialize the Gemini Live model
    async with aiohttp.ClientSession() as session:
        llm = GeminiLiveLLMService(
            api_key=os.getenv("GOOGLE_API_KEY"),
            voice_id="Charon" if not TAVUS else "Aoede",  # Aoede, Charon, Fenrir, Kore, Puck
        )
        if TAVUS:
            ta = TavusVideoService(
                api_key=os.getenv("TAVUS_API_KEY"),
                replica_id=os.getenv("TAVUS_REPLICA_ID"),
                session=session
            )
        else:
            ta = TalkingAnimation()
        
        messages = [
            {
                "role": "user",
                "content": message_prompt
            }, {
                "role": "system",
                "content": get_pdf_context("assets/siboudouki-sample.pdf") # TODO
            }, 
            {
                "role": "system",# TODO
                "content": f"""
    University Information:
    - University: Nagoya University
    - Program: AI
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

