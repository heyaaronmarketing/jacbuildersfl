// Transcode a video to a smaller H.264 mp4 using macOS AVFoundation.
// Usage: swift compress_video.swift <input> <output> [preset]
import Foundation
import AVFoundation

let args = CommandLine.arguments
guard args.count >= 3 else { FileHandle.standardError.write("need <in> <out> [preset]\n".data(using: .utf8)!); exit(2) }
let inURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])
let presetName = args.count >= 4 ? args[3] : AVAssetExportPreset1280x720

let asset = AVAsset(url: inURL)
guard let export = AVAssetExportSession(asset: asset, presetName: presetName) else {
    FileHandle.standardError.write("could not create export session\n".data(using: .utf8)!); exit(1)
}
try? FileManager.default.removeItem(at: outURL)
export.outputURL = outURL
export.outputFileType = .mp4
export.shouldOptimizeForNetworkUse = true

let sem = DispatchSemaphore(value: 0)
export.exportAsynchronously {
    switch export.status {
    case .completed: print("completed")
    case .failed:    print("failed: \(export.error?.localizedDescription ?? "unknown")")
    case .cancelled: print("cancelled")
    default:         print("status: \(export.status.rawValue)")
    }
    sem.signal()
}
sem.wait()
exit(export.status == .completed ? 0 : 1)
