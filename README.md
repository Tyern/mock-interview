# Simple Chatbot
Copy from [git@github.com:pipecat-ai/pipecat.git]

This repository demonstrates a simple AI chatbot with real-time audio/video interaction, implemented using different client and server options. The bot server supports multiple AI backends, and you can connect to it using five different client approaches.

# Deploy

## Docker
```
docker buildx build --platform linux/amd64 -t tyern/mock-interview:v2 --push .
```

## Modal
```
modal secret create secrets DAILY_API_KEY=... GOOGLE_API_KEY=...
modal deploy server_modal.py
```

## Client
- Add .env.production
- In your client directory `cd ../client/react` , install Vercel's CLI tool: `npm install -g vercel`
- Verify it's installed using `vercel --version`
- Log in your Vercel account using `vercel login`
- Deploy your client to Vercel using `vercel`
