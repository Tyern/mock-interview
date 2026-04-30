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

   brew install mysql
   #---
   mysql -u root -p
   CREATE DATABASE interview_app;

   USE interview_app;

   CREATE TABLE candidates (
      id VARCHAR(64) PRIMARY KEY,
      name VARCHAR(255),
      department VARCHAR(100),
      institution_name VARCHAR(100),
      cv_path TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );

   CREATE TABLE IF NOT EXISTS interview_evaluations (
      user_id VARCHAR(255) NOT NULL PRIMARY KEY,
      overall_score INT,
      communication_score INT,
      technical_score INT,
      confidence_score INT,
      summary TEXT,
      strengths JSON,
      areas_for_improvement JSON,
      recommendation ENUM('hire', 'consider', 'reject'),
      created_at DATETIME
   );
   ```

3. Run dev server:
   ```
   uv run server.py
   ```

# Deploy

## Docker
```
# docker build -t mock-interview .
# docker run  -p 7860:7860 --env-file .env mock-interview

docker buildx build --platform linux/amd64 -t tyern/mock-interview:v2 --push .
```

## Modal
```

modal secret create secrets DAILY_API_KEY=... GOOGLE_API_KEY=...
modal deploy server_modal.py
```

- Add .env.production
- In your client directory `cd ../client/react` , install Vercel's CLI tool: `npm install -g vercel`
- Verify it's installed using `vercel --version`
- Log in your Vercel account using `vercel login`
- Deploy your client to Vercel using `vercel`


# TODO
- PDF upload and load to context                  5/10 *
- Language interchange                            5/10
- Score the user answer                           0/10
- Integration                                     10/10
- Web search tool                                 10/10

