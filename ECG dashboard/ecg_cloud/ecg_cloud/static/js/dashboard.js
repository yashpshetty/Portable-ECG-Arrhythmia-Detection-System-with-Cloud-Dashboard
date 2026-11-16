const A = window.APP;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const FS = 360, SECONDS = 6, N = FS * SECONDS;
let buf = new Array(N).fill(0), queue = [], acc = 0, amp = 150;
let client = null, current = null, patients = [], lastMsg = 0, chart = null;

async function api(path) {
  const r = await fetch(path);
  if (r.status === 401) { location = '/'; return null; }
  return r.json();
}
function setChip(id, ok, text, txtId) {
  $(id).classList.toggle('ok', ok);
  if (txtId) $(txtId).textContent = text;
}

/* ---------- patients ---------- */
async function init() {
  patients = await api('/api/patients');
  const sel = $('#patientSel');
  sel.innerHTML = patients.map(p => `<option value="${esc(p.code)}">${esc(p.name)} (${esc(p.code)}) – ${esc(p.relation)}</option>`).join('');
  sel.onchange = () => selectPatient(sel.value);
  $('#logout').onclick = async () => { await fetch('/api/logout', {method: 'POST'}); location = '/'; };
  connectMqtt();
  if (patients.length) selectPatient(patients[0].code);
  requestAnimationFrame(frame);
  setInterval(watchdog, 1000);
  setInterval(() => current && loadSummary(), 30000);
}

function selectPatient(code) {
  if (client && current) client.unsubscribe([`${A.root}/${current}/live`, `${A.root}/${current}/alert`, `${A.root}/${current}/note`]);
  current = code;
  buf.fill(0); queue = []; lastMsg = 0; resetLive(); onNote({});
  const p = patients.find(x => x.code === code);
  $('#details').innerHTML = [['Name', p.name], ['Patient ID', p.code], ['Age', p.age], ['Relation', p.relation]]
    .map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
  if (client && client.connected) subscribe();
  loadAlerts(); loadSummary();
}
function subscribe() {
  client.subscribe([`${A.root}/${current}/live`, `${A.root}/${current}/alert`, `${A.root}/${current}/note`]);
}

/* ---------- MQTT ---------- */
function connectMqtt() {
  client = mqtt.connect(A.wsUrl, {clientId: 'web-' + Math.random().toString(16).slice(2, 10), reconnectPeriod: 2000});
  client.on('connect', () => { setChip('#chipCloud', true, 'connected', '#cloudTxt'); if (current) subscribe(); });
  client.on('close', () => setChip('#chipCloud', false, 'disconnected', '#cloudTxt'));
  client.on('message', (topic, payload) => {
    let d; try { d = JSON.parse(payload.toString()); } catch { return; }
    if (topic.endsWith('/live')) onLive(d); else if (topic.endsWith('/alert')) onAlert(d); else if (topic.endsWith('/note')) onNote(d);
  });
}

function onLive(d) {
  lastMsg = Date.now();
  if (Array.isArray(d.samples)) queue.push(...d.samples);
  if (queue.length > FS * 3) queue.splice(0, queue.length - FS * 2);
  $('#bpm').textContent = d.bpm > 0 ? d.bpm : '--';
  const r = $('#rhythm'); r.textContent = d.rhythm || '--';
  r.className = 'big sm ' + (d.rhythm === 'Normal' ? 'good' : 'bad');
  if (typeof d.battery === 'number') {
    $('#batt').textContent = d.battery;
    const b = $('#battBar'); b.style.width = d.battery + '%';
    b.style.background = d.battery < 20 ? 'var(--bad)' : d.battery < 40 ? 'var(--warn)' : 'var(--good)';
  }
  setChip('#chipPatch', d.patch !== false, d.patch !== false ? 'connected' : 'offline', '#patchTxt');
  setChip('#chipData', true, 'live', '#seenTxt');
}
function onNote(d) {                       // hospital reference text published by the replay tool
  const el = $('#refNote');
  if (d && d.note) { $('#refText').textContent = d.note; el.hidden = false; } else { el.hidden = true; }
}
function resetLive() {
  ['#bpm', '#batt'].forEach(s => $(s).textContent = '--');
  $('#rhythm').textContent = '--'; $('#rhythm').className = 'big sm'; $('#battBar').style.width = '0';
  setChip('#chipPatch', false, 'offline', '#patchTxt'); setChip('#chipData', false, 'no data', '#seenTxt');
}
function watchdog() {
  if (lastMsg && Date.now() - lastMsg > 4000) {
    setChip('#chipPatch', false, 'offline', '#patchTxt');
    setChip('#chipData', false, 'no data', '#seenTxt');
    $('#bpm').textContent = '--';
  }
}

