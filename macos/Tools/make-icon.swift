#!/usr/bin/env swift
// Renders the Local Tasks Bridge app icon: a blue rounded square with a
// checklist card and an orange two-way sync badge.
//
//   swift macos/Tools/make-icon.swift OUTPUT.iconset
//   iconutil -c icns OUTPUT.iconset -o AppIcon.icns
//
// Every size is drawn from the same vector description (1024-point design
// grid, body inset 100 points as in the macOS icon template), not downscaled.

import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let designSize: CGFloat = 1024

func color(_ hex: UInt32, alpha: CGFloat = 1) -> CGColor {
    CGColor(
        srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
        green: CGFloat((hex >> 8) & 0xFF) / 255,
        blue: CGFloat(hex & 0xFF) / 255,
        alpha: alpha
    )
}

/// A superellipse (exponent 5), close to the continuous-corner shape of macOS icons.
func squirclePath(in rect: CGRect) -> CGPath {
    let path = CGMutablePath()
    let exponent: CGFloat = 5
    let steps = 360
    for step in 0...steps {
        let angle = CGFloat(step) / CGFloat(steps) * 2 * .pi
        let cosine = cos(angle)
        let sine = sin(angle)
        let x = pow(abs(cosine), 2 / exponent) * (cosine < 0 ? -1 : 1)
        let y = pow(abs(sine), 2 / exponent) * (sine < 0 ? -1 : 1)
        let point = CGPoint(x: rect.midX + x * rect.width / 2, y: rect.midY + y * rect.height / 2)
        if step == 0 {
            path.move(to: point)
        } else {
            path.addLine(to: point)
        }
    }
    path.closeSubpath()
    return path
}

func roundedRect(_ rect: CGRect, radius: CGFloat) -> CGPath {
    CGPath(roundedRect: rect, cornerWidth: radius, cornerHeight: radius, transform: nil)
}

/// Point on a circle; angles grow clockwise because the context is flipped (y down).
func point(on center: CGPoint, radius: CGFloat, degrees: CGFloat) -> CGPoint {
    let radians = degrees * .pi / 180
    return CGPoint(x: center.x + radius * cos(radians), y: center.y + radius * sin(radians))
}

/// An arc stroke from `start` to `end` degrees (clockwise) ending in an arrowhead.
func drawArrowArc(_ context: CGContext, center: CGPoint, radius: CGFloat, start: CGFloat, end: CGFloat, width: CGFloat) {
    let arc = CGMutablePath()
    let steps = 64
    for step in 0...steps {
        let angle = start + (end - start) * CGFloat(step) / CGFloat(steps)
        let position = point(on: center, radius: radius, degrees: angle)
        if step == 0 {
            arc.move(to: position)
        } else {
            arc.addLine(to: position)
        }
    }
    context.addPath(arc)
    context.setLineWidth(width)
    context.setLineCap(.round)
    context.setLineJoin(.round)
    context.strokePath()

    let radians = end * .pi / 180
    let tip = point(on: center, radius: radius, degrees: end)
    let direction = CGPoint(x: -sin(radians), y: cos(radians))
    let normal = CGPoint(x: cos(radians), y: sin(radians))
    let length = width * 1.7
    let halfWidth = width * 1.25
    let head = CGMutablePath()
    head.move(to: CGPoint(x: tip.x + direction.x * length * 0.75, y: tip.y + direction.y * length * 0.75))
    let base = CGPoint(x: tip.x - direction.x * length * 0.45, y: tip.y - direction.y * length * 0.45)
    head.addLine(to: CGPoint(x: base.x + normal.x * halfWidth, y: base.y + normal.y * halfWidth))
    head.addLine(to: CGPoint(x: base.x - normal.x * halfWidth, y: base.y - normal.y * halfWidth))
    head.closeSubpath()
    context.addPath(head)
    context.fillPath()
}

