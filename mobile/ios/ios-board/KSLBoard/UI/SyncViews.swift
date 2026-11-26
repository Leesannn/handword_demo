import SwiftUI

/// 처음 켰을 때 한 번 받는 데이터 사용 동의. 무엇을 보내고 무엇을 보내지 않는지 알리고, 동의해야 앱을 쓸 수 있다
struct ConsentView: View {
    let sync: SyncCenter

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("학습 데이터로\n앱을 고쳐 갑니다")
                        .font(.app(.title, .bold))
                        .foregroundStyle(Theme.ink)
                        .padding(.top, 28)
                    item("보내는 것", "어떤 낱말을 연습했고 앱이 어떻게 읽었는지, 그리고 수어 동작의 좌표(손과 몸의 점). 이름 없이 임의의 번호로 보냅니다.")
                    item("어디에 쓰나", "앱이 수어를 더 잘 읽도록 다시 학습시키는 데 씁니다.")
                    item("보내지 않는 것", "카메라 영상과 사진, 이름. 영상은 폰에도 저장하지 않습니다.")
                    Text("동의해야 앱을 쓸 수 있어요.")
                        .font(.app(.subheadline))
                        .foregroundStyle(Theme.ink2)
                }
                .padding(.horizontal, 24)
            }
            Button("동의하고 시작하기") { sync.agree() }
                .buttonStyle(CTAStyle())
                .padding(.horizontal, 20)
                .padding(.bottom, 16)
        }
        .background(Theme.bg)
        .interactiveDismissDisabled()
    }

    private func item(_ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.app(.headline)).foregroundStyle(Theme.ink)
            Text(detail).font(.app(.body)).foregroundStyle(Theme.ink2)
        }
    }
}
