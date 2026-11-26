// 좌표를 느리게 읽을 때(초당 15장 → 7.5장, 5장) 판정이 얼마나 바뀌는지, 몸 좌표만 한두 장 늦게 쓰는 것과 견준다.
// 실행: node tools/test_slow_frames.mjs <샘플 폴더>
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const engine = join(dirname(fileURLToPath(import.meta.url)), '..', 'engine');
(0, eval)(readFileSync(join(engine, 'core.js'), 'utf8'));
const KSL = globalThis.KSL, model = JSON.parse(readFileSync(join(engine, 'model.json'), 'utf8'));
const dir = process.argv[2], files = readdirSync(dir).filter((n) => n.endsWith('.json'));
const every = (n) => (s) => { const keep = s.frames.map((_, i) => i).filter((i) => i % n === 0); return { frames: keep.map((i) => s.frames[i]), times: keep.map((i) => s.times[i]), start: s.start, end: s.end }; };
const lagPose = (n) => (s) => ({ frames: s.frames.map((f, i) => { const from = s.frames[Math.max(0, i - n)], out = f.slice(); for (let k = 42 * 3; k < 59 * 3; k++) out[k] = from[k]; return out; }), times: s.times, start: s.start, end: s.end });
for (const [name, change] of [['초당 7.5장으로 읽기', every(2)], ['초당 5장으로 읽기', every(3)], ['몸 좌표만 1장 늦게', lagPose(1)], ['몸 좌표만 2장 늦게', lagPose(2)]]) {
  let same = 0, total = 0; const flips = [];
  for (const file of files) {
    const s = JSON.parse(readFileSync(join(dir, file), 'utf8'));
    const a = KSL.read(model, { frames: s.frames, times: s.times, start: s.start, end: s.end }, s.aspect);
    let b; try { b = KSL.read(model, change(s), s.aspect); } catch (e) { b = { top: { word: '(읽지 못함)', probability: 0 }, kind: 'none' }; }
    total++; if (a.top.word === b.top.word && a.kind === b.kind) same++; else flips.push(`${s.label}: ${a.top.word} ${a.top.probability.toFixed(2)} → ${b.top.word} ${b.top.probability.toFixed(2)}`);
  }
  console.log(`${name}: ${total}건 중 ${same}건 같은 결과`); flips.forEach((f) => console.log('   바뀜', f));
}
