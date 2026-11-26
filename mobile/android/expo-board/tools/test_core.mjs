// 판정 엔진이 파이토치 기준값과 같은 결과를 내는지 확인한다. 실행: node tools/test_core.mjs
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const engine = join(here, '..', 'engine');
(0, eval)(readFileSync(join(engine, 'core.js'), 'utf8'));
const KSL = globalThis.KSL;
const model = JSON.parse(readFileSync(join(engine, 'model.json'), 'utf8'));
const fx = JSON.parse(readFileSync(join(engine, 'fixture.json'), 'utf8'));
const clip = { frames: fx.frames, times: fx.times, start: fx.start, end: fx.end };

let failed = 0;
const check = (name, diff, limit) => { const ok = diff < limit; if (!ok) failed++; console.log(ok ? '통과' : '실패', name, '최대 차이', diff.toExponential(2)); };

const pre = KSL.preprocess(KSL.windowOf(clip), fx.aspect);
check('전처리 (30×177)', Math.max(...fx.preprocessed.map((v, i) => Math.abs(v - pre[i]))), 1e-5);
const p = KSL.predict(model, clip, fx.aspect);
check('모델 확률', Math.max(...fx.probabilities.map((v, i) => Math.abs(v - p[i]))), 1e-4);
const r = KSL.read(model, clip, fx.aspect);
console.log('읽은 낱말:', r.top.word, r.top.probability.toFixed(4), r.mirrored ? '(뒤집음)' : '', '결과:', r.kind);
if (r.top.word !== '감사') { failed++; console.log('실패 본보기는 감사여야 한다'); }

// 폰에서 꺼낸 샘플이 있으면 아이폰 앱이 읽은 낱말과 같은지 본다: node tools/test_core.mjs <샘플 폴더>
const dir = process.argv[2];
if (dir) {
  const { readdirSync } = await import('node:fs');
  let same = 0, total = 0;
  for (const name of readdirSync(dir).filter((n) => n.endsWith('.json'))) {
    const s = JSON.parse(readFileSync(join(dir, name), 'utf8'));
    if (!s.probabilities || s.mirrored === undefined) continue;
    const got = KSL.read(model, { frames: s.frames, times: s.times, start: s.start, end: s.end }, s.aspect);
    const diff = Math.max(...s.classes.map((c, i) => Math.abs(s.probabilities[i] - got.probabilities[c])));
    total++; if (got.top.word === s.predicted && diff < 1e-3) same++; else console.log('다름', name, s.predicted, '→', got.top.word, diff.toExponential(2));
  }
  console.log(`폰 샘플 ${total}건 중 ${same}건이 아이폰 앱과 같은 결과`);
  if (same !== total) failed++;
}
process.exit(failed ? 1 : 0);
