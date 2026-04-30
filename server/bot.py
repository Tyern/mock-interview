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
from datetime import datetime

import aiohttp
from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecatcloud.agent import DailySessionArguments
from pipecat.frames.frames import TranscriptionFrame, TTSTextFrame, TextFrame, LLMFullResponseEndFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection

from PIL import Image
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
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, InputParams
from pipecat.services.tavus.video import TavusVideoService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams, DailyTransport
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pdf_helper import get_pdf_context
from ta_helper import quiet_frame, talking_frame, TalkingAnimation
from prompt_helper import prompt_dict
from google.genai import types, Client

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

BOT_SURVIVE_LIMIT = 660 # 11 min (s)
sprites = []
script_dir = os.path.dirname(__file__)
faq_text = get_pdf_context(os.path.join(script_dir, "assets", "STULINK_FrequentQuestions.pdf"))

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

class UserTranscriptCollector(FrameProcessor):
    def __init__(self, transcript: list):
        super().__init__()
        self._transcript = transcript

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            # User speech transcription
            logger.info(f"[User] {frame.text}")
            self._transcript.append({"role": "user", "content": frame.text})

        # Always pass the frame along
        await self.push_frame(frame, direction)
        
class LLMTranscriptCollector(FrameProcessor):
    def __init__(self, transcript: list):
        super().__init__()
        self._transcript = transcript
        self._bot_buffer = ""

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, TTSTextFrame):
            self._bot_buffer += frame.text  # accumulate, don't append yet

        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._bot_buffer:
                logger.info(f"[Bot] {self._bot_buffer}")
                self._transcript.append({"role": "bot", "content": self._bot_buffer})
                self._bot_buffer = ""  # reset for next turn

        # Always pass the frame along
        await self.push_frame(frame, direction)

async def evaluate_candidate(user_id: str, user_transcript: list, llm_transcript: list):
    if not user_transcript and not llm_transcript:
        logger.info("No transcript data to evaluate")
        return None

    # Interleave transcripts
    max_len = max(len(user_transcript), len(llm_transcript))
    conversation_lines = []
    for i in range(max_len):
        if i < len(llm_transcript):
            conversation_lines.append(f"INTERVIEWER: {llm_transcript[i]['content']}")
        if i < len(user_transcript):
            conversation_lines.append(f"CANDIDATE: {user_transcript[i]['content']}")
    
    transcript_text = "\n".join(conversation_lines)

    try:
        client = Client(api_key=os.getenv("GOOGLE_API_KEY"))
        
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"""You are an expert HR evaluator. Evaluate the following job interview transcript.

<transcript>
{transcript_text}
</transcript>

Respond ONLY with a JSON object, no markdown, no preamble:
{{
    "overall_score": <1-10>,
    "communication_score": <1-10>,
    "technical_score": <1-10>,
    "confidence_score": <1-10>,
    "summary": "<2-3 sentence summary>",
    "strengths": ["<strength 1>", "<strength 2>"],
    "areas_for_improvement": ["<area 1>", "<area 2>"],
    "recommendation": "hire" | "consider" | "reject"
}}""",
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            )
        )

        evaluation = json.loads(response.text)
        print("@@ evaluation", response.text)
        # Save to MySQL
        conn = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", "password"),
            database=os.getenv("MYSQL_DB", "interview_app"),
        )
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO interview_evaluations (
                user_id,
                overall_score,
                communication_score,
                technical_score,
                confidence_score,
                summary,
                strengths,
                areas_for_improvement,
                recommendation,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            user_id,
            evaluation.get("overall_score"),
            evaluation.get("communication_score"),
            evaluation.get("technical_score"),
            evaluation.get("confidence_score"),
            evaluation.get("summary"),
            json.dumps(evaluation.get("strengths", []), ensure_ascii=False),
            json.dumps(evaluation.get("areas_for_improvement", []), ensure_ascii=False),
            evaluation.get("recommendation"),
        ))
        conn.commit()
        logger.info(f"Evaluation saved to DB for user_id={user_id}")
        return evaluation

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        return None

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
    user_transcript = [] 
    llm_transcript = [] 
    
    # Initialize the Gemini Live model
    async with aiohttp.ClientSession() as session:

        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        llm = GeminiLiveLLMService(
            api_key=os.getenv("GOOGLE_API_KEY"),
            voice_id="Charon" if not TAVUS else "Aoede",  # Aoede, Charon, Fenrir, Kore, Puck
            tools=[grounding_tool],
            params=InputParams(
                language=lang
            )
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
            }, {
                "role": "system",
                "content": f"Frequently Asked Interview Questions:\n{faq_text}"
            }, {
                "role": "system",
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
        user_transcript_collector = UserTranscriptCollector(user_transcript)
        llm_transcript_collector = LLMTranscriptCollector(llm_transcript)

        # Pipeline - assembled from reusable components
        pipeline = Pipeline(
            [
                transport.input(),
                rtvi,
                context_aggregator.user(),
                user_transcript_collector,
                llm,
                llm_transcript_collector,
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
        await task.queue_frame(quiet_frame)

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
            logger.info("user_transcript: " + json.dumps(user_transcript))
            logger.info("llm_transcript: " + json.dumps(llm_transcript))
            await task.cancel()
            
        runner = PipelineRunner(handle_sigint=False)

        try:
            await asyncio.wait_for(runner.run(task), timeout=BOT_SURVIVE_LIMIT)
        except asyncio.TimeoutError:
            logger.info("⏰ Timeout reached. Shutting down...")
            await task.cancel()
        finally:
            logger.info("Running candidate evaluation...")
            evaluation = await evaluate_candidate(
                user_id, user_transcript, llm_transcript
            )

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
