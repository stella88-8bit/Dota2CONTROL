// Persistent local recognizer. stdin: uint32 sample count + float32 PCM at 16 kHz.
// stdout: uint32 UTF-8 byte count + transcript. Zero-length startup frame = ready.
#include "whisper.h"
#include <cstdio>
#include <cstdint>
#include <string>
#include <vector>
#include <cstdlib>

int main(int argc, char **argv) {
    if (argc != 2) return 1;
    auto cp = whisper_context_default_params();
    cp.use_gpu = std::getenv("DOTA_WHISPER_CPU") == nullptr;
    auto *ctx = whisper_init_from_file_with_params(argv[1], cp);
    if (!ctx && cp.use_gpu) {
        cp.use_gpu = false;
        ctx = whisper_init_from_file_with_params(argv[1], cp);
    }
    if (!ctx) return 2;
    auto p = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    p.n_threads = 4;
    p.language = "ru";
    p.no_context = true;
    p.no_timestamps = true;
    p.single_segment = true;
    p.print_progress = p.print_realtime = p.print_timestamps = p.print_special = false;
    p.greedy.best_of = 1;
    p.max_tokens = 96;
    uint32_t ready = 0;
    fwrite(&ready, sizeof(ready), 1, stdout); fflush(stdout);
    uint32_t count;
    while (fread(&count, sizeof(count), 1, stdin) == 1) {
        if (!count || count > 16000 * 10) break;
        std::vector<float> samples(count);
        if (fread(samples.data(), sizeof(float), count, stdin) != count) break;
        if (whisper_full(ctx, p, samples.data(), count)) { whisper_free(ctx); return 3; }
        std::string text;
        for (int i=0; i<whisper_full_n_segments(ctx); ++i) text += whisper_full_get_segment_text(ctx, i);
        uint32_t size = text.size();
        fwrite(&size, sizeof(size), 1, stdout);
        fwrite(text.data(), 1, size, stdout); fflush(stdout);
    }
    whisper_free(ctx);
}
