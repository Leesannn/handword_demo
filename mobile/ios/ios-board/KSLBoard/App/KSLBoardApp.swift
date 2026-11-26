import SwiftUI

@main
struct KSLBoardApp: App {
    @State private var model: BoardModel
    @State private var progress = ProgressStore()

    init() {
        // 시뮬레이터에는 카메라가 없어서 앱에 든 본보기 좌표를 카메라 대신 흘려보낸다.
        // 기기에서도 실행 인자에 -demo를 주면 같은 방식으로 돈다
        #if targetEnvironment(simulator)
        let source: FrameSource = DemoSource()
        #else
        let source: FrameSource = ProcessInfo.processInfo.arguments.contains("-demo") ? DemoSource() : CameraSource()
        #endif
        _model = State(initialValue: BoardModel(source: source))
    }

    var body: some Scene {
        WindowGroup {
            RootView(model: model, progress: progress)
        }
    }
}

/// 탭 둘: 번역과 학습
struct RootView: View {
    let model: BoardModel
    let progress: ProgressStore
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        TabView {
            TranslateView(model: model)
                .tabItem {
                    Label { Text("번역") } icon: { Image(uiImage: TabIcon.translate) }
                }
            LearnView(model: model, progress: progress)
                .tabItem { Label("학습", systemImage: "book") }
        }
        .tint(Theme.tint)
        .onChange(of: scenePhase) { _, phase in
            model.setSceneActive(phase == .active)
            // 앱으로 돌아오거나 나갈 때 쌓인 기록을 보낸다
            if phase != .inactive { SyncCenter.shared.flushNow() }
        }
        .sheet(isPresented: Binding(get: { !SyncCenter.isOff && !SyncCenter.shared.agreed }, set: { _ in })) {
            ConsentView(sync: SyncCenter.shared)
        }
    }
}
