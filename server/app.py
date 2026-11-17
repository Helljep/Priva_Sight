"""
app.py - PrivaSight planner server (FastAPI).

    python -m uvicorn app:app --host 127.0.0.1 --port 8787

Environment:
    PRIVASIGHT_BACKEND   scripted (default) | ollama
    OLLAMA_URL           default http://127.0.0.1:11434
    OLLAMA_MODEL         default qwen3-vl:2b   (or the name of your LoRA-merged model)

What this server guarantees:
  1. Every request is scanned for raw structured PII. If any is found the
     request is rejected (422) BEFORE it reaches the model and is not logged.
  2. The model is prompted knowing the screen is sanitised (prompts.py).
  3. Nothing is stored. Only counters are kept for /health.
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from gateway import router as gateway_router
from pii import scan_payload
from planner import make_planner
from schemas import PlanRequest, PlanResponse

BACKEND = os.environ.get('PRIVASIGHT_BACKEND', 'scripted')
planner = make_planner(
    BACKEND,
    **({'base_url': os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434'),
        'model': os.environ.get('OLLAMA_MODEL', 'qwen3-vl:2b')} if BACKEND == 'ollama' else {}),
)

app = FastAPI(title='PrivaSight planner', version='1.0.0')
# The extension calls from a chrome-extension:// origin.
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

app.include_router(gateway_router)   # /agent/* and /bridge for external agents (see gateway.py)

counters = {'accepted': 0, 'rejected_pii': 0}

# EVALUATION ONLY. Turns the server-side PII rejection off so the "unsafe
# baseline" experiment can measure what a naive server would have received.
# Never set this in real use; /health reports it so it cannot go unnoticed.
PII_CHECK = os.environ.get('PRIVASIGHT_UNSAFE_NO_PII_CHECK') != '1'


@app.get('/health')
def health():
    return {'ok': True, 'backend': getattr(planner, 'name', BACKEND), 'pii_check': PII_CHECK, **counters}


@app.post('/plan', response_model=PlanResponse)
def plan(req: PlanRequest):
    hits = scan_payload(req.model_dump()) if PII_CHECK else []
    if hits:
        counters['rejected_pii'] += 1
        # Report only the TYPE and a masked sample, never the raw value.
        raise HTTPException(status_code=422, detail={'error': 'raw PII in payload', 'findings': hits[:10]})
    counters['accepted'] += 1
    return planner.plan(req)
