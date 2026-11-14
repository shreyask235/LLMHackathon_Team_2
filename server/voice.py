"""Phone ordering: Twilio voice webhook. One agent session (same new_session/send_with_fallback
as the chat page) per CallSid. Twilio does speech-to-text (<Gather input="speech">) and
text-to-speech (<Say>). No extra Python packages: form bodies and the Twilio REST API use stdlib.

Twilio number -> Voice webhook (POST) -> https://<tunnel>/voice/incoming
Keys come from .env only: TWILIO_SID, TWILIO_TOKEN, TWILIO_NUMBER.
"""
import asyncio
import base64
import json
import os
import re
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape, quoteattr

from dotenv import load_dotenv
from fastapi import APIRouter, Request
from fastapi.responses import Response
from google.genai import types

router = APIRouter()
CALLS = {}  # CallSid -> {"sid": chat session id, "caller": "+1...", "texted": bool}
VOICE = os.getenv("TWILIO_VOICE", "Polly.Joanna-Neural")

PHONE_RULES = """

You are on a LIVE PHONE CALL. Your words are read aloud by text-to-speech, and the customer's words
come from speech recognition, so they may be slightly misheard: if an item name sounds close to a
menu item, use the menu item and confirm it.
- Reply in one to three short spoken sentences. No lists, bullets, markdown, emojis or symbols.
- Never read out URLs or links.
- The caller's number is already known (shown below), so just confirm it instead of asking for it.
- After confirm_order, do NOT read the pay link aloud. Say the order number and total, and that we
  just texted the secure payment link to their phone. Then say goodbye.
"""


def _main():
    from . import app as main  # late import: app.py includes this router at its bottom
    return main


def _twiml(body):
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
                    media_type="application/xml")


def _speakable(text):
    text = re.sub(r"https?://\S+", "the link we texted you", text or "")
    text = re.sub(r"[*_#`>|]", "", text)
    return escape(re.sub(r"\s+", " ", text).strip()) or "Sorry, could you say that again?"


AUDIO = {}  # id -> wav bytes made by Cartesia, served at /voice/audio/{id}.wav
_CARTESIA = {"voice": None, "off_until": 0}


def _cartesia_wav(text, rate=8000, raw=False, encoding="pcm_s16le", container="wav"):
    """Cartesia text-to-speech (used only when CARTESIA_API_KEY is in .env). None on any failure."""
    import time
    import uuid
    load_dotenv(override=True)
    key = os.getenv("CARTESIA_API_KEY")
    if not key or time.time() < _CARTESIA["off_until"]:
        return None
    hdr = {"X-API-Key": key, "Cartesia-Version": "2025-04-16", "Content-Type": "application/json"}
    try:
        voice = os.getenv("CARTESIA_VOICE") or _CARTESIA["voice"]
        if not voice:
            with urllib.request.urlopen(urllib.request.Request("https://api.cartesia.ai/voices?limit=20",
                                                               headers=hdr), timeout=5) as r:
                v = json.loads(r.read())
            v = v.get("data", v) if isinstance(v, dict) else v
            pick = next((x for x in v if x.get("language", "en") == "en"), v[0])
            voice = _CARTESIA["voice"] = pick["id"]
            print(f"[voice] Cartesia voice: {pick.get('name')} {voice}", flush=True)
        body = {"model_id": os.getenv("CARTESIA_MODEL", "sonic-3"), "transcript": text, "language": "en",
                "voice": {"mode": "id", "id": voice},
                "output_format": {"container": container, "encoding": encoding, "sample_rate": rate}}
        t0 = time.time()
        req = urllib.request.Request("https://api.cartesia.ai/tts/bytes", data=json.dumps(body).encode(),
                                     headers=hdr)
        with urllib.request.urlopen(req, timeout=6) as r:
            wav = r.read()
        if raw:
            return wav
        aid = uuid.uuid4().hex
        AUDIO[aid] = wav
        print(f"[voice] Cartesia TTS {len(wav)} bytes in {time.time() - t0:.1f}s", flush=True)
        return aid
    except Exception as e:
        print(f"[voice] Cartesia failed, using Twilio voice: {e}", flush=True)
        _CARTESIA["off_until"] = time.time() + 60
        return None


def _speak(text):
    """<Play> Cartesia audio when available, else Twilio <Say>."""
    clean = _speakable(text)
    aid = _cartesia_wav(clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    if aid:
        return f"<Play>/voice/audio/{aid}.wav</Play>"
    return f'<Say voice="{VOICE}">{clean}</Say>'


def _hints():
    """Menu item names as speech hints so Twilio hears "tacos", not "tackle"."""
    from .menus import MENUS
    names = {re.sub(r"\s*\(.*?\)", "", i["name"]) for items in MENUS.values() for i in items}
    return ", ".join(sorted(names) + ["Indian", "Italian", "Mexican", "delivery", "vegetarian", "halal", "yes"])


def _gather(say_text):
    """Say something, then listen for speech and post it to /voice/turn."""
    return _twiml(
        f'<Gather input="speech" action="/voice/turn" method="POST" speechTimeout="auto" '
        f'speechModel="phone_call" enhanced="true" language="en-US" actionOnEmptyResult="true" '
        f'hints={quoteattr(_hints())}>'
        f'{_speak(say_text)}</Gather>'
        f'<Redirect method="POST">/voice/turn</Redirect>')


async def _form(request):
    raw = (await request.body()).decode()
    return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}


