"""Phone ordering, streaming version: Twilio Media Streams -> AssemblyAI (speech-to-text) -> same agent
-> Cartesia (text-to-speech) -> back into the call. Used only when ASSEMBLYAI_API_KEY and CARTESIA_API_KEY
are both in .env; otherwise /voice/stream/incoming falls back to the <Gather>/<Say> flow in voice.py.

Twilio number -> Voice webhook (POST) -> https://<tunnel>/voice/stream/incoming
"""
import asyncio
import base64
import json
import os
import urllib.parse
import urllib.request
from xml.sax.saxutils import quoteattr

import websockets
from dotenv import load_dotenv
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from . import voice

router = APIRouter()
AAI_URL = ("wss://streaming.assemblyai.com/v3/ws?sample_rate=8000&encoding=pcm_mulaw"
           "&format_turns=true&end_of_turn_confidence_threshold=0.6&min_end_of_turn_silence_when_confident=400")
GREETING = ("Thanks for calling 334 Food Now! We deliver Indian, Italian and Mexican in one order. "
            "What can I get you today?")


def _keys():
    load_dotenv(override=True)
    return os.getenv("ASSEMBLYAI_API_KEY"), os.getenv("CARTESIA_API_KEY")


@router.post("/voice/stream/incoming")
async def stream_incoming(request: Request):
    aai, cart = _keys()
    if not (aai and cart):
        print("[stream] keys missing, using the Gather flow", flush=True)
        return await voice.incoming(request)
    f = await voice._form(request)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    print(f"[stream] call from {f.get('From')} ({f.get('CallSid')}) -> wss://{host}", flush=True)
    return voice._twiml(f'<Connect><Stream url="wss://{host}/voice/stream/ws">'
                        f'<Parameter name="from" value={quoteattr(f.get("From", ""))}/></Stream></Connect>')


def _tts_mulaw(text):
    """Cartesia raw mu-law 8 kHz bytes (what Twilio plays), or None."""
    return voice._cartesia_wav(voice._speakable(text).replace("&amp;", "&"), rate=8000, raw=True,
                               encoding="pcm_mulaw", container="raw")


def _hangup(call_sid):
    acct, token = os.getenv("TWILIO_SID"), os.getenv("TWILIO_TOKEN")
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{acct}/Calls/{call_sid}.json",
        data=urllib.parse.urlencode({"Status": "completed"}).encode(),
        headers={"Authorization": "Basic " + base64.b64encode(f"{acct}:{token}".encode()).decode()})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print(f"[stream] hangup failed: {e}", flush=True)


@router.websocket("/voice/stream/ws")
async def stream_ws(ws: WebSocket):
    await ws.accept()
    aai_key, _ = _keys()
    loop = asyncio.get_running_loop()
    st = {"sid": None, "call": None, "sess": None, "speaking": False, "end": False}
    turns = asyncio.Queue()

    async def say(text, mark=None):
        audio = await loop.run_in_executor(None, _tts_mulaw, text)
        if not audio:  # Cartesia failed: nothing we can play on a stream, keep going
            print("[stream] no audio for reply", flush=True)
            return
        st["speaking"] = True
        for i in range(0, len(audio), 1600):  # 200 ms chunks
            await ws.send_text(json.dumps({"event": "media", "streamSid": st["sid"],
                                           "media": {"payload": base64.b64encode(audio[i:i + 1600]).decode()}}))
        await ws.send_text(json.dumps({"event": "mark", "streamSid": st["sid"], "mark": {"name": mark or "said"}}))

    async def agent_loop():
        while True:
            said = await turns.get()
            print(f"[stream] caller: {said}", flush=True)
            try:
                reply = await loop.run_in_executor(None, voice._main().send_with_fallback, st["sess"], said)
            except Exception as e:
                print(f"[stream] agent error: {e}", flush=True)
                reply = "Sorry, I had a hiccup on my end. Could you say that again?"
            print(f"[stream] agent: {reply}", flush=True)
            order = st["sess"]["order"]
            if order.number and not st["call"]["texted"]:
                st["call"]["texted"] = True
                to = order.customer.get("phone") or st["call"]["caller"]
                status = await loop.run_in_executor(None, voice.send_sms, to, order.confirm()["pay_link_text"])
                print(f"[stream] pay link SMS to {to}: {status}", flush=True)
                await say(reply, mark="bye")
            else:
                await say(reply)

    async def aai_loop(aai):
        async for msg in aai:
            m = json.loads(msg)
            if m.get("type") == "Turn":
                text = (m.get("transcript") or "").strip()
                if text and st["speaking"]:  # barge-in: caller talks over the agent, stop playback
                    await ws.send_text(json.dumps({"event": "clear", "streamSid": st["sid"]}))
                    st["speaking"] = False
                if m.get("end_of_turn") and m.get("turn_is_formatted") and text:
                    await turns.put(text)

    tasks = []
    try:
        async with websockets.connect(AAI_URL, additional_headers={"Authorization": aai_key}) as aai:
            buf = b""
            while True:
                data = json.loads(await ws.receive_text())
                ev = data.get("event")
                if ev == "start":
                    st["sid"] = data["start"]["streamSid"]
                    call_sid = data["start"]["callSid"]
                    caller = data["start"].get("customParameters", {}).get("from", "")
                    st["call"] = voice._new_call(call_sid, caller)
                    st["sess"] = voice._main().SESSIONS[st["call"]["sid"]]
                    tasks = [asyncio.create_task(aai_loop(aai)), asyncio.create_task(agent_loop())]
                    asyncio.create_task(say(GREETING))
                elif ev == "media":
                    buf += base64.b64decode(data["media"]["payload"])
                    if len(buf) >= 800:  # 100 ms of 8 kHz mu-law
                        await aai.send(buf)
                        buf = b""
                elif ev == "mark":
                    st["speaking"] = False
                    if data.get("mark", {}).get("name") == "bye":
                        await asyncio.sleep(0.5)
                        await loop.run_in_executor(None, _hangup, st["call"]["sid"].removeprefix("call-"))
                elif ev == "stop":
                    await aai.send(json.dumps({"type": "Terminate"}))
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[stream] error: {type(e).__name__}: {e}", flush=True)
    finally:
        for t in tasks:
            t.cancel()
        print("[stream] call ended", flush=True)
