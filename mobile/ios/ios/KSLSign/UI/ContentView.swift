import SwiftUI

struct ContentView: View {
    @State private var model = TranslatorModel()
    @State private var correcting: Translation?
    @State private var showSettings = false
    @State private var askName = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            VStack(spacing: 8) {
                camera
                if model.mode == .button { recordButton }
                TranslationCard(translation: model.selected, mode: model.mode, isRecording: model.isRecording,
                                elapsed: model.elapsed, message: model.message,
                                onConfirm: { withName { if let id = model.selected?.id { model.confirm(id) } } },
                                onCorrect: { withName { correcting = model.selected } })
                HistoryStrip(translations: model.translations, selectedID: model.selected?.id) { model.selectedID = $0 }
            }
            .padding(.horizontal)
            .padding(.bottom, 4)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker("번역 방식", selection: $model.mode) {
                        Text("자동").tag(Segmenter.Mode.auto)
                        Text("버튼").tag(Segmenter.Mode.button)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 160)
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button { model.switchCamera() } label: {
                        Label(model.cameraPosition == .back ? "후면" : "전면", systemImage: "arrow.triangle.2.circlepath.camera")
                            .labelStyle(.titleAndIcon)
                    }
                    .disabled(model.setupError != nil)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                }
            }
            .sheet(item: $correcting) { t in
                CorrectionSheet(translation: t, classes: model.classes) { model.correct(t.id, to: $0) }
            }
            .sheet(isPresented: $showSettings) {
                NavigationStack { SettingsView(model: model) }
            }
            .alert("수어하는 사람 이름", isPresented: $askName) {
                TextField("예: 형준", text: $model.person)
                Button("확인") {}
            } message: {
                Text("확인한 데이터에 함께 저장합니다. 이름을 넣은 뒤 다시 눌러 주세요.")
            }
            .task { await model.setUp() }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { Task { await model.setUp() } } else { model.pause() }
            }
        }
    }

    /// 샘플에 사람 이름이 필요해서, 없으면 먼저 묻는다
    private func withName(_ action: () -> Void) {
        if model.person.trimmingCharacters(in: .whitespaces).isEmpty {
            askName = true
        } else {
            action()
        }
    }

    private var camera: some View {
        ZStack {
            if let preview = model.preview {
                Image(decorative: preview, scale: 1).resizable()
            } else {
                Color.black
            }
            OverlayView(frame: model.frame, guide: model.guide, imageWidth: model.imageWidth, imageHeight: model.imageHeight)
        }
        // MediaPipe에는 좌우 반전한 화면을 넣는다. 전면은 그대로(거울처럼), 후면은 눈에 보이는 대로 다시 뒤집어 보여준다
        .scaleEffect(x: model.cameraPosition == .back ? -1 : 1, y: 1)
        .aspectRatio(model.aspect, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(alignment: .top) {
            if let error = model.setupError {
                Label(error, systemImage: "exclamationmark.triangle")
                    .font(.callout)
                    .padding(10)
                    .background(.red, in: RoundedRectangle(cornerRadius: 10))
                    .foregroundStyle(.white)
                    .padding(8)
            } else {
                HStack(spacing: 6) {
                    Text(model.guide.message).bold()
                    if let width = model.frame?.shoulderWidth {
                        Text(String(format: "어깨 폭 %.2f", width))
                    }
                }
                .font(.callout)
                .padding(.horizontal, 12)
                .padding(.vertical, 5)
                .background(model.guide.isOK ? Color.green : Color.red, in: Capsule())
                .foregroundStyle(.white)
                .padding(8)
            }
        }
        .overlay(alignment: .bottomLeading) {
            HStack(spacing: 10) {
                Label("0~20 Right", systemImage: "circle.fill").foregroundStyle(OverlayView.rightLabelColor)
                Label("21~41 Left", systemImage: "circle.fill").foregroundStyle(OverlayView.leftLabelColor)
            }
            .font(.caption2)
            .padding(6)
            .background(.black.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
            .padding(8)
        }
        .overlay(alignment: .bottomTrailing) {
            if model.zoomLabels.count > 1 {
                HStack(spacing: 4) {
                    ForEach(model.zoomLabels.indices, id: \.self) { i in
                        Button(model.zoomLabels[i]) { model.setZoom(i) }
                            .font(.caption.bold())
                            .frame(width: 38, height: 30)
                            .background(i == model.zoomIndex ? Color.yellow : Color.black.opacity(0.5), in: Capsule())
                            .foregroundStyle(i == model.zoomIndex ? .black : .white)
                    }
                }
                .padding(8)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var recordButton: some View {
        Button {
            model.toggleRecording()
        } label: {
            Text(model.isRecording ? String(format: "끝  (%.1f초)", model.elapsed) : "시작")
                .font(.title3.bold())
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
        }
        .buttonStyle(.borderedProminent)
        .tint(model.isRecording ? .red : .accentColor)
        .disabled(model.setupError != nil)
    }
}
