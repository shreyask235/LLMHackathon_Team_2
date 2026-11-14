"""Point the Twilio number's Voice webhook at our tunnel.
Usage: python -m server.twilio_wire https://<tunnel-host>
Reads TWILIO_SID, TWILIO_TOKEN, TWILIO_NUMBER from .env.
"""
import base64
import json
import os
import sys
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv(override=True)
ACCT, TOKEN, NUMBER = os.environ["TWILIO_SID"], os.environ["TWILIO_TOKEN"], os.environ["TWILIO_NUMBER"]
AUTH = {"Authorization": "Basic " + base64.b64encode(f"{ACCT}:{TOKEN}".encode()).decode()}
BASE = f"https://api.twilio.com/2010-04-01/Accounts/{ACCT}"


def call(url, data=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None, headers=AUTH)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


tunnel = sys.argv[1].rstrip("/")
nums = call(f"{BASE}/IncomingPhoneNumbers.json?" + urllib.parse.urlencode({"PhoneNumber": NUMBER}))
if not nums["incoming_phone_numbers"]:
    sys.exit(f"{NUMBER} is not a number on this Twilio account")
pn = nums["incoming_phone_numbers"][0]
out = call(f"{BASE}/IncomingPhoneNumbers/{pn['sid']}.json",
           {"VoiceUrl": f"{tunnel}/voice/incoming", "VoiceMethod": "POST"})
print("Voice webhook for", out["phone_number"], "->", out["voice_url"])
