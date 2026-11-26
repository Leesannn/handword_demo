// 수어 칠판의 판정 엔진. 아이폰 앱(~/sign-app/ios/KSLSign/Core, ios-board/Engine)과 같은 규격이다.
// 여기를 바꾸면 모델과 맞지 않는다. 고친 뒤에는 `node tools/test_core.mjs`로 기준값과 같은지 확인한다.
// 웹뷰 페이지와 node 시험이 같은 파일을 쓴다 (import 없이 전역 KSL 하나만 만든다).
(function (root) {
  const POINTS = 59, VALUES = POINTS * 3, FRAMES = 30, HAND = 21;
  const RIGHT_LABEL = 0, LEFT_LABEL = 21, POSE = 42, POSE_POINTS = 17;
  const L_SHOULDER = 11, R_SHOULDER = 12, L_WRIST = 15, R_WRIST = 16;
  const MIN_SECONDS = 0.5, MAX_SECONDS = 3.0, MISSING_WARN = 0.5, SURE_AT = 0.6, OTHER = '기타';
  const f = Math.fround;

  // MediaPipe 결과 → 177개 값. 어깨 폭이 가장 큰 사람 한 명과 그 사람 손목 가까이의 손만 쓴다 (FrameBuilder.swift)
  function buildFrame(hands, poses, width, height) {
    const values = new Array(VALUES).fill(NaN);
    const dist = (a, b) => Math.hypot((a.x - b.x) * width, (a.y - b.y) * height);
    let person = null, size = 0;
    for (const p of poses) {
      const s = dist(p[L_SHOULDER], p[R_SHOULDER]) / width;
      if (s >= 0.10 && s > size) { person = p; size = s; }
    }
    if (!person) return { values, person: null, hands: 0 };
    const put = (p, at) => { values[at * 3] = p.x; values[at * 3 + 1] = p.y; values[at * 3 + 2] = p.z; };
    for (let i = 0; i < POSE_POINTS; i++) put(person[i], POSE + i);
    const reach = size * width, slots = {};
    for (const hand of hands) {
      const d = Math.min(dist(hand.points[0], person[L_WRIST]), dist(hand.points[0], person[R_WRIST]));
      if (d > reach) continue;
      const start = hand.label === 'Right' ? RIGHT_LABEL : hand.label === 'Left' ? LEFT_LABEL : -1;
      if (start < 0) continue;
      if (slots[start] && slots[start].score >= hand.score) continue;
      slots[start] = hand;
    }
    for (const start of Object.keys(slots)) {
      for (let i = 0; i < HAND; i++) put(slots[start].points[i], Number(start) + i);
    }
    return { values, person, hands: Object.keys(slots).length };
  }

  // 동작 구간 정하기 (Segmenter.swift). auto: 손이 2프레임 연속 보이면 시작, 0.4초 안 보이면 끝. button: 시작·끝을 누른다
  class Segmenter {
    constructor(mode) { this.mode = mode; this.reset(); }
    reset() { this.recording = false; this.frames = []; this.handRun = []; this.waitDown = false; this.startTime = 0; this.lastHand = 0; }
    setMode(mode) { this.mode = mode; this.reset(); }
    start(time) { if (this.mode === 'button' && !this.recording) { this.recording = true; this.startTime = time; } }
    stop(time) { return this.mode === 'button' && this.recording ? this.finish(time) : null; }
    add(time, values, hasHand) {
      this.frames.push({ time, values });
      if (!this.recording) this.frames = this.frames.filter((x) => x.time >= time - 1.5);
      if (this.mode === 'button') {
        if (!this.recording) return null;
        return time - this.startTime >= MAX_SECONDS ? this.finish(time) : null;
      }
      if (this.recording) {
        if (hasHand) this.lastHand = time;
        if (time - this.startTime >= MAX_SECONDS) { this.waitDown = true; return this.finish(time); }
        return !hasHand && time - this.lastHand >= 0.4 ? this.finish(this.lastHand) : null;
      }
      if (!hasHand) { this.handRun = []; this.waitDown = false; return null; }
      if (this.waitDown) return null;
      this.handRun.push(time);
      if (this.handRun.length < 2) return null;
      this.recording = true; this.startTime = this.handRun[0]; this.lastHand = time;
      return { type: 'started' };
    }
    finish(end) {
      this.recording = false; this.handRun = [];
      const kept = this.frames.filter((x) => x.time >= this.startTime - 1.0);
      const t0 = kept.length ? kept[0].time : this.startTime;
      const clip = { frames: kept.map((x) => x.values), times: kept.map((x) => x.time - t0), start: this.startTime - t0, end: end - t0 };
      const duration = clip.end - clip.start;
      if (duration < MIN_SECONDS || windowOf(clip).length < 2) return { type: 'tooShort', seconds: duration };
      return { type: 'clip', clip };
    }
  }

  function windowOf(clip) {
    return clip.frames.filter((_, i) => clip.times[i] >= clip.start && clip.times[i] <= clip.end);
  }

  // model_bundle/preprocess.py와 같다: 30프레임으로 맞추고 어깨 중심·너비로 정규화, 안 잡힌 점은 0
  function preprocess(seq, aspect) {
    const n = seq.length, step = (n - 1) / (FRAMES - 1), pts = new Float32Array(FRAMES * VALUES);
    for (let fi = 0; fi < FRAMES; fi++) {
      const src = seq[fi === FRAMES - 1 ? n - 1 : Math.floor(fi * step)];
      for (let v = 0; v < VALUES; v++) pts[fi * VALUES + v] = src[v] == null ? NaN : src[v];
    }
    const a = f(aspect);
    for (let fi = 0; fi < FRAMES; fi++) for (let p = 0; p < POINTS; p++) {
      pts[fi * VALUES + p * 3] *= a; pts[fi * VALUES + p * 3 + 2] *= a;
    }
    const l = (POSE + L_SHOULDER) * 3, r = (POSE + R_SHOULDER) * 3;
    const center = [], width = new Float32Array(FRAMES), valid = [];
    for (let fi = 0; fi < FRAMES; fi++) {
      const b = fi * VALUES;
      center.push([0, 1, 2].map((c) => f((pts[b + l + c] + pts[b + r + c]) / 2)));
      const dx = f(pts[b + l] - pts[b + r]), dy = f(pts[b + l + 1] - pts[b + r + 1]);
      width[fi] = Math.sqrt(f(f(dx * dx) + f(dy * dy)));
      valid.push(!Number.isNaN(width[fi]) && width[fi] > 1e-6);
    }
    const count = valid.filter(Boolean).length;
    if (count > 0) {
      const sum = [0, 0, 0]; let wsum = 0;
      for (let fi = 0; fi < FRAMES; fi++) if (valid[fi]) { for (let c = 0; c < 3; c++) sum[c] = f(sum[c] + center[fi][c]); wsum = f(wsum + width[fi]); }
      for (let fi = 0; fi < FRAMES; fi++) if (!valid[fi]) { center[fi] = sum.map((s) => f(s / count)); width[fi] = wsum / count; }
    } else {
      for (let fi = 0; fi < FRAMES; fi++) { center[fi] = [0, 0, 0]; width[fi] = 1; }
    }
    const out = new Float32Array(FRAMES * VALUES);
    for (let fi = 0; fi < FRAMES; fi++) for (let p = 0; p < POINTS; p++) for (let c = 0; c < 3; c++) {
      const i = fi * VALUES + p * 3 + c;
      // 손의 z는 손목 기준이라 어깨 깊이를 빼지 않는다
      const v = (pts[i] - (c === 2 && p < POSE ? 0 : center[fi][c])) / width[fi];
      out[i] = Number.isNaN(v) ? 0 : v === Infinity ? 3.4028235e38 : v === -Infinity ? -3.4028235e38 : v;
    }
    return out;
  }

  function mainHandMissing(seq) {
    const miss = (start) => seq.filter((fr) => { for (let i = start * 3; i < (start + HAND) * 3; i++) if (fr[i] == null || Number.isNaN(fr[i])) return true; return false; }).length / seq.length;
    return Math.min(miss(RIGHT_LABEL), miss(LEFT_LABEL));
  }

  // GRU(177→hidden) + Linear, 파이토치와 같은 식. 반환: 낱말별 확률
  function runModel(model, x) {
    const H = model.hidden, sig = (v) => 1 / (1 + Math.exp(-v));
    let h = new Float64Array(H);
    const gi = new Float64Array(3 * H), gh = new Float64Array(3 * H);
    for (let t = 0; t < FRAMES; t++) {
      for (let j = 0; j < 3 * H; j++) {
        let s = model.b_ih[j]; const wi = j * VALUES, xo = t * VALUES;
        for (let k = 0; k < VALUES; k++) s += model.w_ih[wi + k] * x[xo + k];
        gi[j] = s;
        let u = model.b_hh[j]; const wh = j * H;
        for (let k = 0; k < H; k++) u += model.w_hh[wh + k] * h[k];
        gh[j] = u;
      }
      const next = new Float64Array(H);
      for (let j = 0; j < H; j++) {
        const rg = sig(gi[j] + gh[j]), z = sig(gi[H + j] + gh[H + j]);
        const nn = Math.tanh(gi[2 * H + j] + rg * gh[2 * H + j]);
        next[j] = (1 - z) * nn + z * h[j];
      }
      h = next;
    }
    const logits = model.classes.map((_, c) => { let s = model.b_out[c]; for (let k = 0; k < H; k++) s += model.w_out[c * H + k] * h[k]; return s; });
    const m = Math.max(...logits), e = logits.map((v) => Math.exp(v - m)), total = e.reduce((p, q) => p + q, 0);
    return e.map((v) => v / total);
  }

  function predict(model, clip, aspect) {
    const win = windowOf(clip);
    if (win.length < 2) throw new Error('구간 안 프레임이 2개 미만입니다');
    return runModel(model, preprocess(win, aspect));
  }

  // 좌우 뒤집기: 왼손으로 한 동작을 오른손으로 한 것처럼 만든다 (HandMirror.swift)
  const PAIRS = [[1, 4], [2, 5], [3, 6], [7, 8], [9, 10], [11, 12], [13, 14], [15, 16]];
  function mirror(frames) {
    return frames.map((fr) => {
      const out = fr.slice();
      const copy = (from, to) => {
        const x = fr[from * 3];
        out[to * 3] = x == null || Number.isNaN(x) ? NaN : 1 - x; out[to * 3 + 1] = fr[from * 3 + 1]; out[to * 3 + 2] = fr[from * 3 + 2];
      };
      for (let j = 0; j < HAND; j++) { copy(LEFT_LABEL + j, RIGHT_LABEL + j); copy(RIGHT_LABEL + j, LEFT_LABEL + j); }
      for (let k = 0; k < POSE_POINTS; k++) copy(POSE + k, POSE + k);
      for (const [p, q] of PAIRS) { copy(POSE + p, POSE + q); copy(POSE + q, POSE + p); }
      return out;
    });
  }

  // 한 구간을 읽는다: 그대로와 뒤집은 것을 모두 판정해 낱말을 더 확실히 읽은 쪽을 쓴다 (BoardModel.finish)
  function read(model, clip, aspect) {
    const straight = predict(model, clip, aspect);
    const flipped = predict(model, { ...clip, frames: mirror(clip.frames) }, aspect);
    const other = model.classes.indexOf(OTHER);
    const best = (p) => Math.max(...p.filter((_, i) => i !== other));
    const mirrored = best(flipped) > best(straight), probs = mirrored ? flipped : straight;
    const ranking = model.classes.map((word, i) => ({ word, probability: probs[i] })).sort((p, q) => q.probability - p.probability);
    const handMissing = mainHandMissing(windowOf(clip));
    const top = ranking[0];
    const kind = handMissing > MISSING_WARN ? 'hands_unseen' : top.word === OTHER ? 'unknown' : top.probability >= SURE_AT ? 'sure' : 'unsure';
    // 구간 안 프레임마다 오른손·왼손·몸이 보였는지 (화면에서는 "Left" 자리가 실제 오른손이다)
    const win = windowOf(clip), seen = (point) => win.map((fr) => fr[point * 3] != null && !Number.isNaN(fr[point * 3]));
    return { ranking, top, mirrored, handMissing, seconds: Math.min(clip.end - clip.start, MAX_SECONDS), kind,
      rightSeen: seen(LEFT_LABEL), leftSeen: seen(RIGHT_LABEL), bodySeen: seen(POSE + L_SHOULDER),
      alternatives: ranking.slice(1).filter((c) => c.word !== OTHER && c.probability >= 0.05).slice(0, 2).map((c) => c.word),
      probabilities: Object.fromEntries(ranking.map((c) => [c.word, c.probability])) };
  }

  root.KSL = { buildFrame, Segmenter, preprocess, runModel, predict, mirror, read, windowOf, mainHandMissing,
    VALUES, MAX_SECONDS, SURE_AT, OTHER, LEFT_LABEL, RIGHT_LABEL, POSE };
})(typeof globalThis !== 'undefined' ? globalThis : this);
