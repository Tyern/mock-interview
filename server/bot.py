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
from bot_gemini import run_bot as main

load_dotenv(override=True)

parser = argparse.ArgumentParser()
parser.add_argument("-b", "--body", type=str, default="{}")
args, _ = parser.parse_known_args()
body = json.loads(args.body)
user_id = body.get("user_id")

# Check if we're in local development mode
# LOCAL = os.getenv("LOCAL_RUN")

logger.remove()
logger.add(sys.stderr, level="DEBUG")

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
            await main(transport, user_id)
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

            await main(transport, user_id)
    except Exception as e:
        logger.exception(f"Error in local development mode: {e}")


# Local development entry point
if __name__ == "__main__":
    try:
        asyncio.run(local_daily())
    except Exception as e:
        logger.exception(f"Failed to run in local mode: {e}")
