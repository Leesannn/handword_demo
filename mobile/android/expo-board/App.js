// 수어 칠판 (Expo). 화면·카메라·판정은 모두 웹뷰 안의 한 페이지가 한다 (engine/page.js = web/ui.js + engine/page.html).
// 아이폰 앱(~/sign-app/ios-board)의 화면을 그 페이지에 옮겨 두었고, 여기서는 페이지가 못 하는 일만 한다:
// 카메라 권한 받기, 학습 기록을 서버로 보내기(페이지는 주소 제한 때문에 직접 못 보낸다), 안드로이드의 뒤로 단추, 화면 가장자리 여백.
import { useCallback, useEffect, useRef } from 'react';
import { BackHandler, Platform, StyleSheet, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useCameraPermissions } from 'expo-camera';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import page from './engine/page';
import config from './server.config.json';

// 엔진의 속도 조절 값 (engine/page.html의 TUNE). 비워 두면 기본값을 쓴다
const TUNE = { poseDelegate: 'CPU' };
// 안드로이드에서는 '페이지가 뜨기 전에 넣는 스크립트'가 제때 돌지 않을 때가 있어서, 값을 페이지 글에 직접 써 넣는다
const QUERY = Object.entries(TUNE).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
const HTML = page.replace('<head>', '<head><script>window.KSL_TUNE = ' + JSON.stringify(TUNE) + ';</script>');

export default function App() {
  return <SafeAreaProvider><Shell /></SafeAreaProvider>;
}

function Shell() {
  const insets = useSafeAreaInsets();
  const web = useRef(null);
  const asked = useRef(false);
  const [permission, ask] = useCameraPermissions();
  const run = (code) => web.current?.injectJavaScript(code + '; true;');
  const edges = `document.documentElement.style.setProperty('--sat', '${insets.top}px'); document.documentElement.style.setProperty('--sab', '${insets.bottom}px')`;

  useEffect(() => {
    if (permission && !permission.granted && permission.canAskAgain && !asked.current) { asked.current = true; ask(); }
  }, [permission]);
  useEffect(() => { run(edges + '; window.dispatchEvent(new Event("resize"))'); }, [insets.top, insets.bottom]);
  useEffect(() => {
    // 뒤로 단추: 페이지가 열려 있는 화면을 닫는다. 닫을 것이 없다고 하면 앱에서 물러난다
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      run('window.ReactNativeWebView.postMessage(JSON.stringify({ type: "back", handled: !!(window.KSLBack && window.KSLBack()) }))');
      return true;
    });
    return () => sub.remove();
  }, []);

  const onMessage = useCallback(async (e) => {
    let m;
    try { m = JSON.parse(e.nativeEvent.data); } catch (_) { return; }
    if (m.type === 'back' && !m.handled) BackHandler.exitApp();
    if (m.type === 'perf') console.log('[속도]', JSON.stringify(m));
    if (m.type !== 'post') return;
    // 학습 기록 묶음을 서버로 보내고 응답 코드를 페이지에 돌려준다. 서버 주소와 키는 페이지에 넘기지 않는다
    let status = 0;
    if (config.BaseURL && config.APIKey) {
      try {
        const response = await fetch(config.BaseURL + config.EventsPath, { method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-API-Key': config.APIKey }, body: m.body });
        status = response.status;
      } catch (_) { status = 0; }
    }
    run(`window.KSLNativeReply && window.KSLNativeReply(${Number(m.id)}, ${status})`);
  }, []);

  // 권한을 묻는 동안에는 페이지를 열지 않는다 (페이지가 먼저 카메라를 열려다 실패하지 않게)
  const waiting = !permission || (!permission.granted && permission.canAskAgain);
  return (
    <View style={s.root}>
      <StatusBar style="light" translucent backgroundColor="transparent" />
      {!waiting && (
        <WebView
          ref={web}
          style={s.root}
          // 카메라(getUserMedia)는 https 주소에서만 열리므로 주소를 https로 알려 준다
          // 안드로이드: 앱 안에 넣어 둔 페이지와 파일들을 연다 (인터넷 없이도 켜진다). 조절 값은 주소 뒤에 붙인다.
          // 그 밖: 페이지 글을 그대로 넘기고, 카메라가 https에서만 열리므로 주소를 https로 알려 준다 (좌표 모델은 인터넷에서 받는다)
          source={Platform.OS === 'android' ? { uri: 'file:///android_asset/ksl/index.html?' + QUERY } : { html: HTML, baseUrl: 'https://localhost/' }}
          allowFileAccess
          allowFileAccessFromFileURLs
          allowUniversalAccessFromFileURLs
          injectedJavaScriptBeforeContentLoaded={edges + '; true;'}
          injectedJavaScript={edges + '; window.dispatchEvent(new Event("resize")); true;'}
          originWhitelist={['*']}
          javaScriptEnabled
          domStorageEnabled
          allowsInlineMediaPlayback
          mediaPlaybackRequiresUserAction={false}
          mediaCapturePermissionGrantType="grant"
          scrollEnabled={false}
          bounces={false}
          overScrollMode="never"
          textZoom={100}
          setBuiltInZoomControls={false}
          onMessage={onMessage}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({ root: { flex: 1, backgroundColor: '#1b4332' } });
