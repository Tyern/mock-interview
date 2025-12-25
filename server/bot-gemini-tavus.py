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

import asyncio
import aiohttp
from dotenv import load_dotenv
from loguru import logger
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

load_dotenv(override=True)

script_dir = os.path.dirname(__file__)
interview_state = {
    "question_index": 0,
    "scores": [],
    "weaknesses": [],
}
interview_memory = {
    "summary": "",
    "question_index": 0,
    "strengths": [],
    "weaknesses": [],
}

def summarize_answer(text: str) -> str:
    return text[:200]  # replace with smarter logic

def merge_summaries(old: str, new: str) -> str:
    if not old:
        return new
    return old + " | " + new

async def run_bot(transport: BaseTransport):
    """Main bot execution function.

    Sets up and runs the bot pipeline including:
    - Gemini Live model integration
    - Voice activity detection
    - Animation processing
    - RTVI event handling
    """
    async with aiohttp.ClientSession() as session:
        # Initialize the Gemini Live model
        llm = GeminiLiveLLMService(
            api_key=os.getenv("GOOGLE_API_KEY"),
            voice_id="Aoede",  # Aoede, Charon, Fenrir, Kore, Puck
        )

        tavus = TavusVideoService(
            api_key=os.getenv("TAVUS_API_KEY"),
            replica_id=os.getenv("TAVUS_REPLICA_ID"),
            session=session
        )

        messages = [
            {
                "role": "user",
                "content":  
                    "Bạn là người phỏng vấn thử."
                    "Hãy đặt từng câu hỏi một."
                    "Không đưa ra gợi ý."
                    "Đánh giá câu trả lời xem có phù hợp chưa."
            },
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
                # ta,
                tavus,
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
            idle_timeout_secs=300,
        )

        @rtvi.event_handler("on_client_ready")
        async def on_client_ready(rtvi):
            await rtvi.set_bot_ready()
            # Kick off the conversation
            await task.queue_frames([LLMRunFrame()])
        
        @rtvi.event_handler("before_llm_run")
        async def inject_state(rtvi):
            context.messages = context.messages[-6:]  # keep last 3 turns
            # Remove old state injections
            context.messages = [
                m for m in context.messages if m.get("role") != "system_state"
            ]

            # Inject structured state
            context.messages.append({
                "role": "system",
                "name": "system_state",
                "content": (
                    "Interview state:\n"
                    f"- Question index: {interview_state['question_index']}\n"
                    f"- Previous score: {interview_state['previous_score']}\n"
                    f"- Weaknesses: {', '.join(interview_state['weaknesses'])}\n"
                )
            })
            
        @rtvi.event_handler("on_llm_response")
        async def on_llm_response(rtvi, text):
            score = 0.5  # TODO: your logic
            interview_state["scores"].append(score)
                
            summary = summarize_answer(text)

            interview_memory["summary"] = merge_summaries(
                interview_memory["summary"],
                summary,
            )

            interview_memory["question_index"] += 1
            
        @rtvi.event_handler("before_llm_run")
        async def rebuild_context(rtvi):
            context.messages = [
                {
                    "role": "system",
                    "content": (
                        "Bạn là người phỏng vấn thử nghiêm khắc."
                        "Hãy đặt từng câu hỏi một."
                        "Không đưa ra gợi ý."
                        "Đánh giá câu trả lời xem có phù hợp chưa."
                    )
                },
                {
                    "role": "system",
                    "content": (
                        f"Interview summary so far: "
                        f"{interview_memory['summary']}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        f"Current question index: "
                        f"{interview_memory['question_index']}"
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        f"Interview state: "
                        f"question={interview_state['question_index']}, "
                        f"scores={interview_state['scores']}"
                    )
                }
            ]

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Client connected")

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Client disconnected")
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False)

        await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point."""

    transport = None

    match runner_args:
        case DailyRunnerArguments():
            transport = DailyTransport(
                runner_args.room_url,
                runner_args.token,
                "Pipecat Bot",
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
        case SmallWebRTCRunnerArguments():
            webrtc_connection: SmallWebRTCConnection = runner_args.webrtc_connection

            transport = SmallWebRTCTransport(
                webrtc_connection=webrtc_connection,
                params=TransportParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    video_out_enabled=True,
                    video_out_is_live=True,
                    video_out_width=1024,
                    video_out_height=576,
                            
                    # audio_in_enabled=True,
                    # audio_out_enabled=True,
                    # video_out_enabled=True,
                    # video_out_width=1024,
                    # video_out_height=576,
                    vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                    turn_analyzer=LocalSmartTurnAnalyzerV3(),
                ),
            )
        case _:
            logger.error(f"Unsupported runner arguments type: {type(runner_args)}")
            return

    await run_bot(transport)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