def _new_call(call_sid, caller):
    main = _main()
    sess = main.new_session()
    cfg = sess["config"]
    voice_cfg = types.GenerateContentConfig(
        system_instruction=main.SYSTEM + PHONE_RULES + f"\nCaller's phone number: {caller or 'unknown'}\n",
        tools=cfg.tools, temperature=cfg.temperature, thinking_config=cfg.thinking_config)
    sess["config"] = voice_cfg
    sess["chat"] = main.client().chats.create(model=main.MODELS[sess["model_i"]], config=voice_cfg)
    if caller:
        sess["order"].set_customer(phone=caller)
    sid = f"call-{call_sid}"
    main.SESSIONS[sid] = sess  # also visible to /api/state/{sid}
    CALLS[call_sid] = {"sid": sid, "caller": caller, "texted": False}
    return CALLS[call_sid]


def send_sms(to, body):
    """Text via the Twilio REST API (trial accounts: only to verified numbers). Returns ok/err."""
    load_dotenv(override=True)
    acct, token, frm = (os.getenv("TWILIO_SID"), os.getenv("TWILIO_TOKEN"), os.getenv("TWILIO_NUMBER"))
    # The agent may save the number the way it was spoken ("737 555 0100"): Twilio needs +1XXXXXXXXXX.
    digits = re.sub(r"\D", "", to or "")
    if len(digits) == 10:
        to = "+1" + digits
    elif len(digits) == 11 and digits.startswith("1"):
        to = "+" + digits
    elif digits and not (to or "").strip().startswith("+"):
        to = ""  # not a usable phone number
    if not (acct and token and frm and to):
        return "missing Twilio settings"
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{acct}/Messages.json",
        data=urllib.parse.urlencode({"To": to, "From": frm, "Body": body}).encode(),
        headers={"Authorization": "Basic " + base64.b64encode(f"{acct}:{token}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("status", "sent")
    except Exception as e:
        print(f"[voice] SMS failed: {e}", flush=True)
        return f"error: {e}"


@router.post("/voice/incoming")
async def incoming(request: Request):
    f = await _form(request)
    _new_call(f.get("CallSid", "test"), f.get("From", ""))
    print(f"[voice] call from {f.get('From')} ({f.get('CallSid')})", flush=True)
    return _gather("Thanks for calling 334 Food Now! We deliver Indian, Italian and Mexican "
                   "in one order. What can I get you today?")


@router.post("/voice/turn")
async def turn(request: Request):
    main = _main()
    f = await _form(request)
    call_sid = f.get("CallSid", "test")
    call = CALLS.get(call_sid) or _new_call(call_sid, f.get("From", ""))
    said = (f.get("SpeechResult") or "").strip()
    if not said:
        return _gather("Sorry, I didn't catch that. Could you say that again?")
    print(f"[voice] caller: {said}", flush=True)
    sess = main.SESSIONS[call["sid"]]
    call["pending"] = asyncio.get_running_loop().run_in_executor(None, main.send_with_fallback, sess, said)
    return await _answer(call, sess, first=True)


async def _answer(call, sess, first):
    """Wait for the agent's reply. If Gemini is slow, say a filler and come back via /voice/wait so
    Twilio's 15 s webhook limit never drops the call."""
    try:
        reply = await asyncio.wait_for(asyncio.shield(call["pending"]), 7 if first else 8)  # + TTS 6 s < Twilio 15 s
    except asyncio.TimeoutError:
        filler = "One moment please." if first else "Still checking, thanks for waiting."
        return _twiml(f'<Say voice="{VOICE}">{filler}</Say><Redirect method="POST">/voice/wait</Redirect>')
    except Exception as e:
        print(f"[voice] agent error: {e}", flush=True)
        return _gather("Sorry, I had a hiccup on my end. Could you say that again?")
    print(f"[voice] agent: {reply}", flush=True)
    order = sess["order"]
    if order.number and not call["texted"]:
        call["texted"] = True

        def text_link():
            body = order.confirm()["pay_link_text"]
            to = order.customer.get("phone") or call["caller"]
            status = send_sms(to, body)
            if not status.startswith(("queued", "sent", "accepted", "sending")) and call["caller"] not in ("", to):
                to = call["caller"]  # the saved number failed: fall back to the caller ID
                status = send_sms(to, body)
            print(f"[voice] pay link SMS to {to}: {status}", flush=True)

        # off the event loop, and never hold the reply past Twilio's 15 s webhook limit
        sms = asyncio.get_running_loop().run_in_executor(None, text_link)
        try:
            await asyncio.wait_for(asyncio.shield(sms), 2)
        except Exception:
            pass
        return _twiml(_speak(reply) +
                      '<Pause length="1"/><Hangup/>')
    return _gather(reply)


@router.post("/voice/wait")
async def wait(request: Request):
    f = await _form(request)
    call = CALLS.get(f.get("CallSid", "test"))
    if not call or not call.get("pending"):
        return _gather("What else can I get you?")
    return await _answer(call, _main().SESSIONS[call["sid"]], first=False)


@router.get("/voice/audio/{aid}.wav")
def audio(aid: str):
    return Response(AUDIO.get(aid, b""), media_type="audio/wav")


@router.post("/api/tts")
async def tts(request: Request):
    """Browser call mode: Cartesia speech for one reply, or 204 so the page uses its own voice."""
    text = (await request.json()).get("text", "")
    wav = _cartesia_wav(re.sub(r"https?://\S+", "the link on your screen", text)[:1200], rate=24000, raw=True)
    return Response(wav, media_type="audio/wav") if wav else Response(status_code=204)


@router.get("/voice/health")
def health():
    load_dotenv(override=True)
    return {"ok": True, "calls": len(CALLS),
            "cartesia": bool(os.getenv("CARTESIA_API_KEY")),
            "twilio_configured": all(os.getenv(k) for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_NUMBER"))}
