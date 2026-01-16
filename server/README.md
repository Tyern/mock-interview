# Simple Chatbot Server

A Pipecat server-side bot that connects to a Pipecat client, enabling a user to talk to the bot through their browser or mobile device.

## Setup

1. Configure environment variables

   Create a `.env` file:

   ```bash
   cp env.example .env
   ```

   Then, add your API keys:

   ```ini
   # Required API Keys
   DAILY_API_KEY=           # Your Daily API key
   OPENAI_API_KEY=          # Your OpenAI API key (required for OpenAI bot)
   GOOGLE_API_KEY=          # Your Google Gemini API key (required for Gemini bot)
   ELEVENLABS_API_KEY=      # Your ElevenLabs API key

   # Optional Configuration
   DAILY_API_URL=           # Optional: Daily API URL (defaults to https://api.daily.co/v1)
   DAILY_SAMPLE_ROOM_URL=   # Optional: Fixed room URL for development
   ```

2. Set up a virtual environment and install dependencies

   ```bash
   cd server
   uv sync

   pip install onnxruntime
   uv python pin 3.11
   rm -rf .venv
   uv sync
   ```

3. Run dev server:
   ```
   uv run server.py
   ```


# TODO
- PDF upload and load to context                  5/10 *
- Language interchange                            5/10
- Score the user answer                           0/10
- Integration                                     10/10
- Web search tool                                 10/10
