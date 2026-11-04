"""Build the persistent worker against the project's whisper.cpp libraries."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent
source = root / 'integration/whisper.cpp'
bin_dir = root / 'integration/whisper-bin'
if not (source / 'include/whisper.h').exists():
    raise SystemExit('Сначала загрузите исходники whisper.cpp в integration/whisper.cpp.')
subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O3', '-arch', 'arm64',
                '-I', str(source / 'include'), '-I', str(source / 'ggml/include'),
                str(root / 'integration/whisper_worker.cpp'), '-L', str(bin_dir),
                '-lwhisper', '-Wl,-rpath,@executable_path',
                '-o', str(bin_dir / 'whisper-worker')], check=True)
print('Whisper worker собран.')
