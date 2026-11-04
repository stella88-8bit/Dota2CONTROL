import Foundation
import AVFoundation
import SoundAnalysis

final class Observer: NSObject, SNResultsObserving {
    private var consecutive = 0
    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let result = result as? SNClassificationResult else { return }
        let score = result.classifications.first { $0.identifier == "laughter" }?.confidence ?? 0
        if score >= 0.50 { consecutive += 1 } else { consecutive = 0 }
        if consecutive >= 2 {
            print("LAUGH \(score)")
            fflush(stdout)
            consecutive = 0
        }
    }
    func request(_ request: SNRequest, didFailWithError error: Error) { fputs("Sound Analysis: \(error)\n", stderr) }
    func requestDidComplete(_ request: SNRequest) {}
}

guard CommandLine.arguments.count == 2, let rate = Double(CommandLine.arguments[1]), rate > 0,
      let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: rate, channels: 1, interleaved: true) else { exit(1) }
do {
    let analyzer = SNAudioStreamAnalyzer(format: format)
    let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
    request.overlapFactor = 0.5
    let observer = Observer()
    try analyzer.add(request, withObserver: observer)
    var frame: AVAudioFramePosition = 0
    while let data = try FileHandle.standardInput.read(upToCount: 2048), !data.isEmpty {
        let count = data.count / MemoryLayout<Int16>.size
        guard count > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(count)), let target = buffer.int16ChannelData else { continue }
        buffer.frameLength = AVAudioFrameCount(count)
        data.withUnsafeBytes { source in
            if let base = source.baseAddress { memcpy(target[0], base, count * 2) }
        }
        analyzer.analyze(buffer, atAudioFramePosition: frame)
        frame += AVAudioFramePosition(count)
    }
    analyzer.completeAnalysis()
    Thread.sleep(forTimeInterval: 0.5)
} catch { fputs("Sound Analysis: \(error)\n", stderr); exit(1) }
