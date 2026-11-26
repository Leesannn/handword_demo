// 수어 칠판의 화면과 서버 전송. 아이폰 앱(~/sign-app/ios-board/KSLBoard)의 화면을 그대로 옮긴 것이다.
// 엔진(engine/page.html의 모듈)이 window.KSLOnFrame·KSLOnMessage로 좌표와 판정을 넘기고, 여기서는 window.KSLCommand로 엔진을 부린다.
// 옮겨 온 곳: BoardModel.swift(상태), TranslateView·LearnView·LessonView·PracticeView·TokenDetailView(화면),
// FigureView.swift(사람 도식), LaneView.swift(시간 줄), Gloss.swift(대괄호 표기), Sync/*(기록)
(function () {
  const GOAL = 3, MAX_S = 3, MIN_S = 0.5;
  const NATIVE = !!window.ReactNativeWebView;      // 앱(웹뷰) 안인지, 브라우저인지
  const BASE = window.KSL_SERVER || '';
  const $ = (id) => document.getElementById(id);
  const h = (tag, props, ...kids) => {
    const n = document.createElement(tag);
    for (const k in props || {}) {
      const v = props[k];
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v; else if (k === 'style') n.style.cssText = v; else if (k.startsWith('on')) n[k] = v;
      else if (k === 'html') n.innerHTML = v; else if (k in n && k !== 'list') n[k] = v; else n.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid);
    return n;
  };
  const pct = (p) => Math.round(p * 100) + '%';
  const secs = (s) => s.toFixed(1) + '초';
  const ratio = (a) => (a && a.length ? a.filter(Boolean).length / a.length : 0);
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3) | 8).toString(16); }));
  // "감사로", "집으로"
  const withRo = (w) => { const c = w.charCodeAt(w.length - 1); if (c < 0xac00 || c > 0xd7a3) return w + '(으)로'; const f = (c - 0xac00) % 28; return w + (f === 0 || f === 8 ? '로' : '으로'); };
  const store = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } } };
  const cmd = (c) => window.KSLCommand && window.KSLCommand(c);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const ICON = {
    camera: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.6l1.2-1.8h7.4L16.9 6h1.6A2.5 2.5 0 0 1 21 8.5v8A2.5 2.5 0 0 1 18.500 19h-13A2.5 2.5 0 0 1 3 16.500z"/><path d="M9.200 11.200a3 3 0 0 1 5.300-.9M14.800 13.800a3 3 0 0 1-5.300.9"/><path d="M14.700 8.900v1.600h-1.600M9.300 16.100v-1.600h1.600"/></svg>',
    back: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg>',
    close: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    pause: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="4" width="5" height="16" rx="1.2"/><rect x="14" y="4" width="5" height="16" rx="1.2"/></svg>',
    play: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.500v15a1 1 0 0 0 1.500.9l12-7.500a1 1 0 0 0 0-1.700l-12-7.500A1 1 0 0 0 7 4.500z"/></svg>',
    stop: '<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="3"/></svg>',
    pair: '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="square"><path d="M3.400 1.300H1.300v17.400h2.100M16.600 1.300h2.100v17.400h-2.100"/></svg>',
    pairBig: '<svg width="30" height="30" viewBox="0 0 30 30" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="square"><path d="M5.100 1.500H1.500v27h3.600M24.900 1.500h3.600v27h-3.600"/></svg>',
    tabTranslate: '<svg width="26" height="26" viewBox="0 0 26 26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="square"><path d="M6.400 4H3v18h3.400M19.600 4H23v18h-3.400"/><g fill="currentColor" stroke="none"><circle cx="9.400" cy="13" r="1.200"/><circle cx="13" cy="13" r="1.200"/><circle cx="16.600" cy="13" r="1.200"/></g></svg>',
    tabLearn: '<svg width="26" height="26" viewBox="0 0 26 26" fill="none" stroke="currentColor" stroke-width="1.900" stroke-linejoin="round"><path d="M13 6.500C11 5 8 4.500 4.500 5v14c3.500-.5 6.500 0 8.500 1.500 2-1.500 5-2 8.500-1.500V5C18 4.500 15 5 13 6.500zM13 6.500v14"/></svg>',
    chev: '<svg class="chev" width="9" height="14" viewBox="0 0 9 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1.500 1.500L7 7l-5.500 5.500"/></svg>',
    check: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12.500l5.500 5.500L20 6.500"/></svg>',
    alert: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.200" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.500v5.500M12 16.500v.2"/></svg>',
  };
  const icon = (name) => h('span', { html: ICON[name], style: 'display:grid;place-items:center' });

  // ── 서버 전송 (Sync/Outbox.swift, SyncCenter.swift). 폰에 먼저 쌓고 서버가 2xx로 받으면 지운다. 못 보낸 것은 30초마다 다시 보낸다
  const ua = navigator.userAgent;
  const device = (NATIVE ? '' : 'web-') + (/Android/.test(ua) ? 'android' : /iPhone|iPad/.test(ua) ? 'ios' : /Mac/.test(ua) ? 'mac' : 'other')
    + (/Android (\d+)/.test(ua) ? '-' + RegExp.$1 : '');
  const sync = { user: store.get('sync.user') || uuid(), session: uuid(), seq: store.get('sync.seq', 0), agreed: store.get('sync.agreed', false),
    key: store.get('sync.key', ''), outbox: store.get('sync.outbox', []), sent: store.get('sync.sent', []), rejected: store.get('sync.rejected', []), busy: false, last: null };
  store.set('sync.user', sync.user);
  let soon = null, postSeq = 0;
  const waiting = {};
  window.KSLNativeReply = (id, status) => { if (waiting[id]) { waiting[id](status); delete waiting[id]; } };

  function log(type, fields) {
    if (!sync.agreed) return;
    sync.seq += 1;
    const event = { event_id: uuid(), schema_version: 1, event_type: type, event_time: new Date().toISOString(), seq: sync.seq, user_id: sync.user,
      session_id: sync.session, app_version: NATIVE ? '1.0-expo' : '1.0-web', model_version: (window.KSL_MODEL && window.KSL_MODEL.run) || '', device };
    for (const k in fields) if (fields[k] !== undefined && fields[k] !== null) event[k] = fields[k];
    sync.outbox.push(event);
    store.set('sync.seq', sync.seq); store.set('sync.outbox', sync.outbox);
    clearTimeout(soon); soon = setTimeout(flush, 1500);
  }
  function post(events) {
    const body = JSON.stringify({ sent_at: new Date().toISOString(), count: events.length, events });
    // 앱 안에서는 주소 제한(CORS) 때문에 앱(React Native)이 대신 보낸다. 서버 주소와 키도 앱이 갖고 있다
    if (NATIVE) return new Promise((done) => { const id = ++postSeq; waiting[id] = done; window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'post', id, body })); setTimeout(() => window.KSLNativeReply(id, 0), 20000); });
    return fetch(BASE + '/v1/events', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': sync.key }, body }).then((r) => r.status, () => 0);
  }
  function sentOK(events, code) {
    const ids = new Set(events.map((e) => e.event_id)), at = new Date().toISOString();
    sync.outbox = sync.outbox.filter((e) => !ids.has(e.event_id));
    sync.sent = sync.sent.concat(events.map((e) => ({ sent_at: at, http: code, event_id: e.event_id, event_type: e.event_type, event_time: e.event_time,
      seq: e.seq, source: e.source || '', word: e.word || '', outcome: e.outcome || '' }))).slice(-500);
    store.set('sync.outbox', sync.outbox); store.set('sync.sent', sync.sent);
  }
  async function flush() {
    if (sync.busy || (!NATIVE && !sync.key) || !sync.outbox.length) return;
    sync.busy = true;
    try {
      while (sync.outbox.length) {
        const batch = sync.outbox.slice(0, 100), code = await post(batch);
        sync.last = code;
        if (code >= 200 && code < 300) sentOK(batch, code);
        else if ([400, 413, 422].includes(code)) {
          // 묶음 안의 한 건 때문에 전부 거절됐을 수 있으니 한 건씩 다시 보낸다
          for (const event of batch) {
            const one = batch.length === 1 ? code : await post([event]);
            if (one >= 200 && one < 300) sentOK([event], one);
            else if ([400, 413, 422].includes(one)) {
              sync.outbox = sync.outbox.filter((e) => e.event_id !== event.event_id);
              sync.rejected = sync.rejected.concat(event).slice(-200);
              store.set('sync.outbox', sync.outbox); store.set('sync.rejected', sync.rejected);
            } else return;
          }
        } else return;
      }
    } finally { sync.busy = false; }
  }
  setInterval(flush, 30000);
  document.addEventListener('visibilitychange', flush);

  // 좌표 묶음(샘플): 다시 학습할 때 쓰도록 동작의 좌표를 폰에 남긴다. 서버의 받는 주소가 열리면 올린다
  const kept = new Map();
  function remember(m) { if (!m.clip) return; kept.set(m.id, m); if (kept.size > 8) kept.delete(kept.keys().next().value); }
  function saveSample(id, label, feedback, source, outcome) {
    const m = kept.get(id);
    if (!m || !sync.agreed) return undefined;
    const sample = { id, reading_id: id, label, feedback, source, outcome, predicted: m.top.word, classes: window.KSL_MODEL.classes,
      probabilities: window.KSL_MODEL.classes.map((c) => m.probabilities[c]), mirrored: m.mirrored, frames: m.clip.frames, times: m.clip.times,
      start: m.clip.start, end: m.clip.end, aspect: m.aspect, person: sync.user, model: window.KSL_MODEL.run, mode: m.mode, camera: m.facing === 'user' ? 'front' : 'back',
      device, app_version: NATIVE ? '1.0-expo' : '1.0-web', created: new Date().toISOString() };
    let list = store.get('sync.samples', []).filter((s) => s.id !== id).concat(sample).slice(-12);
    while (list.length && !store.set('sync.samples', list)) list = list.slice(1);   // 자리가 모자라면 오래된 것부터 버린다
    return list.length ? id : undefined;
  }

  // ── 상태 (BoardModel.swift)
  const model = { setup: 'starting', failText: '', words: [], pose: null, nobody: false, rightVisible: true, leftVisible: true, guide: 'ok', aspect: 0.75, facing: 'user',
    isReading: false, elapsed: 0, trail: { right: [], left: [] }, tokens: [], latest: null, tooShort: false, autoEndedAt: 0, lost: 0, rightGone: 0, leftGone: 0 };
  const view = { tab: 'translate', lesson: null, practice: null, detail: null, tipSeen: store.get('detailTipSeen', false) };
  const stageFigure = () => h('canvas', { class: 'figure', id: 'figure' });
  const marks = store.get('marks', {});
  const count = (w) => Math.min(GOAL, marks[w] || 0);
  const progressText = (c) => ['아직 알아본 적이 없어요', '한 번 알아봤어요. 두 번 더 하면 익힘', '두 번 알아봤어요. 한 번 더 하면 익힘', '세 번 알아봐서 익힌 낱말이에요'][Math.min(c, 3)];
  const DEMOS = window.KSL_DEMOS || {};
  const keyFrames = (n) => [0.12, 0.38, 0.64, 0.9].map((k) => Math.round((n - 1) * k));

  // 177개 값 → 그림에 쓰는 점. 좌우 반전한 화면에서는 "Left" 자리(21~41)가 실제 오른손이다 (Reading.swift Pose2D)
  function toPose(v) {
    const pt = (i) => { const x = v[i * 3], y = v[i * 3 + 1]; return x == null || Number.isNaN(x) || Number.isNaN(y) ? null : { x, y }; };
    const hand = (start) => { const p = []; for (let i = 0; i < 21; i++) { const q = pt(start + i); if (!q) return null; p.push(q); } return p; };
    return { body: Array.from({ length: 17 }, (_, i) => pt(42 + i)), right: hand(21), left: hand(0) };
  }
  function extend(runs, flag, point) {
    if (!point) return false;
    if (flag) runs[runs.length - 1].push(point); else runs.push([point]);
    return true;
  }
  let rightOpen = false, leftOpen = false, cameraOn = true;
  // 직전 자세에서 지금 자세로 가는 중간 자세. 한쪽에만 있는 점이나 손은 섞지 않고 지금 것을 쓴다
  function shown() {
    const cur = model.pose, prev = model.prevPose;
    if (!cur || !prev) return cur;
    const k = clamp((performance.now() - model.poseAt) / model.gap, 0, 1);
    if (k >= 1) return cur;
    const mix = (p, q) => (p && q ? { x: p.x + (q.x - p.x) * k, y: p.y + (q.y - p.y) * k } : q);
    const hand = (p, q) => (p && q ? q.map((pt, i) => mix(p[i], pt)) : q);
    return { body: cur.body.map((pt, i) => mix(prev.body[i], pt)), right: hand(prev.right, cur.right), left: hand(prev.left, cur.left) };
  }
  let rafAt = 0;
  (function loop() { rafAt = performance.now(); if (cameraOn && model.pose) drawFigure($('figure')); requestAnimationFrame(loop); })();

  window.KSLOnFrame = (f) => {
    model.aspect = f.width / f.height; model.facing = f.facing;
    const seen = f.person ? toPose(f.values) : null;
    // 좌표는 초당 11~15장 들어오지만 화면은 그 사이를 이어 그려 매끄럽게 보이게 한다 (shown)
    const at = performance.now();
    model.prevPose = shown() || model.pose; model.gap = clamp((at - (model.poseAt || at)) * 0.6, 30, 70); model.poseAt = at;   // 새 자세까지 빨리 따라붙는다 (오래 끌면 반응이 늦어 보인다)
    model.pose = seen;
    model.lost = seen ? 0 : model.lost + 1;
    const nobody = model.lost >= 15;
    model.rightGone = seen && seen.right ? 0 : model.rightGone + 1;
    model.leftGone = seen && seen.left ? 0 : model.leftGone + 1;
    model.rightVisible = model.rightGone < 6; model.leftVisible = model.leftGone < 6;
    // 자리 안내 (PositionGuide.swift): 어깨 중심이 가운데에 있는지 먼저 보고, 어깨 폭으로 거리를 본다
    let guide = 'noPerson';
    if (seen && seen.body[11] && seen.body[12]) {
      const a = seen.body[11], b = seen.body[12], center = (a.x + b.x) / 2, size = Math.hypot((a.x - b.x) * f.width, (a.y - b.y) * f.height) / f.width;
      guide = center < 0.32 ? 'moveRight' : center > 0.68 ? 'moveLeft' : size < 0.12 ? 'closer' : size > 0.30 ? 'farther' : 'ok';
    }
    const wasReading = model.isReading;
    model.isReading = f.recording; model.elapsed = f.elapsed;
    if (f.recording && seen) { rightOpen = extend(model.trail.right, rightOpen, seen.right && seen.right[0]); leftOpen = extend(model.trail.left, leftOpen, seen.left && seen.left[0]); }
    const changed = nobody !== model.nobody || guide !== model.guide || wasReading !== model.isReading;
    model.nobody = nobody; model.guide = guide;
    if (changed) render(); else live();
  };

  window.KSLOnMessage = (m) => {
    if (m.type === 'status') { if (model.setup !== 'ready') { model.failText = m.text; render(); } }
    else if (m.type === 'error') { model.setup = /권한/.test(m.text) ? 'cameraDenied' : 'failed'; model.failText = m.text; render(); }
    else if (m.type === 'ready') { model.setup = 'ready'; model.words = m.classes.filter((c) => c !== '기타'); cmd({ type: 'mode', mode: 'button' }); cmd({ type: 'clips', keep: true }); render(); }
    else if (m.type === 'camera') { model.facing = m.facing; model.pose = null; render(); }
    else if (m.type === 'started') { model.trail = { right: [], left: [] }; rightOpen = leftOpen = false; model.tooShort = false; model.isReading = true; model.elapsed = 0; render(); }
    else if (m.type === 'tooShort') { model.isReading = false; if (m.mode === 'button') { model.tooShort = true; log('recognition_result', { source: 'translate', outcome: 'too_short' }); } render(); }
    else if (m.type === 'reading') {
      model.isReading = false; remember(m);
      if (m.mode === 'button') { model.autoEndedAt = Date.now(); if (view.practice) return; record(m); }
      else if (view.practice) practiceRead(m);
      render();
    }
  };

  // 번역 (BoardModel.record, setWord)
  function fillReading(m, target) {
    return { reading_id: m.id, predicted_word: m.top.word, confidence: m.top.probability, probabilities: m.probabilities,
      duration_ms: Math.round(m.seconds * 1000), hand_missing_ratio: m.handMissing, target_probability: target ? (m.probabilities[target] || 0) : undefined };
  }
  function record(m) {
    log('recognition_result', { source: 'translate', ...fillReading(m), outcome: m.kind === 'sure' ? 'read' : m.kind });
    if (m.kind === 'sure' || m.kind === 'unsure') {
      model.tokens.push({ id: m.id, word: m.top.word, sure: m.kind === 'sure', corrected: false, reading: m });
      if (model.tokens.length > 30) model.tokens.shift();
      model.latest = { token: m.id };
    } else model.latest = { unread: m.kind, seconds: m.seconds };
  }
  const token = (id) => model.tokens.find((t) => t.id === id);
  function setWord(word, id) {
    const t = token(id);
    if (!t) return;
    t.word = word; t.sure = true; t.corrected = word !== t.reading.top.word;
    const sample = saveSample(id, word, t.corrected ? 'corrected' : 'confirmed', 'kslboard-translate', t.corrected ? 'wrong_word' : 'correct');
    log('answer_selected', { source: 'translate', reading_id: id, predicted_word: t.reading.top.word, confidence: t.reading.top.probability,
      probabilities: t.reading.probabilities, selected_word: word, was_corrected: t.corrected, sample_id: sample });
    render();
  }
  function removeToken(id) { model.tokens = model.tokens.filter((t) => t.id !== id); if (model.latest && model.latest.token === id) model.latest = null; render(); }
  function toggleRead() {
    if (model.setup !== 'ready') return;
    if (model.isReading) cmd({ type: 'stop' });
    else { if (Date.now() - model.autoEndedAt < 600) return; cmd({ type: 'start' }); }   // 3초에서 저절로 끝난 직후의 누름은 넘긴다
  }

  // 따라 하기 (PracticeView.swift)
  let runToken = 0;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function practiceLog(type, extra) {
    const p = view.practice;
    const base = { source: 'practice', lesson_id: p.lessonId, word: p.word };
    if (p.attempts > 0 && ['practice_attempt', 'recognition_result', 'retry'].includes(type)) base.attempt = p.attempts;
    log(type, { ...base, ...extra });
  }
  function report(outcome, m) {
    const p = view.practice;
    p.lastOutcome = outcome;
    const sample = m ? saveSample(m.id, p.word, 'practice', 'kslboard-practice', outcome) : undefined;
    practiceLog('recognition_result', { ...(m ? fillReading(m, p.word) : {}), outcome, is_correct: outcome === 'correct', sample_id: sample });
  }
  function openPractice(word) {
    view.practice = { word, step: 'ready', n: 0, reading: null, why: null, read: null, lessonId: uuid(), attempts: 0, successes: 0, lastOutcome: null };
    cmd({ type: 'mode', mode: 'button' });
    if (model.facing !== 'user') cmd({ type: 'camera', facing: 'user' });
    practiceLog('lesson_started');
    render();
  }
  function closePractice() {
    const p = view.practice;
    if (!p) return;
    runToken++;
    cmd({ type: 'mode', mode: 'button' });
    practiceLog('lesson_ended', { total_attempts: p.attempts, success_count: p.successes });
    view.practice = null; render();
  }
  async function startPractice() {
    const p = view.practice;
    if (p.step === 'failure' && p.lastOutcome) practiceLog('retry', { attempt: p.attempts + 1, previous_outcome: p.lastOutcome });
    p.attempts += 1;
    practiceLog('practice_attempt');
    const my = ++runToken;
    for (const n of [3, 2, 1]) { p.step = 'counting'; p.n = n; render(); await sleep(900); if (my !== runToken) return; }
    p.step = 'armed'; model.trail = { right: [], left: [] }; cmd({ type: 'mode', mode: 'auto' }); render();
    // 6초 동안 손이 한 번도 보이지 않으면 그만둔다. 읽는 중이면 끝날 때까지 기다린다
    await sleep(6000);
    while (my === runToken && p.step === 'armed' && model.isReading) await sleep(200);
    if (my === runToken && p.step === 'armed') { cmd({ type: 'mode', mode: 'button' }); p.step = 'failure'; p.why = 'noHands'; p.reading = null; report('no_hands', null); render(); }
  }
  function practiceRead(m) {
    const p = view.practice;
    if (p.step !== 'armed') return;
    cmd({ type: 'mode', mode: 'button' });
    p.reading = m; p.read = m.top.word;
    const fail = (why, outcome) => { p.step = 'failure'; p.why = why; report(outcome, m); };
    if (m.kind === 'hands_unseen') fail('handsUnseen', 'hands_unseen');
    else if (m.kind === 'unknown') fail('unknown', 'unknown');
    else if (m.top.word !== p.word) fail('other', 'wrong_word');
    else if (m.kind !== 'sure') fail('unsure', 'unsure');
    else {
      const before = count(p.word);
      marks[p.word] = Math.min(GOAL, before + 1); store.set('marks', marks);
      p.successes += 1; p.step = 'success';
      report('correct', m);
      if (before < GOAL && count(p.word) === GOAL) practiceLog('lesson_completed', { total_attempts: p.attempts, success_count: p.successes });
    }
  }

  // ── 부품 (Gloss.swift, Parts.swift, LaneView.swift)
  function gloss(word, em = 34, tone = 'normal', weight = 700) {
    const stroke = Math.max(1.5, em * 0.095);
    const n = h('span', { class: 'gloss ' + tone, style: `--em:${em}px;--st:${stroke}px;font-weight:${weight}`, role: 'text',
      'aria-label': tone === 'unsure' ? `${word}, 확실하지 않음` : word === '?' ? '읽지 못함' : word }, h('i'), h('b', {}, word, tone === 'unsure' && h('em', {}, '?')), h('i'));
    return n;
  }
  function marksView(c) {
    let s = '';
    for (let i = 0; i < GOAL; i++) {
      const on = i < c, color = on ? 'var(--tint)' : 'var(--ink3)';
      s += `<svg width="13" height="15" viewBox="0 0 13 15" fill="none" stroke="${color}" stroke-width="1.600" opacity="${on ? 1 : 0.75}"><path d="M4 .8H.8v13.400H4M9 .8h3.200v13.400H9"/>${on ? '<rect x="4" y="4" width="5" height="7" fill="var(--tint)" stroke="none"/>' : ''}</svg>`;
    }
    return h('span', { class: 'marks', html: s, role: 'img', 'aria-label': `세 번 가운데 ${Math.min(c, GOAL)}번 알아봄` });
  }
  // phase: { kind: 'waiting' } | { kind: 'open', seconds } | { kind: 'closed', seconds, word, tone }
  function lane(phase, showMinimum, note) {
    const track = h('div', { class: 'track' });
    const fill = (width) => {
      track.querySelectorAll('.br,.secs,.word').forEach((n) => n.remove());
      if (phase.kind === 'waiting') track.append(h('div', { class: 'br' }, h('div', { class: 'side' }), h('div', { class: 'caret' })));
      else if (phase.kind === 'open') {
        const short = phase.seconds < MIN_S, length = Math.max(12, width * Math.min(phase.seconds, MAX_S) / MAX_S);
        track.append(h('div', { class: 'br open' + (short ? ' short' : ''), id: 'lane-open', style: `width:${length}px` }, h('div', { class: 'side' }), h('div', { class: 'edge' })),
          h('div', { class: 'secs' + (short ? ' short' : ''), id: 'lane-secs', style: `left:${length + 8}px` }, secs(phase.seconds)));
      } else {
        const length = Math.max(24, width * Math.min(phase.seconds, MAX_S) / MAX_S);
        track.append(h('div', { class: 'br closed ' + phase.tone, style: `width:${length}px` }, h('div', { class: 'side' }), h('div', { class: 'side right' })));
        // 괄호 안에 적고, 괄호가 짧으면 바로 뒤에 적는다
        const text = h('div', { class: 'word ' + phase.tone }, phase.word, phase.tone === 'unsure' && h('em', {}, '?'));
        track.append(text);
        text.style.left = text.offsetWidth + 30 <= length ? '15px' : `${length + 8}px`;
      }
    };
    const ticks = h('div', { class: 'ticks' }, ...[0, 1, 2, 3, 4, 5, 6].map((k) => h('i', { class: k % 2 === 0 ? 'major' : '', style: `left:${k === 6 ? 'calc(100% - 1.5px)' : (k / 6 * 100) + '%'}` })));
    const nums = h('div', { class: 'nums' }, h('span', { style: 'left:0' }, '0'), showMinimum && h('span', { style: 'left:16.667%' }, '최소 0.5'),
      h('span', { style: 'left:33.333%' }, '1'), h('span', { style: 'left:66.667%' }, '2'), h('span', { style: 'left:100%' }, '3초'));
    const n = h('div', { class: 'lane', role: 'img', 'aria-label': '시간 줄' }, h('div', { class: 'lane-note' }, note || ''), track, ticks, nums);
    requestAnimationFrame(() => fill(track.clientWidth));
    setTimeout(() => { if (!track.querySelector('.br')) fill(track.clientWidth); }, 60);   // 화면이 가려져 있으면 rAF가 안 온다
    n.fillNow = () => fill(track.clientWidth);
    return n;
  }
  function legend(rightSeen, leftSeen, leftFirst) {
    const item = (right, seen) => h('span', { class: (right ? 'r' : 'l') + (seen ? '' : ' gone') }, h('i'), (right ? '오른손' : '왼손') + (seen ? '' : ' 안 보임'));
    return h('div', { class: 'legend', id: 'legend' }, leftFirst ? [item(false, leftSeen), item(true, rightSeen)] : [item(true, rightSeen), item(false, leftSeen)]);
  }
  const HINT = { closer: ['조금 더 가까이 서 주세요', '조금 더 가까이 비춰 주세요'], farther: ['조금 더 뒤로 가 주세요', '조금 더 멀리서 비춰 주세요'],
    moveLeft: ['화면 가운데에 서 주세요', '사람이 가운데에 오게 비춰 주세요'], moveRight: ['화면 가운데에 서 주세요', '사람이 가운데에 오게 비춰 주세요'] };
  const hintText = (selfView) => (HINT[model.guide] ? HINT[model.guide][selfView ? 0 : 1] : null);
  const message = (title, detail) => h('div', { class: 'message' }, h('b', {}, title), h('span', {}, detail));
  function stageMessage(selfView) {
    if (model.setup === 'cameraDenied') return message('카메라를 쓸 수 없어요', '설정에서 카메라를 허용하면 수어를 읽을 수 있습니다. 영상은 저장하지 않습니다.');
    if (model.setup === 'failed') return message('카메라를 시작하지 못했어요', model.failText);
    if (model.setup === 'starting') return message('준비하는 중', model.failText || '손과 몸의 점을 읽을 준비를 하고 있어요.');
    if (model.nobody) return message('사람이 보이지 않아요', selfView ? '얼굴과 두 손이 화면에 들어오게 서 주세요.' : '수어하는 사람의 얼굴과 두 손이 화면에 들어오게 비춰 주세요.');
    return null;
  }
  const sheetHeight = (base, min) => Math.min(base, Math.max(min, $('app').clientHeight - 150));

  // ── 사람 도식 (FigureView.swift): 영상은 쓰지 않고 손과 몸의 점만으로 그린다
  const PALM = [0, 1, 5, 9, 13, 17], FINGERS = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16], [17, 18, 19, 20]];
  function cameraMap(aspect, w, hh, flipX) {
    const height = Math.max(hh, Math.min(w / aspect, hh / 0.78)), width = height * aspect, x0 = (w - width) / 2;
    return (p) => ({ x: x0 + (flipX ? 1 - p.x : p.x) * width, y: p.y * height, x0, width });
  }
  function drawFigure(canvas) {
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), w = canvas.clientWidth, hh = canvas.clientHeight;   // 3배 화면에서도 2배로만 그린다 (그리는 넓이가 절반 아래로 준다)
    if (!w || !hh) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(hh * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(hh * dpr); }
    const g = canvas.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, hh);
    const pose = shown();
    if (model.setup !== 'ready' || model.nobody || !pose) return;
    const selfView = !!view.practice;
    const map = cameraMap(model.aspect, w, hh, selfView ? false : model.facing !== 'user');
    const C = { chalk: '#f2f7f3', chalk2: '#b8d4c6', cloth: '#27583f', board: '#1b4332', right: '#f4d35e', left: '#9ad4f5' };
    const joint = (i) => (pose.body[i] ? map(pose.body[i]) : null);
    const line = (pts, color, width, dash) => { g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y))); g.strokeStyle = color; g.lineWidth = width; g.lineCap = 'round'; g.lineJoin = 'round'; g.setLineDash(dash || []); g.stroke(); g.setLineDash([]); };
    const dot = (p, r, color, strokeOnly, lw) => { g.beginPath(); g.arc(p.x, p.y, r, 0, Math.PI * 2); if (strokeOnly) { g.strokeStyle = color; g.lineWidth = lw; g.stroke(); } else { g.fillStyle = color; g.fill(); } };

    // 자리 안내 상자의 양 끝 (가운데 60%)
    if (model.guide !== 'ok') {
      const m0 = map({ x: 0, y: 0 }), x0 = Math.max(14, m0.x0 + 0.2 * m0.width), x1 = Math.min(w - 14, m0.x0 + 0.8 * m0.width), top = hh * 0.34, bottom = hh * 0.8;
      g.strokeStyle = C.chalk2; g.lineWidth = 2; g.setLineDash([5, 4]); g.lineCap = 'butt'; g.lineJoin = 'miter';
      g.beginPath(); g.moveTo(x0 + 12, top); g.lineTo(x0, top); g.lineTo(x0, bottom); g.lineTo(x0 + 12, bottom);
      g.moveTo(x1 - 12, top); g.lineTo(x1, top); g.lineTo(x1, bottom); g.lineTo(x1 - 12, bottom); g.stroke(); g.setLineDash([]);
    }
    const ls = joint(11), rs = joint(12);
    if (!ls || !rs) return;
    const d = Math.hypot(ls.x - rs.x, ls.y - rs.y);
    if (d <= 3) return;
    // 몸통: 어깨에서 허리쯤까지의 면
    const a = ls.x < rs.x ? ls : rs, b = ls.x < rs.x ? rs : ls, bottom = Math.max(a.y, b.y) + d * 1.75;
    g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.lineTo(b.x - d * 0.1, bottom); g.lineTo(a.x + d * 0.1, bottom); g.closePath();
    g.fillStyle = C.cloth; g.fill(); g.strokeStyle = C.cloth; g.lineWidth = d * 0.16; g.lineJoin = 'round'; g.stroke();
    // 목과 머리
    const le = joint(7), re = joint(8);
    if (le && re) {
      const e = Math.max(Math.hypot(le.x - re.x, le.y - re.y), d * 0.3), c = { x: (le.x + re.x) / 2, y: (le.y + re.y) / 2 - 0.07 * e };
      line([{ x: (ls.x + rs.x) / 2, y: (ls.y + rs.y) / 2 }, { x: c.x, y: c.y + 0.6 * e }], C.cloth, d * 0.26);
      const lw = clamp(d * 0.028, 1.4, 3.6);
      g.beginPath(); g.ellipse(c.x, c.y, 0.6 * e, 0.8 * e, 0, 0, Math.PI * 2); g.fillStyle = C.cloth; g.fill(); g.strokeStyle = C.chalk; g.lineWidth = lw; g.stroke();
      for (const i of [2, 5]) { const eye = joint(i); if (eye) dot(eye, Math.max(1, e * 0.04), C.chalk); }
      const m1 = joint(9), m2 = joint(10);
      if (m1 && m2) line([m1, m2], C.chalk, Math.max(1, lw * 0.8));
    }
    // 읽는 동안 손목이 지나간 길
    if (model.isReading) {
      const trail = (raw, right) => {
        if (raw.length < 3) return;
        let pts = raw.map(map);
        for (let k = 0; k < 2; k++) pts = pts.map((p, i) => { const q = pts[Math.max(i - 1, 0)], r = pts[Math.min(i + 1, pts.length - 1)]; return { x: (q.x + p.x * 2 + r.x) / 4, y: (q.y + p.y * 2 + r.y) / 4 }; });
        let len = 0; for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
        if (len < 24) return;
        if (right) line(pts, C.right, 2); else line(pts, C.left, 2.6, [0.1, 6]);
      };
      model.trail.right.forEach((r) => trail(r, true)); model.trail.left.forEach((r) => trail(r, false));
    }
    // 팔. 손이 잡혔으면 팔 끝을 그 손목에 맞춘다
    const wristEnd = {};
    for (const hand of [pose.right, pose.left]) {
      if (!hand) continue;
      const wp = map(hand[0]); let near = null;
      for (const i of [15, 16]) { const j = joint(i); if (j) { const dist = Math.hypot(j.x - wp.x, j.y - wp.y); if (!near || dist < near[1]) near = [i, dist]; } }
      if (near && !wristEnd[near[0]]) wristEnd[near[0]] = wp;
    }
    const armWidth = clamp(d * 0.075, 2.4, 12);
    for (const [s, e, wi] of [[11, 13, 15], [12, 14, 16]]) {
      const p0 = joint(s), p1 = joint(e);
      if (!p0 || !p1) continue;
      const p2 = wristEnd[wi] || joint(wi);
      line(p2 ? [p0, p1, p2] : [p0, p1], C.chalk, armWidth);
    }
    // 안 잡힌 손은 손목 자리에 흐린 표시만 남긴다 (화면에서는 Pose 15번이 실제 오른손목이다)
    const mark = armWidth * 0.8;
    g.globalAlpha = 0.42; if (!pose.right && !wristEnd[15] && joint(15)) dot(joint(15), mark, C.right);
    g.globalAlpha = 0.6; if (!pose.left && !wristEnd[16] && joint(16)) dot(joint(16), mark, C.left, true, 1.6);
    g.globalAlpha = 1;
    const hand = (pts, right) => {
      const p = pts.map(map), finger = clamp(Math.hypot(p[5].x - p[17].x, p[5].y - p[17].y) * 0.26, 1.6, 9);
      const paint = (color, width) => {
        g.beginPath(); PALM.forEach((i, k) => (k ? g.lineTo(p[i].x, p[i].y) : g.moveTo(p[i].x, p[i].y))); g.closePath();
        g.fillStyle = color; g.fill(); g.strokeStyle = color; g.lineWidth = width; g.lineCap = 'round'; g.lineJoin = 'round'; g.stroke();
        g.beginPath(); for (const fi of FINGERS) fi.forEach((i, k) => (k ? g.lineTo(p[i].x, p[i].y) : g.moveTo(p[i].x, p[i].y))); g.stroke();
      };
      if (right) paint(C.right, finger * 1.25);
      else { const edge = clamp(finger * 0.22, 1.1, 1.8); paint(C.left, finger * 1.25 + edge * 2); paint(C.board, finger * 1.25); }   // 속이 빈 손
    };
    if (pose.left) hand(pose.left, false);
    if (pose.right) hand(pose.right, true);
  }

  // 매 프레임 바뀌는 것만 고친다 (사람 도식, 손 표시, 열린 괄호의 길이)
  function live() {
    if (performance.now() - rafAt > 250) drawFigure($('figure'));   // 화면 갱신 신호가 안 올 때(창이 가려짐)만 여기서 그린다
    const lg = $('legend');
    if (lg && lg.dataset.live) {
      const state = (model.rightVisible ? 'R' : 'r') + (model.leftVisible ? 'L' : 'l');
      if (lg.dataset.state !== state) { const again = liveLegend(lg.dataset.leftFirst === '1'); lg.replaceWith(again); }
    }
    const open = $('lane-open');
    if (open && model.isReading) {
      const width = open.parentNode.clientWidth, short = model.elapsed < MIN_S, length = Math.max(12, width * Math.min(model.elapsed, MAX_S) / MAX_S);
      open.style.width = length + 'px'; open.classList.toggle('short', short);
      const s = $('lane-secs'); s.style.left = (length + 8) + 'px'; s.textContent = secs(model.elapsed); s.classList.toggle('short', short);
    }
  }
  const liveLegend = (leftFirst) => { const n = legend(model.rightVisible, model.leftVisible, leftFirst); n.dataset.live = '1'; n.dataset.leftFirst = leftFirst ? '1' : '0';
    n.dataset.state = (model.rightVisible ? 'R' : 'r') + (model.leftVisible ? 'L' : 'l'); if (model.setup !== 'ready') n.style.opacity = '.5'; return n; };

  // ── 화면
  function translateScreen() {
    const blocked = model.setup !== 'ready' || model.nobody, front = model.facing === 'user';
    const hint = model.setup === 'ready' && !model.nobody ? hintText(front) : null;
    const stage = h('div', { class: 'stage' }, stageFigure(), stageMessage(false),
      h('div', { class: 'over' }, h('div', { class: 'top' }, liveLegend(front), h('div', { class: 'grow' }),
        h('button', { class: 'glass', disabled: model.setup !== 'ready' || model.isReading, 'aria-label': front ? '뒤쪽 카메라로 바꾸기' : '앞쪽 카메라로 바꾸기',
          onclick: () => cmd({ type: 'camera', facing: front ? 'environment' : 'user' }) }, icon('camera'))),
        hint && h('div', { class: 'hint' }, hint)));
    const hero = model.latest && model.latest.token ? token(model.latest.token) : null;
    const written = h('div', { class: 'fit' + (!model.latest && !model.isReading && !model.tokens.length ? ' middle' : '') });
    if (model.isReading) {
      written.append(h('p', { class: 'h2', style: 'color:var(--ink2);margin-top:10px' }, '읽는 중'), h('p', { class: 'sub', style: 'margin-top:8px' }, '단추를 다시 누르면 괄호가 닫히고 낱말이 적혀요.'));
    } else {
      if (model.tokens.length) {
        const past = model.tokens.filter((t) => !hero || t.id !== hero.id);
        const rowEl = h('div', { style: 'flex:1 1 0;min-width:0;display:flex;gap:12px;overflow-x:auto;padding:0 10px;scrollbar-width:none' },
          ...past.map((t) => h('button', { style: 'min-height:44px;flex:none', onclick: () => openDetail(t) }, gloss(t.word, 17, t.sure ? 'normal' : 'unsure', 600))));
        written.append(h('div', { class: 'row', style: 'gap:0;min-height:44px;flex:none' }, h('b', {}, '읽은 수어'), rowEl,
          h('button', { class: 'text', style: 'margin-right:-10px', onclick: () => { model.tokens = []; model.latest = null; model.tooShort = false; render(); } }, '지우기')));
        requestAnimationFrame(() => { rowEl.scrollLeft = rowEl.scrollWidth; });
      }
      if (hero) {
        const status = hero.sure ? h('span', { class: 'sub num' }, hero.corrected ? secs(hero.reading.seconds) : `${secs(hero.reading.seconds)} · ${pct(hero.reading.top.probability)}`)
          : h('span', { class: 'sub num', style: 'color:var(--warn);font-weight:600' }, `확실하지 않아요 · ${pct(hero.reading.top.probability)}`);
        written.append(h('div', { class: 'row', style: 'min-height:58px;flex:none' },
          h('button', { style: 'min-height:52px', 'aria-label': hero.word + ', 자세히 봅니다', onclick: () => openDetail(hero) }, gloss(hero.word, 34, hero.sure ? 'normal' : 'unsure')), h('div', { class: 'spacer' }), status));
        if (hero.sure) written.append(h('p', { class: 'sub', style: 'min-height:48px;display:flex;align-items:center;flex:none' }, view.tipSeen ? ' ' : '낱말을 누르면 자세히 볼 수 있어요.'));
        else written.append(h('div', { class: 'chips', style: 'min-height:48px;flex:none' },   // 확실하지 않을 때는 고칠 길을 바로 옆에 둔다
          h('button', { class: 'chip primary', onclick: () => setWord(hero.word, hero.id) }, hero.word),
          ...hero.reading.alternatives.map((w) => h('button', { class: 'chip', onclick: () => setWord(w, hero.id) }, w)),
          h('button', { class: 'text', onclick: () => removeToken(hero.id) }, '다시 읽기')));
      } else if (model.latest && model.latest.unread) {
        written.append(h('div', { class: 'row', style: 'min-height:58px;flex:none' }, gloss('?', 34, 'muted'), h('div', { class: 'spacer' }), h('span', { class: 'sub num' }, secs(model.latest.seconds))),
          h('p', { class: 'sub', style: 'min-height:48px;flex:none' }, model.latest.unread === 'hands_unseen' ? '손이 잘 보이지 않아 읽지 못했어요. 더 가까이에서 다시 눌러 주세요.'
            : `아는 낱말과 맞지 않아요. 지금은 ${model.words.join('·')}만 읽을 수 있어요.`));
      } else if (!model.tokens.length) {
        written.append(h('div', { style: 'display:flex;flex-direction:column;gap:8px;padding:8px 0' }, h('p', { class: 'h2', style: 'white-space:pre-line' }, '단추를 눌러 시작하고,\n다시 눌러 끝내세요'),
          h('p', { class: 'sub' }, '3초가 지나면 저절로 끝납니다. 영상은 저장하지 않고, 손과 몸의 점만 읽습니다.'),
          model.words.length ? h('p', { class: 'foot' }, '읽을 수 있는 낱말: ' + model.words.join(' · ')) : null));
      }
    }
    const phase = model.isReading ? { kind: 'open', seconds: model.elapsed }
      : hero ? { kind: 'closed', seconds: hero.reading.seconds, word: hero.word, tone: hero.sure ? 'normal' : 'unsure' }
        : model.latest && model.latest.unread ? { kind: 'closed', seconds: model.latest.seconds, word: '?', tone: 'muted' } : { kind: 'waiting' };
    const sheet = h('div', { class: 'sheet', style: `height:${sheetHeight(358, 280)}px` }, written,
      h('div', { style: 'padding-top:6px' }, lane(phase, true, model.tooShort ? '너무 짧아요. 0.5초가 지난 뒤에 끝내 주세요' : null)),
      h('div', { class: 'read-wrap' }, h('button', { class: 'read' + (model.isReading ? ' on' : ''), disabled: blocked && !model.isReading, onclick: toggleRead,
        'aria-label': model.isReading ? '읽기 끝내기' : '읽기 시작' }, icon(model.isReading ? 'stop' : 'pair'))));
    return h('div', { class: 'screen' }, stage, sheet);
  }

  function still(word, frame, mirror) {
    const frames = DEMOS[word];
    return frames ? h('img', { src: frames[clamp(frame, 0, frames.length - 1)], class: mirror ? 'mirror-img' : '', alt: '' }) : null;
  }
  function learnScreen() {
    const words = model.words.length ? model.words : Object.keys(DEMOS);
    const open = words.filter((w) => count(w) < GOAL);
    const next = open.find((w) => count(w) > 0) || open.find((w) => DEMOS[w]) || open[0];
    const learned = words.filter((w) => count(w) >= GOAL).length;
    const list = h('div', { class: 'list' }, h('h1', {}, '학습'),
      h('p', { class: 'sub', style: 'margin:0 4px' }, words.length ? `배울 수 있는 낱말 ${words.length}개 중 ${learned}개를 익혔어요` : '낱말 목록을 읽지 못했어요.'));
    if (next) {
      list.append(h('h2', {}, count(next) > 0 ? '이어서 하기' : '먼저 해 보기'),
        h('div', { class: 'group' }, h('button', { style: 'padding:12px 16px', onclick: () => openLesson(next) },
          h('div', { class: 'card', style: 'flex:1 1 0;min-width:0' }, h('div', { class: 'thumb' }, DEMOS[next] ? still(next, keyFrames(DEMOS[next].length)[2], false) : icon('pairBig')),
            h('div', { style: 'display:flex;flex-direction:column;gap:6px;align-items:flex-start' }, gloss(next, 22), h('span', { class: 'foot' }, progressText(count(next))), marksView(count(next)))),
          h('span', { html: ICON.chev }))));
    }
    list.append(h('h2', {}, '낱말'), h('div', { class: 'group' }, ...words.map((w) => h('button', { onclick: () => openLesson(w) }, h('span', {}, w), h('div', { class: 'spacer' }), marksView(count(w)), h('span', { html: ICON.chev })))));
    return h('div', { class: 'screen' }, list);
  }

  // 낱말 배우기 (LessonView.swift): 위에서 본보기를 되풀이해 보여 주고, 아래에서 진도와 동작 순서를 보여 준다
  let playTimer = null;
  function openLesson(word) { view.lesson = { word, frame: 0, playing: true, slow: false, mirror: true }; render(); schedule(); }
  function closeLesson() { clearTimeout(playTimer); view.lesson = null; render(); }
  function schedule() {
    clearTimeout(playTimer);
    const l = view.lesson, frames = l && DEMOS[l.word];
    if (!l || !frames || !l.playing || view.practice) return;
    const step = 1000 / 15 / (l.slow ? 0.4 : 1), atEnd = l.frame >= frames.length - 1;
    playTimer = setTimeout(() => {
      if (view.lesson !== l) return;
      l.frame = atEnd ? 0 : l.frame + 1;
      const img = $('demo'); if (img) img.src = frames[l.frame];
      schedule();
    }, atEnd ? step + 700 : step);   // 끝에서 잠깐 멈췄다가 처음으로 돌아간다
  }
  function lessonScreen() {
    const l = view.lesson, frames = DEMOS[l.word], c = count(l.word);
    const stage = h('div', { class: 'stage' });
    if (frames) {
      stage.append(h('img', { class: 'demo' + (l.mirror ? ' mirror' : ''), id: 'demo', src: frames[l.frame], alt: `${l.word} 본보기 동작` }));
    } else stage.append(message('이 낱말은 아직 본보기가 없어요', '동작을 알고 있다면 따라 하기로 확인해 볼 수 있어요.'));
    stage.append(h('div', { class: 'over', style: 'padding-bottom:22px' },
      h('div', { class: 'top' }, h('button', { class: 'glass', 'aria-label': '뒤로', onclick: closeLesson }, icon('back')), h('div', { class: 'grow' })),
      frames && h('div', { class: 'top', style: 'margin-top:-6px' }, h('div', { class: 'grow' }), legend(true, true, l.mirror)),
      h('div', { class: 'grow' }),
      frames && h('div', { class: 'pills' },
        h('button', { class: 'pill', 'aria-label': l.playing ? '멈춤' : '재생', onclick: () => { l.playing = !l.playing; render(); schedule(); } }, icon(l.playing ? 'pause' : 'play')),
        h('button', { class: 'pill' + (l.slow ? ' on' : ''), 'aria-pressed': String(l.slow), onclick: () => { l.slow = !l.slow; render(); schedule(); } }, '느리게'),
        h('button', { class: 'pill' + (l.mirror ? ' on' : ''), 'aria-pressed': String(l.mirror), onclick: () => { l.mirror = !l.mirror; render(); } }, '거울로 보기'))));
    const body = h('div', { class: 'fit' }, h('div', { style: 'padding-top:6px;flex:none' }, gloss(l.word)),
      h('div', { class: 'row', style: 'gap:8px;padding-top:6px;flex:none' }, marksView(c), h('span', { class: 'sub' }, progressText(c))));
    if (frames) {
      const keys = keyFrames(frames.length);
      let current = 0; keys.forEach((k, i) => { if (Math.abs(k - l.frame) < Math.abs(keys[current] - l.frame)) current = i; });
      body.append(h('p', { class: 'h3', style: 'padding-top:20px;flex:none' }, '동작 순서'),
        h('div', { class: 'steps', style: 'flex:none' }, ...keys.map((k, i) => h('button', { class: 'step' + (!l.playing && current === i ? ' now' : ''), 'aria-label': `동작 ${i + 1}`,
          onclick: () => { l.playing = false; l.frame = k; clearTimeout(playTimer); render(); } }, h('div', {}, still(l.word, k, l.mirror)), String(i + 1)))),
        h('p', { class: 'foot', style: 'padding-top:8px;flex:none' }, '여러 각도로 찍은 수어 영상의 동작을 사람 모형으로 옮긴 것이고, 수어 사용자의 확인을 받기 전이에요.'));
    }
    const sheet = h('div', { class: 'sheet', style: `height:${sheetHeight(frames ? 376 : 376 * 0.56, 200)}px` }, body,
      h('div', { style: 'padding:12px 0' }, h('button', { class: 'cta', onclick: () => openPractice(l.word) }, '따라 하기')));
    return h('div', { class: 'screen' }, stage, sheet);
  }

  function practiceScreen() {
    const p = view.practice, c = count(p.word), m = p.reading;
    const hint = model.setup === 'ready' && !model.nobody ? hintText(true) : null;
    const stage = h('div', { class: 'stage' }, stageFigure(), stageMessage(true),
      h('div', { class: 'over' }, h('div', { class: 'top' }, h('button', { class: 'glass', 'aria-label': '닫기', onclick: closePractice }, icon('close')), h('div', { class: 'grow' }), liveLegend(true)),
        hint && h('div', { class: 'hint' }, hint)),
      p.step === 'counting' && h('div', { class: 'count', 'aria-hidden': 'true' }, String(p.n)));
    const g = p.step === 'success' ? gloss(p.word) : p.step === 'failure' ? (p.why === 'other' ? gloss(p.read, 34, 'muted') : p.why === 'unsure' ? gloss(p.word, 34, 'unsure') : gloss('?', 34, 'muted')) : gloss(p.word, 34, 'muted');
    const badge = p.step === 'success' ? h('span', { class: 'badge', style: 'color:var(--tint)' }, icon('check'), '알아봤어요')
      : p.step !== 'failure' ? null
        : p.why === 'other' ? h('span', { class: 'badge', style: 'color:var(--bad)' }, icon('alert'), '다르게 읽었어요')
          : p.why === 'unsure' ? h('span', { class: 'badge', style: 'color:var(--warn)' }, icon('alert'), '확실하지 않아요')
            : h('span', { class: 'badge', style: 'color:var(--bad)' }, icon('alert'), '읽지 못했어요');
    let text;
    if (p.step === 'ready') text = '휴대폰을 세워 두고 시작을 누르세요. 셋을 센 뒤 손을 올려 수어를 하면 읽기 시작해요.';
    else if (p.step === 'counting') text = '얼굴과 두 손이 화면에 들어오게 서 주세요.';
    else if (p.step === 'armed') text = model.isReading ? '읽는 중이에요. 다 하면 손을 내려 주세요.' : '지금 수어를 해 보세요. 손을 내리면 읽기가 끝나요.';
    else if (p.step === 'success') {
      const right = ratio(m.rightSeen), left = ratio(m.leftSeen);
      text = Math.min(right, left) < 0.5 ? `${right < left ? '오른손' : '왼손'}이 ${pct(Math.min(right, left))}만 보였어요. 다음에는 조금 더 가까이 서 보세요.` : `확률 ${pct(m.top.probability)}로 읽었어요.`;
    } else if (p.why === 'noHands') text = '손이 보이지 않았어요. 두 손이 화면에 들어오게 서서 다시 해 보세요.';
    else if (p.why === 'handsUnseen') text = `읽는 동안 손이 ${m ? pct(1 - m.handMissing) : '절반 아래'}만 보였어요. 조금 더 가까이 와서 다시 해 보세요.`;
    else if (p.why === 'unknown') text = DEMOS[p.word] ? '아는 낱말로 읽지 못했어요. 본보기를 다시 보고 해 보세요.' : '아는 낱말로 읽지 못했어요. 동작을 천천히 다시 해 보세요.';
    else if (p.why === 'other') text = `${p.word} 대신 ${withRo(p.read)} 읽었어요. 동작을 다시 확인해 보세요.`;
    else text = `${withRo(p.word)} 읽었지만 확률이 ${m ? pct(m.probabilities[p.word] || 0) : ''}라서 세지 않았어요. 한 번 더 해 보세요.`;
    const phase = p.step === 'armed' && model.isReading ? { kind: 'open', seconds: model.elapsed }
      : p.step === 'success' ? { kind: 'closed', seconds: m.seconds, word: p.word, tone: 'normal' }
        : p.step === 'failure' && m ? (p.why === 'other' ? { kind: 'closed', seconds: m.seconds, word: p.read, tone: 'muted' } : p.why === 'unsure' ? { kind: 'closed', seconds: m.seconds, word: p.word, tone: 'unsure' } : { kind: 'closed', seconds: m.seconds, word: '?', tone: 'muted' })
          : { kind: 'waiting' };
    const done = p.step === 'success' || p.step === 'failure', busy = p.step === 'counting' || p.step === 'armed';
    const title = { ready: '시작', counting: '준비', armed: '읽는 중', success: '한 번 더', failure: '다시 하기' }[p.step];
    const sheet = h('div', { class: 'sheet', style: `height:${sheetHeight(400, 300)}px;padding-bottom:var(--sab)` },
      h('div', { class: 'fit' }, h('div', { class: 'row', style: 'min-height:58px;flex:none' }, g, h('div', { class: 'spacer' }), badge),
        h('div', { class: 'row', style: 'gap:8px;flex:none' }, marksView(c), h('span', { class: 'sub' }, progressText(c))),
        h('p', { class: 'sub', style: 'padding-top:10px;flex:none', role: 'status' }, text)),
      h('div', { style: 'padding-top:6px' }, lane(phase, false, null)),
      h('div', { style: 'padding:12px 0 8px' }, h('button', { class: 'cta', disabled: busy || model.setup !== 'ready', onclick: startPractice }, title),
        h('button', { class: 'text wide', style: `margin-top:2px;${done ? '' : 'visibility:hidden'}`, disabled: !done, onclick: closePractice }, '마치기')));
    return h('div', { class: 'cover' }, stage, sheet);
  }

  // 낱말 자세히 (TokenDetailView.swift): 읽는 동안 오른손·왼손·몸이 보인 구간을 한 시간 줄에 놓아 보여 주고, 고치거나 지울 수 있다
  function openDetail(t) { view.tipSeen = true; store.set('detailTipSeen', true); view.detail = t.id; render(); }
  function bars(canvas, seen, kind) {
    const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, hh = 14;
    canvas.width = w * dpr; canvas.height = hh * dpr;
    const g = canvas.getContext('2d'); g.scale(dpr, dpr);
    const rr = (x, y, ww, h2, r) => { g.beginPath(); g.roundRect ? g.roundRect(x, y, ww, h2, r) : g.rect(x, y, ww, h2); };
    g.fillStyle = 'rgba(255,255,255,.16)'; rr(0, hh / 2 - 1, w, 2, 1); g.fill();
    if (!seen.length) return;
    const step = w / seen.length; let start = null;
    for (let i = 0; i <= seen.length; i++) {
      const on = i < seen.length && seen[i];
      if (on && start === null) start = i;
      if (on || start === null) continue;
      const x = start * step, ww = Math.max(3, (i - start) * step); start = null;
      if (kind === 'right') { g.fillStyle = '#f4d35e'; rr(x, 0, ww, hh, 3); g.fill(); }
      else if (kind === 'left') { g.fillStyle = '#1b4332'; rr(x, 0, ww, hh, 3); g.fill(); g.strokeStyle = '#9ad4f5'; g.lineWidth = 1.8; rr(x + 0.9, 0.9, ww - 1.8, hh - 1.8, 2.4); g.stroke(); }
      else { g.fillStyle = '#f2f7f3'; rr(x, 0, ww, hh, 3); g.fill(); }
    }
  }
  function axis(canvas, seconds) {
    const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth;
    canvas.width = w * dpr; canvas.height = 24 * dpr;
    const g = canvas.getContext('2d'); g.scale(dpr, dpr);
    const total = Math.max(seconds, 0.5);
    g.strokeStyle = '#b8d4c6'; g.fillStyle = '#b8d4c6'; g.lineWidth = 1.2; g.font = '11px -apple-system, "Noto Sans KR", sans-serif'; g.textBaseline = 'top';
    for (let k = 0; k * 0.5 <= total + 0.001; k++) {
      const major = k % 2 === 0, x = clamp(w * (k * 0.5 / total), 0.6, w - 0.6);
      g.beginPath(); g.moveTo(x, 0); g.lineTo(x, major ? 7 : 4); g.stroke();
      if (major) { g.textAlign = k === 0 ? 'left' : 'center'; g.fillText(k === 0 ? '0' : `${k / 2}초`, x, 10); }
    }
  }
  function detailSheet() {
    const t = token(view.detail);
    if (!t) { view.detail = null; return null; }
    const r = t.reading, close = () => { view.detail = null; render(); };
    const canvases = { right: h('canvas'), left: h('canvas'), body: h('canvas'), axis: h('canvas', { class: 'axis' }) };
    const rows = [['걸린 시간', secs(r.seconds)], ['오른손이 보인 시간', pct(ratio(r.rightSeen))], ['왼손이 보인 시간', pct(ratio(r.leftSeen))],
      t.corrected ? ['처음 읽은 낱말', `${r.top.word} ${pct(r.top.probability)}`] : ['확률', pct(r.top.probability)]];
    const others = r.ranking.map((c) => c.word).filter((w) => w !== '기타' && w !== t.word);
    const sheet = h('div', { class: 'detail', role: 'dialog', 'aria-modal': 'true', onclick: (e) => e.stopPropagation() }, h('div', { class: 'grab' }),
      h('div', { class: 'row', style: 'min-height:56px;padding:0 4px' }, gloss(t.word, 28, t.sure ? 'normal' : 'unsure'), h('div', { class: 'spacer' }),
        h('button', { class: 'text strong', style: 'margin-right:-10px', onclick: close }, '완료')),
      h('div', { class: 'plate', role: 'img', 'aria-label': `읽는 동안 보인 구간. 오른손 ${pct(ratio(r.rightSeen))}, 왼손 ${pct(ratio(r.leftSeen))}` },
        h('span', {}, '낱말'), h('div', { class: 'wordbar' }, t.word), h('span', {}, '오른손'), canvases.right, h('span', {}, '왼손'), canvases.left, h('span', {}, '몸'), canvases.body, h('span'), canvases.axis),
      h('div', { class: 'facts' }, ...rows.map(([a, b]) => h('div', {}, h('span', {}, a), h('span', {}, b)))),
      others.length ? h('p', { style: 'font-weight:600;margin:22px 4px 2px' }, '다른 낱말로 고치기') : null,
      others.length ? h('div', { class: 'chips' }, ...others.map((w) => h('button', { class: 'chip on-row', onclick: () => setWord(w, t.id) }, w))) : null,
      h('button', { class: 'rowbtn', onclick: () => { view.detail = null; removeToken(t.id); } }, '이 낱말 지우기'));
    const paint = () => { bars(canvases.right, r.rightSeen, 'right'); bars(canvases.left, r.leftSeen, 'left'); bars(canvases.body, r.bodySeen, 'body'); axis(canvases.axis, r.seconds); };
    requestAnimationFrame(paint); setTimeout(paint, 80);
    return h('div', { class: 'scrim', onclick: close }, sheet);
  }

  // 처음 켰을 때 한 번 받는 데이터 사용 동의 (SyncViews.swift)
  function consentSheet() {
    const item = (title, text) => h('div', {}, h('h3', {}, title), h('p', {}, text));
    const key = !NATIVE ? h('input', { type: 'password', placeholder: '팀에서 받은 서버 키 (없으면 비워 두세요)', autocomplete: 'off', 'aria-label': '서버 키' }) : null;
    return h('div', { class: 'consent', role: 'dialog', 'aria-modal': 'true' }, h('div', { class: 'scroll' }, h('h1', {}, '학습 데이터로\n앱을 고쳐 갑니다'),
      item('보내는 것', '어떤 낱말을 연습했고 앱이 어떻게 읽었는지, 그리고 수어 동작의 좌표(손과 몸의 점). 이름 없이 임의의 번호로 보냅니다.'),
      item('어디에 쓰나', '앱이 수어를 더 잘 읽도록 다시 학습시키는 데 씁니다.'),
      item('보내지 않는 것', '카메라 영상과 사진, 이름. 영상은 폰에도 저장하지 않습니다.'),
      h('p', { class: 'sub' }, '동의해야 앱을 쓸 수 있어요.'), key),
    h('div', { class: 'cta-wrap' }, h('button', { class: 'cta', onclick: () => { if (key) { sync.key = key.value.trim(); store.set('sync.key', sync.key); } sync.agreed = true; store.set('sync.agreed', true); render(); flush(); } }, '동의하고 시작하기')));
  }

  function tabbar() {
    const tab = (key, label, ic) => h('button', { role: 'tab', 'aria-selected': String(view.tab === key), onclick: () => { if (view.tab === key && key === 'learn' && view.lesson) closeLesson(); else { view.tab = key; render(); schedule(); } } }, icon(ic), label);
    return h('div', { class: 'tabbar' + (view.tab === 'learn' && !view.lesson ? ' grouped' : '') }, h('nav', { role: 'tablist' }, tab('translate', '번역', 'tabTranslate'), tab('learn', '학습', 'tabLearn')));
  }

  function render() {
    const app = $('app');
    if (!app) return;
    const focusKey = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute('aria-label');
    const screen = view.tab === 'translate' ? translateScreen() : view.lesson ? lessonScreen() : learnScreen();
    app.replaceChildren(...[screen, tabbar(), view.practice ? practiceScreen() : null, view.detail ? detailSheet() : null, !sync.agreed ? consentSheet() : null].filter(Boolean));
    // 카메라를 쓰는 화면(번역, 따라 하기)에서만 좌표를 뽑는다. 목록과 본보기 화면에서는 쉬게 해서 화면이 끊기지 않게 한다
    const needCamera = view.tab === 'translate' || !!view.practice;
    if (needCamera !== cameraOn) { cameraOn = needCamera; cmd({ type: 'pause', on: !needCamera }); }
    app.querySelectorAll('.lane').forEach((n) => n.fillNow());
    if (focusKey) { const again = app.querySelector(`[aria-label="${focusKey}"]`); if (again && again.focus) again.focus({ preventScroll: true }); }
    live();
  }

  // 안드로이드의 뒤로 단추: 열려 있는 것부터 닫는다. 닫을 것이 없으면 false (앱이 물러난다)
  window.KSLBack = () => {
    if (view.detail) { view.detail = null; render(); return true; }
    if (view.practice) { closePractice(); return true; }
    if (view.lesson && view.tab === 'learn') { closeLesson(); return true; }
    if (view.tab === 'learn') { view.tab = 'translate'; render(); return true; }
    return false;
  };
  window.addEventListener('resize', render);
  window.addEventListener('pagehide', () => { if (view.practice) closePractice(); flush(); });
  document.addEventListener('DOMContentLoaded', () => { render(); if (sync.agreed) flush(); });
})();
