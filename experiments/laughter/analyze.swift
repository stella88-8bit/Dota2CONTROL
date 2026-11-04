import Foundation
import SoundAnalysis

final class Observer: NSObject, SNResultsObserving {
    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let r = result as? SNClassificationResult else { return }
        let hits = r.classifications.filter { $0.identifier.localizedCaseInsensitiveContains("laugh") }
        for hit in hits { print("\(hit.identifier): \(String(format: "%.3f", hit.confidence))") }
        if let best = r.classifications.first { print("Лидер: \(best.identifier) \(String(format: "%.3f", best.confidence))") }
    }
    func request(_ request: SNRequest, didFailWithError error: Error) { fputs("Ошибка анализа: \(error)\n", stderr) }
    func requestDidComplete(_ request: SNRequest) {}
}

guard CommandLine.arguments.count == 2 else { fputs("Укажите WAV-файл\n", stderr); exit(1) }
do {
    let analyzer = try SNAudioFileAnalyzer(url: URL(fileURLWithPath: CommandLine.arguments[1]))
    let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
    request.overlapFactor = 0.5
    let observer = Observer()
    try analyzer.add(request, withObserver: observer)
    analyzer.analyze()
} catch { fputs("Ошибка: \(error)\n", stderr); exit(1) }
