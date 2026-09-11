import Foundation
import AVFoundation
import CoreMedia
import CoreVideo
import CoreML
import VideoToolbox

final class ArgolisUpscaler {
    let inputURL: URL
    let outputURL: URL
    let modelURL: URL
    let isMonochrome: Bool
    let computeUnits: MLComputeUnits

    init(inputURL: URL, outputURL: URL, modelURL: URL, isMonochrome: Bool = false, computeUnits: MLComputeUnits = .all) {
        self.inputURL = inputURL
        self.outputURL = outputURL
        self.modelURL = modelURL
        self.isMonochrome = isMonochrome
        self.computeUnits = computeUnits
    }

    func run() throws {
        setlinebuf(stdout)
        let startTime = CFAbsoluteTimeGetCurrent()
        print("======================================================================")
        print("ARGOLIS NATIVE SWIFT ZERO-COPY REMASTER ENGINE (Apple Silicon M4)")
        print("Input:        \(inputURL.path)")
        print("Output:       \(outputURL.path)")
        print("Model:        \(modelURL.lastPathComponent)")
        print("Mode:         \(isMonochrome ? "Monochrome B&W Normalization" : "Full Color 1080p")")
        print("Compute Unit: \(computeUnits == .all ? "16-Core Neural Engine + Metal GPU" : "Custom Engine")")
        print("======================================================================")

        // 1. Load Compiled CoreML Model
        let config = MLModelConfiguration()
        config.computeUnits = computeUnits
        config.allowLowPrecisionAccumulationOnGPU = true

        let model = try MLModel(contentsOf: modelURL, configuration: config)
        print("Loaded native hardware model successfully.")

        // 2. Setup AVAssetReader
        let asset = AVURLAsset(url: inputURL)
        let duration = CMTimeGetSeconds(asset.duration)

        guard let videoTrack = asset.tracks(withMediaType: .video).first else {
            throw NSError(domain: "Argolis", code: 1, userInfo: [NSLocalizedDescriptionKey: "No video track found in input."])
        }

        let fps = Double(videoTrack.nominalFrameRate > 0 ? videoTrack.nominalFrameRate : 25.0)
        let totalFrames = Int(duration * fps)
        print(String(format: "Input Duration: %.2fs (~%d frames @ %.2f fps)", duration, totalFrames, fps))

        let reader = try AVAssetReader(asset: asset)

        let videoReaderSettings: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
            kCVPixelBufferWidthKey as String: 720,
            kCVPixelBufferHeightKey as String: 540,
            kCVPixelBufferMetalCompatibilityKey as String: true,
            kCVPixelBufferIOSurfacePropertiesKey as String: [:]
        ]
        let videoOutput = AVAssetReaderTrackOutput(track: videoTrack, outputSettings: videoReaderSettings)
        videoOutput.alwaysCopiesSampleData = false
        reader.add(videoOutput)

        // Audio processing removed: delegated to FFmpeg in daemon.

        // 3. Setup AVAssetWriter
        if FileManager.default.fileExists(atPath: outputURL.path) {
            try? FileManager.default.removeItem(at: outputURL)
        }

        let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
        writer.shouldOptimizeForNetworkUse = true

        let videoCompressionProps: [String: Any] = [
            AVVideoAverageBitRateKey: 5_000_000,
            AVVideoProfileLevelKey: kVTProfileLevel_HEVC_Main_AutoLevel as String,
            AVVideoAllowFrameReorderingKey: true
        ]

