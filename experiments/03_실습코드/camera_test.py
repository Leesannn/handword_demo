import cv2


def main():
    camera = cv2.VideoCapture(0)

    try:
        if not camera.isOpened():
            print("웹캠을 열지 못했습니다.")
            print("카메라 권한과 다른 프로그램의 카메라 사용 여부를 확인하세요.")
            return

        print("웹캠 실행 성공")
        print("종료: 카메라 창을 선택한 상태에서 Q 키를 누르세요.")

        while True:
            success, frame = camera.read()

            if not success:
                print("카메라에서 화면을 읽지 못했습니다.")
                break

            cv2.imshow("Camera Test - Press Q to quit", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.release()
        cv2.destroyAllWindows()
        print("카메라를 종료했습니다.")


if __name__ == "__main__":
    main()