/* ---------- alerts ---------- */
function alertHtml(a) {
  return `<div class="alert"><b>${esc(a.kind)}</b> · ${esc(a.bpm)} BPM<small>${new Date(a.ts * 1000).toLocaleString()}</small>
  <small>SMS: ${esc(a.sms_status || 'pending')}</small></div>`;
}
async function loadAlerts() {
  const list = await api(`/api/alerts?patient=${current}`);
  $('#alerts').innerHTML = list && list.length ? list.map(alertHtml).join('') : '<div class="empty">No alerts – all good.</div>';
}
function onAlert(a) {
  const t = $('#toast'); t.textContent = '⚠ ' + a.message; t.hidden = false;
  setTimeout(() => t.hidden = true, 9000);
  beep(); setTimeout(loadAlerts, 2500); loadSummary();
}
function beep() {
  try {
    const c = new (window.AudioContext || window.webkitAudioContext)(), o = c.createOscillator(), g = c.createGain();
    o.frequency.value = 880; o.connect(g); g.connect(c.destination); g.gain.value = .15; o.start(); o.stop(c.currentTime + .4);
  } catch {}
}

/* ---------- bar chart ---------- */
async function loadSummary() {
  const rows = await api(`/api/summary?patient=${current}`); if (!rows) return;
  const data = {labels: rows.map(r => r.label), datasets: [
    {label: 'Avg heart rate (BPM)', data: rows.map(r => r.avg_bpm), backgroundColor: '#22d3eecc', borderRadius: 8, yAxisID: 'y'},
    {label: 'Abnormal events', data: rows.map(r => r.abnormal), backgroundColor: '#f43f5ecc', borderRadius: 8, yAxisID: 'y1'}]};
  if (chart) { chart.data = data; chart.update(); return; }
  const grid = {color: '#1f2d4a'}, tick = {color: '#8a9bb8'};
  chart = new Chart($('#bars'), {type: 'bar', data, options: {
    maintainAspectRatio: false, plugins: {legend: {labels: {color: '#c5d0e6'}}},
    scales: {x: {grid: {display: false}, ticks: tick},
      y: {grid, ticks: tick, beginAtZero: true, title: {display: true, text: 'BPM', color: '#8a9bb8'}},
      y1: {position: 'right', grid: {display: false}, ticks: {...tick, precision: 0}, beginAtZero: true, title: {display: true, text: 'Events', color: '#8a9bb8'}}}}});
}

/* ---------- live ECG drawing ---------- */
const cv = $('#ecg'), ctx = cv.getContext('2d');
let last = performance.now();
function frame(t) {
  const dt = Math.min((t - last) / 1000, .25); last = t;
  if (queue.length) {
    acc += dt * FS * (queue.length > FS * 1.2 ? 1.5 : 1);
    const n = Math.min(Math.floor(acc), queue.length); acc -= Math.floor(acc);
    if (n > 0) { const chunk = queue.splice(0, n); buf.splice(0, n); buf.push(...chunk); }
  }
  draw(); requestAnimationFrame(frame);
}
function draw() {
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  const box = W / SECONDS * 0.04;                     // ECG-paper grid: one small box = 0.04 s
  ctx.lineWidth = 1;
  for (let i = 0; i * box <= W; i++) {
    ctx.strokeStyle = i % 5 === 0 ? '#1b3150' : '#0f2038';
    ctx.beginPath(); ctx.moveTo(i * box, 0); ctx.lineTo(i * box, H); ctx.stroke();
  }
  for (let i = 0; i * box <= H; i++) {
    ctx.strokeStyle = i % 5 === 0 ? '#1b3150' : '#0f2038';
    ctx.beginPath(); ctx.moveTo(0, i * box); ctx.lineTo(W, i * box); ctx.stroke();
  }
  let m = 0; for (const v of buf) if (Math.abs(v) > m) m = Math.abs(v);
  amp = amp * 0.98 + Math.max(60, m) * 0.02;
  const k = (H * 0.42) / amp;
  ctx.strokeStyle = '#34d399'; ctx.lineWidth = 2; ctx.lineJoin = 'round';
  ctx.shadowColor = '#34d399'; ctx.shadowBlur = 8; ctx.beginPath();
  for (let i = 0; i < N; i++) {
    const x = i / (N - 1) * W, y = H / 2 - buf[i] * k;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.stroke(); ctx.shadowBlur = 0;
}

init();
