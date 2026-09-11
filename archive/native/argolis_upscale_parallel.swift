import Foundation
import AVFoundation
import CoreMedia
import CoreVideo
import CoreML
import VideoToolbox

final class ParallelUpscaler {
    let inputURL: URL
    let outputURL: URL
    let modelURL: URL
    let isMonochrome: Bool

    init(inputURL: URL, outputURL: URL, modelURL: URL, isMonochrome: Bool = false) {
        self.inputURL = inputURL
        self.outputURL = outputURL
        self.modelURL = modelURL
        self.isMonochrome = isMonochrome
    }

    func run() throws {
        setlinebuf(stdout)
        let startTime = CFAbsoluteTimeGetCurrent()
        print("======================================================================")
        print("ARGOLIS DUAL-ENGINE CONCURRENT SWIFT REMASTER (ANE + GPU)")
        print("Input:        \(inputURL.path)")
        print("Output:       \(outputURL.path)")
        print("Model:        \(modelURL.lastPathComponent)")
        print("Architecture: Asynchronous Dual-Model Parallel Hardware Pipeline")
        print("======================================================================")

        // 1. Load Dual CoreML Models (One ANE, One GPU)
        let configANE = MLModelConfiguration()
        configANE.computeUnits = .cpuAndNeuralEngine
        configANE.allowLowPrecisionAccumulationOnGPU = true

        let configGPU = MLModelConfiguration()
        configGPU.computeUnits = .cpuAndGPU
        configGPU.allowLowPrecisionAccumulationOnGPU = true

        print("Loading Model Instance 1 (16-Core Neural Engine)...")
        let modelANE = try MLModel(contentsOf: modelURL, configuration: configANE)
        print("Loading Model Instance 2 (10-Core Metal GPU)...")
        let modelGPU = try MLModel(contentsOf: modelURL, configuration: configGPU)
        print("Both hardware engines loaded successfully.")

        // 2. Setup AVAssetReader
        let asset = AVURLAsset(url: inputURL)
        let duration = CMTimeGetSeconds(asset.duration)
        guard let videoTrack = asset.tracks(withMediaType: .video).first else {
            throw NSError(domain: "Argolis", code: 1, userInfo: [NSLocalizedDescriptionKey: "No video track found."])
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

        var audioOutput: AVAssetReaderTrackOutput?
        if let audioTrack = asset.tracks(withMediaType: .audio).first {
            let audioReaderSettings: [String: Any] = [AVFormatIDKey: Int(kAudioFormatLinearPCM)]
            let aOut = AVAssetReaderTrackOutput(track: audioTrack, outputSettings: audioReaderSettings)
            aOut.alwaysCopiesSampleData = false
            if reader.canAdd(aOut) {
                reader.add(aOut)
                audioOutput = aOut
            }
        }

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

        var audioWriterInput: AVAssetWriterInput?
        if audioOutput != nil {
            let audioWriterSettings: [String: Any] = [
                AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
                AVSampleRateKey: 48000,
                AVNumberOfChannelsKey: 2,
                AVEncoderBitRateKey: 192000
            ]
            let aIn = AVAssetWriterInput(mediaType: .audio, outputSettings: audioWriterSettings)
            aIn.expectsMediaDataInRealTime = false
            if writer.canAdd(aIn) {
                writer.add(aIn)
                audioWriterInput = aIn
            }
        }

        guard reader.startReading() else { throw NSError(domain: "Argolis", code: 2, userInfo: [:]) }
        guard writer.startWriting() else { throw NSError(domain: "Argolis", code: 3, userInfo: [:]) }
        writer.startSession(atSourceTime: .zero)

        print("Beginning Dual-Engine Concurrent Hardware Remaster...")

        struct ProcessedFrame {
            let index: Int
            let pts: CMTime
            let pixelBuffer: CVPixelBuffer
        }

        let workerQueueANE = DispatchQueue(label: "com.argolis.worker.ane", qos: .userInteractive)
        let workerQueueGPU = DispatchQueue(label: "com.argolis.worker.gpu", qos: .userInteractive)
        let writerQueue = DispatchQueue(label: "com.argolis.writer", qos: .userInitiated)
        let group = DispatchGroup()

        var frameIndex = 0
        var completedFrames = 0
        var firstPTS: CMTime?
        var bufferMap = [Int: ProcessedFrame]()
        var nextWriteIndex = 0
        var isReadingFinished = false

        let lock = NSLock()
        let semaphore = DispatchSemaphore(value: 8) // Limit inflight frames to 8 to cap memory

        var lastLogTime = CFAbsoluteTimeGetCurrent()
        var lastLogFrames = 0

        func writePendingFrames() {
            while let frame = bufferMap[nextWriteIndex] {
                if !videoWriterInput.isReadyForMoreMediaData {
                    break
                }
                if !adaptor.append(frame.pixelBuffer, withPresentationTime: frame.pts) {
                    print("Warning: append failed at frame \(frame.index)")
                }
                bufferMap.removeValue(forKey: nextWriteIndex)
                nextWriteIndex += 1
                completedFrames += 1

                let now = CFAbsoluteTimeGetCurrent()
                if now - lastLogTime >= 3.0 {
                    let intervalFrames = completedFrames - lastLogFrames
                    let curFps = Double(intervalFrames) / (now - lastLogTime)
                    let totalElapsed = now - startTime
                    let aggFps = Double(completedFrames) / totalElapsed
                    let pct = totalFrames > 0 ? Double(completedFrames) / Double(totalFrames) * 100.0 : 0.0
                    print(String(format: "Frame %d/%d (%.1f%%) | Live Speed: %.2f fps | Aggregate: %.2f fps",
                                 completedFrames, totalFrames, pct, curFps, aggFps))
                    fflush(stdout)
                    lastLogTime = now
                    lastLogFrames = completedFrames
                }
            }
        }

        // Processing loop: read sample buffer, alternate between ANE and GPU workers
        while let sampleBuffer = videoOutput.copyNextSampleBuffer() {
            guard let imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { continue }
            let rawPTS = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            if firstPTS == nil { firstPTS = rawPTS }
            let pts = firstPTS != nil ? CMTimeSubtract(rawPTS, firstPTS!) : rawPTS

            let currentIdx = frameIndex
            frameIndex += 1

            let targetModel = (currentIdx % 2 == 0) ? modelANE : modelGPU
            let targetQueue = (currentIdx % 2 == 0) ? workerQueueANE : workerQueueGPU

            semaphore.wait()
            group.enter()

            targetQueue.async {
                autoreleasepool {
                    do {
                        let feature = MLFeatureValue(pixelBuffer: imageBuffer)
                        let inputProvider = try MLDictionaryFeatureProvider(dictionary: ["input": feature])
                        let prediction = try targetModel.prediction(from: inputProvider)

                        if let outFeature = prediction.featureValue(for: "output") ?? prediction.featureValue(for: "var_182"),
                           let outPixelBuffer = outFeature.imageBufferValue {
                            lock.lock()
                            bufferMap[currentIdx] = ProcessedFrame(index: currentIdx, pts: pts, pixelBuffer: outPixelBuffer)
                            writePendingFrames()
                            lock.unlock()
                        }
                    } catch {
                        print("Error processing frame \(currentIdx): \(error)")
                    }
                    semaphore.signal()
                    group.leave()
                }
            }
        }

        group.wait()

        // Flush remaining frames
        lock.lock()
        while nextWriteIndex < frameIndex {
            if let frame = bufferMap[nextWriteIndex] {
                adaptor.append(frame.pixelBuffer, withPresentationTime: frame.pts)
                bufferMap.removeValue(forKey: nextWriteIndex)
                nextWriteIndex += 1
                completedFrames += 1
            } else {
                break
            }
        }
        lock.unlock()

        videoWriterInput.markAsFinished()

        // Audio Copy
        if let aOut = audioOutput, let aIn = audioWriterInput {
            let audioGroup = DispatchGroup()
            let audioQueue = DispatchQueue(label: "com.argolis.audio")
            audioGroup.enter()
            aIn.requestMediaDataWhenReady(on: audioQueue) {
                while aIn.isReadyForMoreMediaData {
                    guard let aSample = aOut.copyNextSampleBuffer() else {
                        aIn.markAsFinished()
                        audioGroup.leave()
                        return
                    }
                    aIn.append(aSample)
                }
            }
            audioGroup.wait()
        }

        let finishGroup = DispatchGroup()
        finishGroup.enter()
        writer.finishWriting { finishGroup.leave() }
        finishGroup.wait()

        let totalTime = CFAbsoluteTimeGetCurrent() - startTime
        let finalFPS = Double(completedFrames) / totalTime
        let fileSize = (try? FileManager.default.attributesOfItem(atPath: outputURL.path)[.size] as? Double) ?? 0.0
        let outSizeMB = fileSize / (1024.0 * 1024.0)

        print("\n======================================================================")
        print("SUCCESS: Dual-Engine Concurrent Remaster Complete!")
        print(String(format: "Master Output:  %@ (%.1f MB)", outputURL.path, outSizeMB))
        print(String(format: "Total Frames:   %d frames in %.2fs (%.2f mins)", completedFrames, totalTime, totalTime / 60.0))
        print(String(format: "Throughput:     %.2f FPS (%.2fx Real-Time Speed)", finalFPS, finalFPS / 25.0))
        print("======================================================================\n")
    }
}

let inputPath = CommandLine.arguments[1]
let outputPath = CommandLine.arguments[2]
let modelPath = "/Volumes/Seagate External/Development/Manhattan/tools/realesrgan/models/realesr_1080p_zerocopy.mlmodelc"
let modelURL = URL(fileURLWithPath: modelPath)

let upscaler = ParallelUpscaler(inputURL: URL(fileURLWithPath: inputPath), outputURL: URL(fileURLWithPath: outputPath), modelURL: modelURL)
try upscaler.run()