        let videoWriterSettings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.hevc,
            AVVideoWidthKey: 1440,
            AVVideoHeightKey: 1080,
            AVVideoCompressionPropertiesKey: videoCompressionProps
        ]

        let videoWriterInput = AVAssetWriterInput(mediaType: .video, outputSettings: videoWriterSettings)
        videoWriterInput.expectsMediaDataInRealTime = false

        let sourcePixelBufferAttributes: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32BGRA),
            kCVPixelBufferWidthKey as String: 1440,
            kCVPixelBufferHeightKey as String: 1080,
            kCVPixelBufferMetalCompatibilityKey as String: true,
            kCVPixelBufferIOSurfacePropertiesKey as String: [:]
        ]
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: videoWriterInput,
            sourcePixelBufferAttributes: sourcePixelBufferAttributes
        )
        writer.add(videoWriterInput)

        // Audio writer setup removed.

        // 4. Start Hardware Pipeline
        guard reader.startReading() else {
            throw NSError(domain: "Argolis", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to start AVAssetReader: \(String(describing: reader.error))"])
        }
        guard writer.startWriting() else {
            throw NSError(domain: "Argolis", code: 3, userInfo: [NSLocalizedDescriptionKey: "Failed to start AVAssetWriter: \(String(describing: writer.error))"])
        }
        writer.startSession(atSourceTime: .zero)

        print("Beginning Zero-Copy Hardware Neural Upscaling...")
        var frameCount = 0
        var lastLogTime = CFAbsoluteTimeGetCurrent()
        var lastLogFrames = 0
        var firstPTS: CMTime?

        let videoGroup = DispatchGroup()
        let videoQueue = DispatchQueue(label: "com.argolis.upscale.video", qos: .userInitiated)

        // Video Pipeline with requestMediaDataWhenReady
        videoGroup.enter()
        videoWriterInput.requestMediaDataWhenReady(on: videoQueue) {
            while videoWriterInput.isReadyForMoreMediaData {
                var shouldBreak = false
                autoreleasepool {
                    let success = self.processNextFrame(
                        videoOutput: videoOutput,
                        videoWriterInput: videoWriterInput,
                        adaptor: adaptor,
                        model: model,
                        firstPTS: &firstPTS,
                        frameCount: &frameCount,
                        lastLogTime: &lastLogTime,
                        lastLogFrames: &lastLogFrames,
                        startTime: startTime,
                        totalFrames: totalFrames
                    )
                    if !success {
                        if reader.status == .failed {
                            print("Reader failed: \(String(describing: reader.error))")
                            exit(118)
                        }
                        videoWriterInput.markAsFinished()
                        videoGroup.leave()
                        shouldBreak = true
                    }
                }
                if shouldBreak || !videoWriterInput.isReadyForMoreMediaData { break }
            }
        }

        // Audio processing loop removed.
        videoGroup.wait()

        let finishGroup = DispatchGroup()
        finishGroup.enter()
        writer.finishWriting {
            finishGroup.leave()
        }
        finishGroup.wait()

        let totalTime = CFAbsoluteTimeGetCurrent() - startTime
        let finalFPS = Double(frameCount) / totalTime
        let fileSize = (try? FileManager.default.attributesOfItem(atPath: outputURL.path)[.size] as? Double) ?? 0.0
        let outSizeMB = fileSize / (1024.0 * 1024.0)

        print("\n======================================================================")
        print("SUCCESS: Native Zero-Copy Remaster Complete!")
        print(String(format: "Master Output:  %@ (%.1f MB)", outputURL.path, outSizeMB))
        print(String(format: "Total Frames:   %d frames in %.2fs (%.2f mins)", frameCount, totalTime, totalTime / 60.0))
        print(String(format: "Throughput:     %.2f FPS (%.2fx Real-Time Speed)", finalFPS, finalFPS / 25.0))
        print("======================================================================\n")
    }

    private func processNextFrame(
        videoOutput: AVAssetReaderTrackOutput,
        videoWriterInput: AVAssetWriterInput,
        adaptor: AVAssetWriterInputPixelBufferAdaptor,
        model: MLModel,
        firstPTS: inout CMTime?,
        frameCount: inout Int,
        lastLogTime: inout CFAbsoluteTime,
        lastLogFrames: inout Int,
        startTime: CFAbsoluteTime,
        totalFrames: Int
    ) -> Bool {
        guard let sampleBuffer = videoOutput.copyNextSampleBuffer() else {
            return false
        }

        guard let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            return true
        }

        let rawPTS: CMTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        if firstPTS == nil {
            firstPTS = rawPTS
        }
        let pts: CMTime = firstPTS != nil ? CMTimeSubtract(rawPTS, firstPTS!) : rawPTS

        do {
            if self.isMonochrome {
                CVPixelBufferLockBaseAddress(imageBuffer, [])
                if let baseAddress = CVPixelBufferGetBaseAddress(imageBuffer) {
                    let bytesPerRow = CVPixelBufferGetBytesPerRow(imageBuffer)
                    let width = CVPixelBufferGetWidth(imageBuffer)
                    let height = CVPixelBufferGetHeight(imageBuffer)
                    var ptr = baseAddress.assumingMemoryBound(to: UInt8.self)
                    for _ in 0..<height {
                        for x in 0..<width {
                            let b = UInt32(ptr[x * 4])
                            let g = UInt32(ptr[x * 4 + 1])
                            let r = UInt32(ptr[x * 4 + 2])
                            let gray = UInt8((r * 77 + g * 150 + b * 29) >> 8)
                            ptr[x * 4] = gray
                            ptr[x * 4 + 1] = gray
                            ptr[x * 4 + 2] = gray
                        }
                        ptr = ptr.advanced(by: bytesPerRow)
                    }
                }
                CVPixelBufferUnlockBaseAddress(imageBuffer, [])
            }

            let feature = MLFeatureValue(pixelBuffer: imageBuffer)
            let inputProvider = try MLDictionaryFeatureProvider(dictionary: ["input": feature])
            let prediction = try model.prediction(from: inputProvider)

            if let outFeature = prediction.featureValue(for: "output") ?? prediction.featureValue(for: "var_182"),
               let outPixelBuffer = outFeature.imageBufferValue {
                if self.isMonochrome {
                    CVPixelBufferLockBaseAddress(outPixelBuffer, [])
                    if let baseAddress = CVPixelBufferGetBaseAddress(outPixelBuffer) {
                        let bytesPerRow = CVPixelBufferGetBytesPerRow(outPixelBuffer)
                        let width = CVPixelBufferGetWidth(outPixelBuffer)
                        let height = CVPixelBufferGetHeight(outPixelBuffer)
                        var ptr = baseAddress.assumingMemoryBound(to: UInt8.self)
                        for _ in 0..<height {
                            for x in 0..<width {
                                let b = UInt32(ptr[x * 4])
                                let g = UInt32(ptr[x * 4 + 1])
                                let r = UInt32(ptr[x * 4 + 2])
                                let gray = UInt8((r * 77 + g * 150 + b * 29) >> 8)
                                ptr[x * 4] = gray
                                ptr[x * 4 + 1] = gray
                                ptr[x * 4 + 2] = gray
                            }
                            ptr = ptr.advanced(by: bytesPerRow)
                        }
                    }
                    CVPixelBufferUnlockBaseAddress(outPixelBuffer, [])
                }

                if !adaptor.append(outPixelBuffer, withPresentationTime: pts) {
                    print("Warning: append failed at frame \(frameCount)")
                }
                frameCount += 1
            }
        } catch {
            print("Inference error at frame \(frameCount): \(error)")
        }

        let now: CFAbsoluteTime = CFAbsoluteTimeGetCurrent()
        if now - lastLogTime >= 3.0 {
            let intervalFrames: Int = frameCount - lastLogFrames
            let curFps: Double = Double(intervalFrames) / (now - lastLogTime)
            let totalElapsed: Double = now - startTime
            let aggFps: Double = Double(frameCount) / totalElapsed
            let pct: Double = totalFrames > 0 ? Double(frameCount) / Double(totalFrames) * 100.0 : 0.0
            print(String(format: "Frame %d/%d (%.1f%%) | Live Speed: %.2f fps | Aggregate: %.2f fps",
                         frameCount, totalFrames, pct, curFps, aggFps))
            fflush(stdout)
            lastLogTime = now
            lastLogFrames = frameCount
        }
        return true
    }
}

