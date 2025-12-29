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

TAVUS = False

load_dotenv(override=True)

sprites = []
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
                "content":  
                    "Bạn là người phỏng vấn thử."
                    "Đánh giá câu trả lời xem có phù hợp chưa."
                    "Trước tiên hỏi ứng viên giới thiệu bản thân, và tăng dần độ khó."
                    "Sử dụng CV của ứng viên để định hướng việc lựa chọn câu hỏi."
                    "Về các dự án, kỹ năng và những quyết định được đề cập trong CV."
                    "Đánh giá khả năng hiểu và lập luận, không kiểm tra khả năng ghi nhớ."
                    "Không đọc lại nội dung CV thành tiếng. Không đưa ra gợi ý."
                    "Hỏi từng câu hỏi một, bằng tiếng Việt."
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
        
        # @rtvi.event_handler("before_llm_run")
        # async def inject_state(rtvi):
        #     logger.info("inject_state")
            
        #     context.messages = context.messages[-6:]  # keep last 3 turns
        #     # Remove old state injections
        #     context.messages = [
        #         m for m in context.messages if m.get("role") != "system_state"
        #     ]

        #     # Inject structured state
        #     context.messages.append({
        #         "role": "system",
        #         "name": "system_state",
        #         "content": (
        #             "Interview state:\n"
        #             f"- Question index: {interview_state['question_index']}\n"
        #             f"- Previous score: {interview_state['previous_score']}\n"
        #             f"- Weaknesses: {', '.join(interview_state['weaknesses'])}\n"
        #         )
        #     })
            
        # @rtvi.event_handler("on_llm_response")
        # async def on_llm_response(rtvi, text):
        #     logger.info("on_llm_response")
        #     score = 0.5  # TODO: your logic
        #     interview_state["scores"].append(score)
                
        #     summary = summarize_answer(text)

        #     interview_memory["summary"] = merge_summaries(
        #         interview_memory["summary"],
        #         summary,
        #     )

        #     interview_memory["question_index"] += 1
            
        # @rtvi.event_handler("before_llm_run")
        # async def rebuild_context(rtvi):
        #     logger.info("rebuild_context")
        #     context.messages = [
        #         {
        #             "role": "system",
        #             "content": (
        #                 "Bạn là người phỏng vấn thử nghiêm khắc."
        #                 "Hãy đặt từng câu hỏi một."
        #                 "Không đưa ra gợi ý."
        #                 "Đánh giá câu trả lời xem có phù hợp chưa."
        #             )
        #         },
        #         {
        #             "role": "system",
        #             "content": (
        #                 f"Interview summary so far: "
        #                 f"{interview_memory['summary']}"
        #             ),
        #         },
        #         {
        #             "role": "system",
        #             "content": (
        #                 f"Current question index: "
        #                 f"{interview_memory['question_index']}"
        #             ),
        #         },
        #         {
        #             "role": "system",
        #             "content": (
        #                 f"Interview state: "
        #                 f"question={interview_state['question_index']}, "
        #                 f"scores={interview_state['scores']}"
        #             )
        #         }
        #     ]

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            logger.info("Client connected")

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info("Client disconnected")
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False)

        await runner.run(task)

