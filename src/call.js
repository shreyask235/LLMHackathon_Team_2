// "Call 334-FOOD-NOW": talk to the same agent by voice in the browser (no phone number needed).
// Listening: the browser's speech recognition (Chrome / Edge). Speaking: Cartesia via /api/tts when
// CARTESIA_API_KEY is in .env, otherwise the browser's own voice.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition
const head = document.querySelector('.chat-head')

const style = document.createElement('style')
style.textContent = `
.call-btn { margin-left: auto; display: flex; align-items: center; gap: 8px; padding: 9px 16px; border-radius: 99px; font-size: .85rem; }
.call-btn.on { background: #e5484d; }
.call-state { font-size: .78rem; color: var(--muted); min-width: 0; }
.call-btn .dot { width: 8px; height: 8px; border-radius: 50%; background: #fff; }
.call-btn.on .dot { animation: callpulse 1s infinite; }
@keyframes callpulse { 50% { opacity: .3; } }`
document.head.appendChild(style)

const state = document.createElement('span')
state.className = 'call-state'
const btn = document.createElement('button')
btn.type = 'button'
btn.className = 'call-btn'
btn.innerHTML = '<span class="dot"></span><span class="label">Call 334-FOOD-NOW</span>'
head.append(state, btn)

let live = false
let rec = null
let audio = null

const setState = (t) => { state.textContent = t }
const speakable = (t) => t.replace(/https?:\/\/\S+/g, 'the link on your screen').replace(/[*_#`]/g, '')

async function speak(text) {
  text = speakable(text)
  try {
    const res = await fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
    if (!live) return // hung up while the audio was being made: stay quiet
    if (res.status === 200) {
      const url = URL.createObjectURL(await res.blob())
      audio = new Audio(url)
      await new Promise((ok) => { audio.onended = ok; audio.onerror = ok; audio.play().catch(ok) })
      return
    }
  } catch {}
  await new Promise((ok) => {
    const u = new SpeechSynthesisUtterance(text)
    u.lang = 'en-US'
    u.rate = 1.05
    u.onend = ok
    u.onerror = ok
    speechSynthesis.speak(u)
  })
}

function listen() {
  return new Promise((resolve) => {
    rec = new SR()
    rec.lang = 'en-US'
    rec.interimResults = false
    rec.maxAlternatives = 1
    let heard = ''
    rec.onresult = (e) => { heard = e.results[0][0].transcript }
    rec.onend = () => resolve(heard.trim())
    rec.onerror = () => {}
    rec.start()
  })
}

let callNo = 0 // a call that was hung up and redialed must not keep running next to the new one

async function loop() {
  const mine = ++callNo
  const on = () => live && mine === callNo
  setState('Connected')
  await speak('Thanks for calling 334 Food Now! We deliver Indian, Italian and Mexican in one order. What can I get you today?')
  let misses = 0
  while (on()) {
    setState('Listening...')
    const said = await listen()
    if (!on()) break
    if (!said) {
      if (++misses >= 3) { await speak("I'll be here when you're ready. Goodbye!"); break }
      continue
    }
    misses = 0
    setState('Thinking...')
    const data = await window.foodSend(said)
    if (!on()) break
    if (!data) { await speak('Sorry, I had a hiccup. Could you say that again?'); continue }
    setState('Speaking...')
    await speak(data.reply)
    if (data.order && data.order.order_number) { await speak('Thanks for ordering with 334 Food Now. Goodbye!'); break }
  }
  if (mine === callNo) hangup()
}

function hangup() {
  live = false
  try { rec && rec.abort() } catch {}
  try { audio && audio.pause() } catch {}
  speechSynthesis.cancel()
  btn.classList.remove('on')
  btn.querySelector('.label').textContent = 'Call 334-FOOD-NOW'
  setState('')
}

btn.onclick = () => {
  if (live) return hangup()
  if (!SR) { setState('Voice needs Chrome or Edge'); return }
  live = true
  btn.classList.add('on')
  btn.querySelector('.label').textContent = 'Hang up'
  loop()
}