// Entry point
let args = CommandLine.arguments
if args.count < 3 {
    print("Usage: argolis-upscale <input.mp4> <output_1080p.mp4> [--mono] [--engine ane|gpu|all] [--model <path>]")
    exit(1)
}

let inputPath = args[1]
let outputPath = args[2]
let isMono = args.contains("--mono") || args.contains("--bw")
var computeUnits: MLComputeUnits = .all
if args.contains("--engine") {
    if let idx = args.firstIndex(of: "--engine"), idx + 1 < args.count {
        let e = args[idx + 1].lowercased()
        if e == "ane" { computeUnits = .cpuAndNeuralEngine }
        else if e == "gpu" { computeUnits = .cpuAndGPU }
    }
}

var modelPath = "/Volumes/Seagate External/Development/Manhattan/tools/realesrgan/models/realesr_1080p_zerocopy.mlmodelc"
if args.contains("--model"), let idx = args.firstIndex(of: "--model"), idx + 1 < args.count {
    modelPath = args[idx + 1]
} else if let envModel = ProcessInfo.processInfo.environment["ARGOLIS_MODEL_PATH"], !envModel.isEmpty {
    modelPath = envModel
} else {
    let binURL = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    let candidateRelative = binURL.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("realesrgan/models/realesr_1080p_zerocopy.mlmodelc").path
    if FileManager.default.fileExists(atPath: candidateRelative) {
        modelPath = candidateRelative
    }
}
let modelURL = URL(fileURLWithPath: modelPath)

let upscaler = ArgolisUpscaler(
    inputURL: URL(fileURLWithPath: inputPath),
    outputURL: URL(fileURLWithPath: outputPath),
    modelURL: modelURL,
    isMonochrome: isMono,
    computeUnits: computeUnits
)

do {
    try upscaler.run()
} catch {
    print("Fatal Error: \(error.localizedDescription)")
    exit(1)
}
