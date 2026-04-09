# Cloover AI Sales Coach

AI sales co-pilot for Cloover installers, now with a voice roleplay training mode.

## What it does

- Takes a postal code, product interest, and optional Cloover blocks.
- Runs quality checks before anything is saved or passed to the LLM.
- Enriches missing data conservatively.
- Stores every enriched session in `knowledge_base/`.
- Generates a grounded sales briefing from the fresh, quality-checked KB.
- Supports voice roleplay with ElevenLabs when available, and a text fallback when it is not.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in ANTHROPIC_API_KEY or another supported provider key
# optionally fill in ELEVENLABS_API_KEY and CLOOVER_API_KEY
streamlit run app.py
```

## API provider selection

- If `ANTHROPIC_API_KEY` is set, the app uses Claude Sonnet via LangChain.
- Otherwise, if `GEMINI_API_KEY` is set, it uses Gemini via LangChain.
- Otherwise, if `Z_AI_API_KEY` is set, it uses the configured OpenAI-compatible endpoint such as Featherless.
- If no provider key is present, the app falls back to offline grounded output.

## Docker

Build the container:

```bash
docker build -t cloover-ai-sales-coach .
```

Run it:

```bash
docker run --rm -p 8501:8501 --env-file .env cloover-ai-sales-coach
```

The app will be available at `http://localhost:8501`.

## Railway

Live app URL:

`https://cloover-challenge-team1-production.up.railway.app`

The current repo is linked to the Railway project `cloover-challenge-team1` and deploys from the included `Dockerfile`.

## Vercel

Vercel is not a good fit for this repository in its current form.

- This app is a long-running Streamlit server.
- Vercel does not run arbitrary Docker containers for user apps.
- Vercel serverless functions are request/response oriented and are not suitable for hosting a persistent Streamlit process or a near-realtime voice loop.

If you want to deploy the current app without rewriting the runtime model, use a container-friendly host such as Render, Railway, Fly.io, or Azure App Service.

If you specifically need Vercel, the app would need to be split into:

- a separate frontend for the UI and realtime voice experience
- API routes or another backend service for enrichment and coaching
- a non-Streamlit architecture

## Voice roleplay

- `ELEVENLABS_API_KEY` enables ElevenLabs TTS output and the voice training tab.
- The app is designed to support realtime voice, but also remains runnable without it.
- If realtime transport is unavailable, the roleplay tab falls back to push-to-talk text plus TTS playback.

## Cloover blocks endpoint

The "Fetch Cloover Blocks" button is implemented as a documented placeholder/mock flow so the app remains runnable without a private endpoint.
Replace that section in `app.py` with your real endpoint once available.

## Knowledge base files

- `knowledge_base/dynamic_enrichments.json`
- `knowledge_base/regulations_knowledge.md`
- Timestamped session exports like `knowledge_base/session_YYYYMMDD_HHMMSS.md`
- Voice transcripts like `knowledge_base/voice_YYYYMMDD_HHMMSS.md`

## Notes on quality

The app follows this order strictly:

1. Gather
2. Validate quality
3. Enrich
4. Save to KB
5. Use LLM

Every session records a quality score and conservative enrichment notes.