func drawIcon(in context: CGContext) {
    let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!

    // Body with a soft drop shadow.
    let body = squirclePath(in: CGRect(x: 100, y: 100, width: 824, height: 824))
    context.saveGState()
    context.setShadow(offset: CGSize(width: 0, height: 10), blur: 24, color: color(0x000000, alpha: 0.28))
    context.addPath(body)
    context.setFillColor(color(0x2F6BEA))
    context.fillPath()
    context.restoreGState()

    context.saveGState()
    context.addPath(body)
    context.clip()
    let background = CGGradient(
        colorsSpace: colorSpace,
        colors: [color(0x5CB8FF), color(0x2E62E8)] as CFArray,
        locations: [0, 1]
    )!
    context.drawLinearGradient(background, start: CGPoint(x: 200, y: 100), end: CGPoint(x: 824, y: 924), options: [])
    context.restoreGState()

    // Checklist card.
    let card = roundedRect(CGRect(x: 228, y: 232, width: 476, height: 552), radius: 72)
    context.saveGState()
    context.setShadow(offset: CGSize(width: 0, height: 10), blur: 22, color: color(0x0B2A6B, alpha: 0.30))
    context.addPath(card)
    context.setFillColor(color(0xFFFFFF))
    context.fillPath()
    context.restoreGState()

    let rowCenters: [CGFloat] = [360, 494, 628]
    for (index, y) in rowCenters.enumerated() {
        let checked = index < 2
        let circleCenter = CGPoint(x: 318, y: y)
        let circle = CGRect(x: circleCenter.x - 38, y: y - 38, width: 76, height: 76)
        if checked {
            context.setFillColor(color(0x2F6BEA))
            context.fillEllipse(in: circle)
            let check = CGMutablePath()
            check.move(to: CGPoint(x: circleCenter.x - 18, y: y + 1))
            check.addLine(to: CGPoint(x: circleCenter.x - 5, y: y + 15))
            check.addLine(to: CGPoint(x: circleCenter.x + 19, y: y - 13))
            context.addPath(check)
            context.setStrokeColor(color(0xFFFFFF))
            context.setLineWidth(12)
            context.setLineCap(.round)
            context.setLineJoin(.round)
            context.strokePath()
        } else {
            context.setStrokeColor(color(0x9AA9C2))
            context.setLineWidth(10)
            context.strokeEllipse(in: circle.insetBy(dx: 5, dy: 5))
        }
        context.addPath(roundedRect(CGRect(x: 384, y: y - 15, width: index == 1 ? 196 : 250, height: 30), radius: 15))
        context.setFillColor(checked ? color(0xC9D5E8) : color(0x5B6B84))
        context.fillPath()
    }

    // Two-way sync badge.
    let badgeCenter = CGPoint(x: 712, y: 712)
    context.saveGState()
    context.setShadow(offset: CGSize(width: 0, height: 8), blur: 18, color: color(0x0B2A6B, alpha: 0.30))
    context.setFillColor(color(0xFFFFFF))
    context.fillEllipse(in: CGRect(x: badgeCenter.x - 176, y: badgeCenter.y - 176, width: 352, height: 352))
    context.restoreGState()

    context.saveGState()
    context.addEllipse(in: CGRect(x: badgeCenter.x - 156, y: badgeCenter.y - 156, width: 312, height: 312))
    context.clip()
    let badge = CGGradient(
        colorsSpace: colorSpace,
        colors: [color(0xFFB443), color(0xFF7417)] as CFArray,
        locations: [0, 1]
    )!
    context.drawLinearGradient(
        badge,
        start: CGPoint(x: badgeCenter.x, y: badgeCenter.y - 156),
        end: CGPoint(x: badgeCenter.x, y: badgeCenter.y + 156),
        options: []
    )
    context.restoreGState()

    context.setStrokeColor(color(0xFFFFFF))
    context.setFillColor(color(0xFFFFFF))
    drawArrowArc(context, center: badgeCenter, radius: 84, start: 200, end: 318, width: 28)
    drawArrowArc(context, center: badgeCenter, radius: 84, start: 20, end: 138, width: 28)
}

func renderPNG(pixels: Int, to url: URL) throws {
    let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
    guard let context = CGContext(
        data: nil,
        width: pixels,
        height: pixels,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        throw NSError(domain: "make-icon", code: 1, userInfo: [NSLocalizedDescriptionKey: "Cannot create a \(pixels)px bitmap"])
    }
    context.interpolationQuality = .high
    context.setShouldAntialias(true)
    let scale = CGFloat(pixels) / designSize
    // Flip so the drawing code can use top-left coordinates.
    context.translateBy(x: 0, y: CGFloat(pixels))
    context.scaleBy(x: scale, y: -scale)
    drawIcon(in: context)

    guard let image = context.makeImage(),
          let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
        throw NSError(domain: "make-icon", code: 2, userInfo: [NSLocalizedDescriptionKey: "Cannot write \(url.path)"])
    }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        throw NSError(domain: "make-icon", code: 3, userInfo: [NSLocalizedDescriptionKey: "Cannot write \(url.path)"])
    }
}

let arguments = CommandLine.arguments
guard arguments.count == 2, arguments[1].hasSuffix(".iconset") else {
    FileHandle.standardError.write(Data("usage: swift make-icon.swift OUTPUT.iconset\n".utf8))
    exit(2)
}

let iconset = URL(fileURLWithPath: arguments[1], isDirectory: true)
do {
    try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
    for points in [16, 32, 128, 256, 512] {
        try renderPNG(pixels: points, to: iconset.appendingPathComponent("icon_\(points)x\(points).png"))
        try renderPNG(pixels: points * 2, to: iconset.appendingPathComponent("icon_\(points)x\(points)@2x.png"))
    }
} catch {
    FileHandle.standardError.write(Data("make-icon: \(error.localizedDescription)\n".utf8))
    exit(1)
}
