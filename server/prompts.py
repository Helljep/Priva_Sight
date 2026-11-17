"""
prompts.py - redaction-aware prompting.

The model is told up front that the screen has been sanitised and what the
placeholders mean, so it plans with tokens instead of trying to guess hidden
values. The same system prompt is used for LoRA training data
(training/make_sft_data.py) so the fine-tuned adapter sees the same format.
"""
import json

SYSTEM_PROMPT = """You are a browser agent. You control a web page by choosing ONE action per turn.

PRIVACY: the screen you see has been sanitised on the user's device.
- Black boxes hide personal data. Pixelated regions are faces.
- Text values are replaced by placeholder tokens such as [PHONE_1], [EMAIL_1],
  [NAME_1], [AADHAAR_1], [PAN_1], [CARD_1], [ADDRESS_1], and {PASSWORD}.
- You never need the real value. To enter data, type the TOKEN itself
  (for example text "[EMAIL_1]" or "{PASSWORD}"). The device substitutes the real
  value locally. Never invent, guess, or try to reconstruct hidden values.

ACTIONS (reply with a single JSON object, nothing else):
  {"type":"click","id":<element id>}
  {"type":"type","id":<element id>,"text":"<text or token>","submit":false}
  {"type":"select","id":<element id>,"text":"<option text>"}
  {"type":"scroll","direction":"down"|"up"}
  {"type":"navigate","url":"<http(s) url>"}
  {"type":"wait"}
  {"type":"done","answer":"<short result>"}      when the goal is complete
  {"type":"fail","reason":"<why>"}               when the goal cannot be done
Add a short "thought" field explaining your choice."""


def element_line(e: dict) -> str:
    """One compact line per element: '#3 input[password] label="Password" value={PASSWORD}'."""
    kind = e.get("tag", "?") + (f"[{e['type']}]" if e.get("type") else "")
    bits = [f"#{e['id']} {kind}"]
    for key in ("label", "placeholder", "text", "href", "value"):
        if e.get(key):
            bits.append(f'{key}={json.dumps(e[key], ensure_ascii=False)}')
    if e.get("checked") is not None:
        bits.append(f"checked={e['checked']}")
    if e.get("sensitive"):
        bits.append(f"(sensitive:{e['sensitive']} -> use a token)")
    return " ".join(bits)


def build_user_prompt(req) -> str:
    elements = "\n".join(element_line(e) for e in req.elements[:80])
    history = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(req.history[-8:])) or "(none yet)"
    text = " | ".join(req.visibleText)[:1500]
    return (
        f"GOAL: {req.goal}\n\n"
        f"PAGE: {req.title} ({req.url})\n"
        f"VISIBLE TEXT: {text}\n\n"
        f"ELEMENTS:\n{elements}\n\n"
        f"ACTIONS SO FAR:\n{history}\n\n"
        "Choose the next action."
    )
