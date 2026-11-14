const $ = (id) => document.getElementById(id)
let sessionId = null
const FREE_OVER = 50

const SAMPLES = [
  'Hi, can I get two chicken biryanis, one not spicy, and a penne alfredo? Is delivery free?',
  'What’s vegetarian?',
  'Is anything halal at the Mexican place?',
  'Add a veggie burrito',
  'Drop the burrito',
]

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

function bubble(text, who) {
  const div = document.createElement('div')
  div.className = `msg ${who}`
  div.textContent = text
  $('log').appendChild(div)
  $('log').scrollTop = $('log').scrollHeight
  return div
}

function typing() {
  const div = document.createElement('div')
  div.className = 'msg bot typing'
  div.innerHTML = '<span></span><span></span><span></span>'
  $('log').appendChild(div)
  $('log').scrollTop = $('log').scrollHeight
  return div
}

function cartHtml(o) {
  const rs = Object.entries(o.restaurants)
  if (!rs.length) return '<p class="empty">Your cart is empty. Ask for anything on the menu.</p>'
  const t = o.totals
  const sub = parseFloat(t.subtotal)
  const pct = Math.min(100, (sub / FREE_OVER) * 100)
  const progress = `
    <div class="progress">
      <div class="progress-label"><span>Free delivery over $${FREE_OVER}</span><b>$${t.subtotal} / $${FREE_OVER}</b></div>
      <div class="bar ${t.free_delivery ? 'full' : ''}"><i style="width:${pct}%"></i></div>
      ${t.free_delivery
        ? '<div class="hint ok">You unlocked free delivery.</div>'
        : `<div class="hint">Add $${t.amount_needed_for_free_delivery} more for free delivery. Try the ${esc(t.suggested_item.item)} ($${t.suggested_item.price}).</div>`}
    </div>`
  const rests = rs.map(([r, lines]) => {
    const rt = lines.reduce((a, l) => a + l.price * l.qty, 0)
    return `<div class="rest ${esc(r.toLowerCase())}">
      <div class="rest-head"><span>${esc(r)}</span><span>$${rt.toFixed(2)}</span></div>
      <ul>${lines.map((l) => `<li><span><span class="qty">${l.qty}×</span> ${esc(l.name)}${l.notes.length ? ` <em>· ${esc(l.notes.join(', '))}</em>` : ''}</span><span>$${(l.price * l.qty).toFixed(2)}</span></li>`).join('')}</ul>
    </div>`
  }).join('')
  return rests + progress + `
    <dl>
      <dt>Subtotal</dt><dd>$${t.subtotal}</dd>
      <dt>Tax (8.25%)</dt><dd>$${t.tax}</dd>
      <dt>Delivery</dt><dd class="${t.delivery === 'FREE' ? 'free' : ''}">${t.delivery === 'FREE' ? 'FREE' : '$' + t.delivery}</dd>
      <dt class="total">Total</dt><dd class="total">$${t.total}</dd>
    </dl>`
}

function render(s) {
  sessionId = s.session_id
  const o = s.order
  $('status').textContent = o.status
  $('status').className = `badge ${o.status}`
  $('cart').innerHTML = cartHtml(o)
  $('outputs').hidden = !s.group_text // a fresh session (e.g. after a server restart) has no checkout yet
  if (s.group_text) {
    $('ordernum').textContent = `#${o.order_number}`
    $('pay').innerHTML = esc(s.pay_link_text).replace(/(https:\/\/\S+?)(?=\s|\)|$)/, '<a href="$1" target="_blank" rel="noopener">$1</a>')
    $('group').textContent = s.group_text
    $('json').textContent = JSON.stringify(s.order_json, null, 2)
  }
}

async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({ detail: res.statusText }))
  if (!res.ok) throw new Error(data.detail || res.statusText)
  return data
}

let busy = false // one request at a time: a second send on the same session would race on the server

async function send(text) {
  if (busy) return
  busy = true
  bubble(text, 'user')
  const wait = typing()
  $('msg').disabled = true
  try {
    const data = await post('/api/chat', { session_id: sessionId, message: text })
    wait.remove()
    bubble(data.reply, 'bot')
    render(data)
    return data
  } catch (e) {
    wait.remove()
    bubble(`Something went wrong: ${e.message}`, 'error')
  } finally {
    busy = false
    $('msg').disabled = false
    $('msg').focus()
  }
}

$('form').addEventListener('submit', (e) => {
  e.preventDefault()
  const text = $('msg').value.trim()
  if (!text) return
  $('msg').value = ''
  send(text)
})

for (const s of SAMPLES) {
  const b = document.createElement('button')
  b.type = 'button'
  b.textContent = s
  b.onclick = () => send(s)
  $('chips').appendChild(b)
}

document.querySelectorAll('.sim button').forEach((b) =>
  b.addEventListener('click', async () => {
    try {
      const data = await post(`/api/simulate/${sessionId}/${b.dataset.ev}`)
      data.messages.forEach((m) => bubble(m, 'sms'))
      render(data)
    } catch (e) {
      bubble(`Something went wrong: ${e.message}`, 'error')
    }
  }),
)

bubble('Hi, this is 334-FOOD-NOW! I can put Indian, Italian and Mexican dishes on one order with one delivery. What would you like?', 'bot')

// Used by src/call.js (voice call mode)
window.foodSend = send
