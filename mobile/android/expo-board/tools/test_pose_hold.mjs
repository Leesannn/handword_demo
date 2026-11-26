// 몸(Pose) 좌표를 매 장이 아니라 N장에 한 번만 새로 뽑아도 판정이 유지되는지 본다.
// 폰에서 꺼낸 샘플의 몸 좌표를 N장 동안 붙들어 둔 것으로 다시 판정해, 원래 결과와 비교한다.
// 실행: node tools/test_pose_hold.mjs <샘플 폴더>
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const engine = join(dirname(fileURLToPath(import.meta.url)), '..', 'engine');
(0, eval)(readFileSync(join(engine, 'core.js'), 'utf8'));
const KSL = globalThis.KSL, model = JSON.parse(readFileSync(join(engine, 'model.json'), 'utf8'));
const dir = process.argv[2];
const hold = (frames, every) => { let last = null; return frames.map((f, i) => { if (i % every === 0 || !last) { last = f; return f; } const out = f.slice(); for (let k = 42 * 3; k < 59 * 3; k++) out[k] = last[k]; return out; }); };
const files = readdirSync(dir).filter((n) => n.endsWith('.json'));
for (const every of [2, 3, 4]) {
  let same = 0, total = 0, worst = 0, flips = [];
  for (const name of files) {
    const s = JSON.parse(readFileSync(join(dir, name), 'utf8'));
    const clip = { frames: s.frames, times: s.times, start: s.start, end: s.end };
    const a = KSL.read(model, clip, s.aspect), b = KSL.read(model, { ...clip, frames: hold(s.frames, every) }, s.aspect);
    total++; const d = Math.abs(a.top.probability - (b.probabilities[a.top.word] || 0)); worst = Math.max(worst, d);
    if (a.top.word === b.top.word && a.kind === b.kind) same++; else flips.push(`${s.label}: ${a.top.word} ${a.top.probability.toFixed(2)} → ${b.top.word} ${b.top.probability.toFixed(2)}`);
  }
  console.log(`몸을 ${every}장에 한 번: ${total}건 중 ${same}건 같은 결과, 확률 차이 최대 ${worst.toFixed(3)}`); flips.forEach((f) => console.log('   바뀜', f));
}
