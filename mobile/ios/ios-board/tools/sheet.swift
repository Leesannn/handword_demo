// 폴더의 PNG를 이름 순서대로 한 장에 모은다 (화면 그림을 한눈에 볼 때 쓴다).
// 쓰는 법: xcrun swift tools/sheet.swift <폴더> <결과.png> [한 줄에 몇 장] [한 장의 너비]
import AppKit

let arguments = CommandLine.arguments
guard arguments.count >= 3 else {
    print("쓰는 법: xcrun swift tools/sheet.swift <폴더> <결과.png> [한 줄에 몇 장] [한 장의 너비]")
    exit(1)
}
let folder = URL(fileURLWithPath: arguments[1])
let output = URL(fileURLWithPath: arguments[2])
let columns = arguments.count > 3 ? Int(arguments[3]) ?? 6 : 6
let cellWidth = arguments.count > 4 ? CGFloat(Double(arguments[4]) ?? 300) : 300

let files = ((try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? [])
    .filter { $0.pathExtension.lowercased() == "png" && $0.standardizedFileURL != output.standardizedFileURL }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }
let images = files.compactMap { url in NSImage(contentsOf: url).map { (url.deletingPathExtension().lastPathComponent, $0) } }
guard let first = images.first else {
    print("그림이 없습니다:", folder.path)
    exit(1)
}

let cellHeight = cellWidth * first.1.size.height / first.1.size.width
let gap: CGFloat = 16, label: CGFloat = 22
let rows = (images.count + columns - 1) / columns
let width = Int(CGFloat(columns) * (cellWidth + gap) + gap)
let height = Int(CGFloat(rows) * (cellHeight + label + gap) + gap)
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height, bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSColor(calibratedWhite: 0.9, alpha: 1).setFill()
NSRect(x: 0, y: 0, width: width, height: height).fill()
for (i, item) in images.enumerated() {
    let x = gap + CGFloat(i % columns) * (cellWidth + gap)
    let y = CGFloat(height) - gap - CGFloat(i / columns + 1) * (cellHeight + label + gap) + gap
    let drawn = cellWidth * item.1.size.height / item.1.size.width
    item.1.draw(in: NSRect(x: x, y: y + label + (cellHeight - min(drawn, cellHeight)), width: cellWidth, height: min(drawn, cellHeight)))
    (item.0 as NSString).draw(at: NSPoint(x: x, y: y + 3), withAttributes: [.font: NSFont.systemFont(ofSize: 12), .foregroundColor: NSColor.black])
}
NSGraphicsContext.current = nil
try rep.representation(using: .png, properties: [:])!.write(to: output)
print("모음:", output.path, "\(images.count)장")
