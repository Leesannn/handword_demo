// 엔진(engine/page.html, core.js, model.json), 화면(web/ui.css, ui.js), 본보기 그림(engine/demo_frames)을 한 덩어리로 묶는다.
// - web/dist/index.html: 브라우저에서 여는 웹앱 (HTTPS 주소에 올리면 사파리·크롬에서 바로 열린다)
// - engine/page.js: 앱(React Native)의 웹뷰가 읽는 같은 페이지의 문자열. 직접 고치지 않는다
// - engine/dist/index.html: 화면 없이 엔진만 든 시험용
// 고친 뒤에는 `npm run engine`을 다시 실행한다. 서버 주소를 웹앱에 박으려면 KSL_SERVER=https://서버주소 npm run engine
import { copyFileSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const engine = join(root, 'engine'), web = join(root, 'web');
const read = (dir, name) => readFileSync(join(dir, name), 'utf8');
const html = read(engine, 'page.html').replace('/*CORE*/', () => read(engine, 'core.js')).replace('/*MODEL*/null', () => read(engine, 'model.json'));
mkdirSync(join(engine, 'dist'), { recursive: true });
writeFileSync(join(engine, 'dist', 'index.html'), html);

// 본보기: 3D 사람 모형이 낱말을 하는 장면들 (아이폰 앱의 모형을 ios-board/tools/avatar_video.sh로 뽑아 engine/demo_frames에 둔 것)
const WORDS = ['커피', '춥다', '우유', '감사', '자다'];
const demos = {};
for (const name of readdirSync(join(engine, 'demo_frames')).filter((n) => n.endsWith('.jpg')).sort()) {
  const word = WORDS[Number(name.split('_')[0])];
  (demos[word] = demos[word] || []).push('data:image/jpeg;base64,' + readFileSync(join(engine, 'demo_frames', name)).toString('base64'));
}

// 좌표 라이브러리(MediaPipe)의 글을 페이지에 넣는다 (인터넷 없이 켜지게)
const mediapipe = join(root, 'node_modules', '@mediapipe', 'tasks-vision');
const safe = (text) => text.replace(/<\/script/gi, '<\\/script');
const library = '<script>window.KSL_MP_LIB = ' + safe(JSON.stringify(readFileSync(join(mediapipe, 'vision_bundle.cjs'), 'utf8'))) + ';</script>\n';
const head = library + '<meta name="theme-color" content="#1b4332">\n<meta name="mobile-web-app-capable" content="yes">\n<meta name="apple-mobile-web-app-capable" content="yes">\n'
  + '<meta name="apple-mobile-web-app-title" content="수어 칠판">\n<meta name="color-scheme" content="light dark">\n<style>' + read(web, 'ui.css') + '</style>';
const body = '<div id="app"></div>\n<script>window.KSL_SERVER = ' + JSON.stringify(process.env.KSL_SERVER || '') + '; window.KSL_DEMOS = ' + JSON.stringify(demos) + ';</script>\n<script>'
  + read(web, 'ui.js') + '</script>';
const app = html.replace('<title>수어 칠판 엔진</title>', '<title>수어 칠판</title>')
  .replace('viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"', 'viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover"')
  .replace('<!--WEB_HEAD-->', () => head).replace('<!--WEB_BODY-->', () => body);
if (!app.includes('id="app"') || !app.includes('viewport-fit=cover')) throw new Error('page.html의 끼워 넣을 자리를 찾지 못했다');
mkdirSync(join(web, 'dist'), { recursive: true });
writeFileSync(join(web, 'dist', 'index.html'), app);
writeFileSync(join(engine, 'page.js'), '// tools/build_engine.mjs가 만든 파일. 직접 고치지 않는다.\nexport default ' + JSON.stringify(app) + ';\n');
// 안드로이드 앱 안에 넣는 묶음: 같은 페이지 + 좌표를 뽑는 데 필요한 파일들. 인터넷 없이도 켜진다.
// android/app/src/main/assets/ksl 에 복사해 넣는다 (npm run apk가 한다). 페이지는 그 파일들을 옆에서('./') 읽는다
const offline = join(root, 'offline');
mkdirSync(offline, { recursive: true });
writeFileSync(join(offline, 'index.html'), app.replace('<head>', '<head><script>window.KSL_ASSETS = "./";</script>'));
for (const name of ['vision_wasm_internal.js', 'vision_wasm_internal.wasm']) copyFileSync(join(mediapipe, 'wasm', name), join(offline, name));
for (const name of ['hand_landmarker.task', 'pose_landmarker_lite.task']) copyFileSync(join(engine, 'vendor', name), join(offline, name));
console.log('web/dist/index.html', Math.round(app.length / 1024) + 'KB', '본보기', Object.entries(demos).map(([w, f]) => `${w} ${f.length}장`).join(', '));
