# Проверка смеха

`voices/` содержит локальные английские записи из установленной Dota 2:

- `laugh.mp3` — `sounds/vo/invoker/invo_laugh_01.vsnd_c`
- `knowing.mp3` — `sounds/vo/invoker/invo_respawn_10.vsnd_c`
- `carl.mp3` — `sounds/vo/invoker/invo_rare_04.vsnd_c`

Файлы извлечены из `game/dota/pak01_dir.vpk` с помощью Source 2 Viewer CLI; аудио исключено из Git. Расположение и номера могут отличаться после обновления игры.

Для сборки анализатора на macOS из корня проекта:

```bash
mkdir -p /tmp/dota-swift-cache
xcrun swiftc -module-cache-path /tmp/dota-swift-cache experiments/laughter/analyze.swift -o experiments/laughter/analyze-laughter
xcrun swiftc -module-cache-path /tmp/dota-swift-cache experiments/laughter/stream.swift -o experiments/laughter/stream-laughter
```

Запуск пробы:

```bash
.venv/bin/python experiments/laughter/test_laughter.py
```

Анализ выполняется локально встроенным Apple Sound Analysis. Шестисекундная запись хранится во временном каталоге и удаляется после анализа. Проба не управляет игрой и не запускает реплики автоматически. Основная программа при включённом вводе отслеживает смех и воспроизводит одну из трёх локальных реплик; период между срабатываниями — минимум 20 секунд.
