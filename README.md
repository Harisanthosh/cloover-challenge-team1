# SolarSage Coach

AI Sales Co-Pilot for Cloover installers, now with a voice roleplay training mode.

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
# fill in GEMINI_API_KEY or Z_AI_API_KEY
# optionally fill in ELEVENLABS_API_KEY and CLOOVER_API_KEY
streamlit run app.py
```

## API provider selection

- If `GEMINI_API_KEY` is set, the app uses Gemini via LangChain.
- Otherwise, if `Z_AI_API_KEY` is set, it uses Z.AI's OpenAI-compatible endpoint at:
  `https://api.z.ai/api/paas/v4/`
- If neither key is present, the app falls back to offline grounded output.

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
