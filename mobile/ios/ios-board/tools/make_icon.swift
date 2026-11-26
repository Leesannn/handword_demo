// 앱 아이콘을 그린다: 칠판 초록 바탕에 분필 흰 대괄호, 그 안에 빈 하늘색 고리(왼손)와 채운 노란 점(오른손).
// 쓰는 법: xcrun swift tools/make_icon.swift KSLBoard/Assets.xcassets/AppIcon.appiconset/AppIcon.png
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let side = 1024
let path = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.png"
// 아이콘은 투명한 곳이 없어야 해서 알파 없는 그림으로 만든다
let ctx = CGContext(data: nil, width: side, height: side, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!

func color(_ hex: UInt32) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
}

ctx.setFillColor(color(0x1B4332))
ctx.fill(CGRect(x: 0, y: 0, width: side, height: side))

// 대괄호 한 쌍
ctx.setStrokeColor(color(0xF2F7F3))
ctx.setLineWidth(64)
ctx.setLineCap(.butt)
ctx.setLineJoin(.miter)
let top: CGFloat = 744, bottom: CGFloat = 280, arm: CGFloat = 120
for (edge, direction) in [(CGFloat(212), CGFloat(1)), (CGFloat(812), CGFloat(-1))] {
    ctx.move(to: CGPoint(x: edge + arm * direction, y: top))
    ctx.addLine(to: CGPoint(x: edge, y: top))
    ctx.addLine(to: CGPoint(x: edge, y: bottom))
    ctx.addLine(to: CGPoint(x: edge + arm * direction, y: bottom))
    ctx.strokePath()
}

// 왼손: 빈 하늘색 고리 / 오른손: 채운 노란 점
ctx.setStrokeColor(color(0x9AD4F5))
ctx.setLineWidth(40)
ctx.strokeEllipse(in: CGRect(x: 334, y: 432, width: 160, height: 160))
ctx.setFillColor(color(0xF4D35E))
ctx.fillEllipse(in: CGRect(x: 520, y: 412, width: 200, height: 200))

let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(destination, ctx.makeImage()!, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("아이콘을 쓰지 못했습니다") }
print("아이콘:", path)
