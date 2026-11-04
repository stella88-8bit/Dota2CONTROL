"""Event-driven keyboard control, independent of Tk, Vosk and console output."""
import queue
import re
import threading
import time

from combo_runner import ComboRunner
from predictive_combo import PredictiveComboRunner
from combos import match_combo
from controls import NAMES, VOICE_KEYS, VOICE_PHRASES
from low_latency import LowLatencyActivity
from spell_planner import plan_spell
from combo_timing import plan_combo


class VoiceController:
    def __init__(self, gsi, capture, send, laughter=None, player=None, activity=None,
                 spell_database=None, target_distance=600):
        self.gsi, self.capture, self.send = gsi, capture, send
        self.laughter, self.player = laughter, player
        self.activity = activity if activity is not None else LowLatencyActivity()
        self.spell_database = spell_database
        self.target_distance = target_distance
        self.scepter_option = self.shard_option = None
        self.require_tornado_window = True
        self.enabled = self.playback = False
        self.enabled_at = 0.0
        self.active = None
        self.last_run = None
        self.events = queue.SimpleQueue()
        self.commands = queue.SimpleQueue()
        self.wakeup = gsi.changed
        self.capture.wakeup = self.wakeup
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._run, name='spell-control', daemon=True)
        self.thread.start()

    def _emit(self, kind, text):
        self.events.put((kind, text))

    def _command(self, kind, value=None, token=None):
        self.commands.put((kind, value, token))
        self.wakeup.set()

    def enable(self):
        self._command('enable')

    def disable(self, reason='Остановлено кнопкой', token=None):
        self._command('disable', reason, token)

    def audio_error(self, token):
        self._command('audio_error', token=token)

    def set_timing_options(self, distance, scepter_option=None, shard_option=None, require_tornado_window=True):
        self._command('timing', (float(distance), scepter_option, shard_option, bool(require_tornado_window)))

    def _disable(self, reason):
        self.enabled = False
        self.active = None
        self.capture.cancel()
        self.activity.stop()
        self._emit('status', reason)
        self._emit('log', reason)

    def _commands(self):
        while True:
            try:
                kind, value, token = self.commands.get_nowait()
            except queue.Empty:
                return
            if token is not None and token != self.capture.token:
                continue
            if kind == 'enable':
                if not self.capture.ready:
                    self._emit('status', 'Модель ещё загружается или недоступна')
                    continue
                self.capture.cancel()
                self.active = None
                self.activity.start()
                self.enabled_at = time.monotonic()
                self.enabled = True
                self._emit('status', 'Ввод включён — переключись в Dota')
                self._emit('log', 'Ввод включён.')
            elif kind == 'disable':
                self._disable(value)
            elif kind == 'audio_error':
                self.active = None
                self.capture.cancel()
                self._emit('last', 'Сбой аудио: действие отменено, слушаю следующую команду')
            elif kind == 'timing':
                self.target_distance, self.scepter_option, self.shard_option, self.require_tornado_window = value

    def _results(self):
        while self.active is None:
            try:
                token, text, error, received = self.capture.results.get_nowait()
            except queue.Empty:
                return
            if token != self.capture.token or not self.enabled or time.monotonic() - received > 1:
                continue
            if error:
                self._emit('last', 'Распознавание восстанавливается: ' + error)
                self._emit('log', 'Ошибка Whisper, ожидаю следующую команду: ' + error)
                continue
            self._emit('log', 'Whisper: ' + text)
            normalized = ' '.join(re.sub(r'[^\w\s]', ' ', text.lower()).split())
            if normalized == 'стоп':
                self._disable('Остановлено командой «стоп»')
                return
            match = match_combo(text)
            if match:
                if not self.gsi.details():
                    self._emit('last', 'Прокаст отменён: нет свежих данных GSI')
                    continue
                self._start(match[1], 'Прокаст: ' + match[0], received, predictive=True)
                return
            direct = {**VOICE_KEYS, **VOICE_PHRASES}.get(normalized)
            if direct:
                self._send(direct)
                continue
            plan = plan_spell(text, self.gsi.snapshot(max_age=2))
            if not plan:
                self._emit('last', 'Фраза не распознана или нет свежих данных GSI')
                continue
            if plan.kind == 'invoke':
                self._send('r')
            else:
                # Solo spells use exactly the same fast, GSI-verified executor.
                self._start((plan.spell,), 'Заклинание: ' + plan.spell, received)
                return

    def _start(self, spells, label, received, predictive=False):
        timing = None
        if predictive and self.spell_database is not None:
            hero, abilities, _ = self.gsi.read_context()
            try:
                if not hero or not abilities:
                    raise ValueError('Нет свежих данных героя GSI')
                if hero.get('alive') is False or hero.get('stunned') or hero.get('silenced') or hero.get('hexed'):
                    raise ValueError('Invoker сейчас не может применять заклинания')
                profile = self.spell_database.from_gsi(hero, abilities,
                    scepter_option=self.scepter_option, shard_option=self.shard_option)
                timing = plan_combo(spells, profile, abilities, self.target_distance,
                                    self.spell_database.metadata['source_sha256'])
                if timing.blocked_reason:
                    raise ValueError(timing.blocked_reason)
                if 'tornado' in spells and not timing.synchronized and self.require_tornado_window:
                    raise ValueError('В модели нет общего окна попадания после Tornado при этих уровнях и дистанции. Можно изменить условия или снять требование общего окна.')
                mana = sum(profile['spells'][s]['values'].get('AbilityManaCost',0) for s in spells)
                if hero.get('mana') is not None and hero['mana'] < mana:
                    raise ValueError(f'Для полного прокаста нужно {mana:g} маны; доступно {hero["mana"]:g}')
            except ValueError as error:
                self._emit('last', 'Прокаст не запущен: ' + str(error))
                self._emit('log', 'Прокаст не запущен: ' + str(error))
                return
            spells = timing.order
            self._emit('log', f'Профиль: уровень {profile["hero_level"]}, Q/W/E {profile["levels"]}; расстояние {self.target_distance:g} ед. (оценка)')
            self._emit('log', 'Порядок по таймингам: ' + ' → '.join(spells))
            if timing.landing is not None:
                self._emit('log', f'Расчётное приземление Tornado: {timing.landing:.3f} с от начала; подъём {timing.nominal_lift:.3f} с')
            for warning in timing.warnings:
                self._emit('log', 'Условие прокаста: ' + warning)
            if hero.get('aghanims_scepter') and profile['scepter_option'] is None:
                self._emit('log', 'Выбор Scepter не определён GSI: укажи выбранную сферу в окне программы.')
        now = time.monotonic()
        self.active = (PredictiveComboRunner(spells, received, timing=timing) if predictive
                       else ComboRunner(spells, received))
        self._emit('last', label)
        self._emit('log', f'{label} — начало [0.000 с]; очередь команды {(now-received)*1000:.1f} мс')

    def _send(self, key, self_target=False):
        self.send(key, self_target)
        if self.active is None:
            self._emit('last', f'Отправлено: {NAMES[key]} [{key.upper()}]')

    def _advance(self):
        self._commands()
        if not self.enabled or self.closed.is_set():
            return
        run = self.active
        if run is None:
            return
        now = time.monotonic()
        if getattr(run, 'predictive', False):
            details, packet_at = self.gsi.read(max_age=2)
            action = run.step(now, details, packet_at)
        else:
            details = self.gsi.details(max_age=2, after=run.after)
            fresh = details is not None
            if not fresh and run.phase == 'cast_confirm':
                details = self.gsi.details(max_age=2)
            action = run.step(now, details, fresh=fresh)
        # Send before formatting or publishing diagnostics.
        if action:
            started = time.monotonic()
            self._send(*action)
            finished = time.monotonic()
            if finished - started > .05:
                self._emit('log', f'Отправка {action[0].upper()} заняла {(finished-started)*1000:.1f} мс')
        for kind, spell, stamp, interval in run.events:
            elapsed = stamp - run.started_at
            if kind == 'note':
                self._emit('log', f'[{elapsed:.3f} с] {spell}')
                continue
            if kind == 'cast':
                gap = f'; после предыдущей команды {interval:.3f} с' if interval is not None else ''
                text = f'команда применения{gap}'
            elif kind == 'retry':
                text = 'повторная попытка'
            elif kind == 'invoke':
                text = 'команда Invoke'
            elif kind == 'preparing':
                text = 'сферы заранее: ожидаю подтверждения предыдущего применения'
            elif kind == 'invoked':
                text = f'GSI подтвердил ячейку; ожидание {interval:.3f} с'
            else:
                text = f'GSI показывает перезарядку; ожидание {interval:.3f} с'
            self._emit('log', f'[{elapsed:.3f} с] {spell}: {text}')
        run.events.clear()
        if run.error or run.complete:
            elapsed = time.monotonic() - run.started_at
            message = ('Прокаст остановлен: ' + run.error if run.error else
                       f'Выполнено за {elapsed:.3f} с (от распознавания до подтверждения GSI).')
            if getattr(run, 'predictive', False) and not run.error:
                dispatched = run.dispatch_complete_at - run.started_at
                missing = ', '.join(s for s in run.spells if s not in run.confirmed) or 'нет'
                message = (f'Отправка прокаста: {dispatched:.3f} с; проверка завершена через {elapsed:.3f} с. '
                           f'Не подтверждены GSI: {missing}')
                if run.timing is not None:
                    estimates = run.timing.impact_report(run.sent, run.started_at)
                    for spell, estimate in estimates.items():
                        self._emit('log', f'Расчёт {spell}: {estimate["relative_to_landing_s"]:+.3f} с от приземления (оценка, не подтверждение попадания)')
            self._emit('last', message)
            self._emit('log', message)
            self._emit('log', self.gsi.timing_summary())
            self.last_run = run
            self.active = None

    def _laughter(self):
        if self.player:
            self.playback = self.player.is_playing()
        if not self.laughter:
            return
        while True:
            try:
                detected_at = self.laughter.events.get_nowait()
            except queue.Empty:
                return
            if (self.enabled and self.active is None and not self.playback
                    and detected_at >= self.enabled_at and time.monotonic() - detected_at < 2):
                try:
                    chosen = self.player.play()
                    if chosen:
                        self.playback = True
                        self.capture.cancel()
                        self._emit('last', 'Смех: воспроизводится реплика Invoker')
                        self._emit('log', 'Реплика Invoker: ' + chosen)
                except OSError as error:
                    self._emit('log', 'Не удалось воспроизвести реплику: ' + str(error))

    def _run(self):
        try:
            while not self.closed.is_set():
                # Clear before reading queues so a concurrent update cannot be lost.
                self.wakeup.clear()
                try:
                    self._commands()
                    self._advance()
                    self._laughter()
                    if not self.playback:
                        self._results()
                    if self.active is not None:
                        self._advance()
                except Exception as error:
                    self._disable('Ошибка управления: ' + str(error))
                run = self.active
                timeout = .02
                if run is not None and getattr(run, 'predictive', False):
                    timeout = run.wait_time(time.monotonic())
                elif run is not None:
                    if run.phase == 'cast_confirm' and run.prepared_keys:
                        timeout = min(timeout, max(.001, run.prepare_at - time.monotonic()))
                    if run.phase == 'orbs':
                        timeout = min(timeout, max(0, run.next_at - time.monotonic()))
                        # Readiness may need a new packet even when next_at has passed.
                        timeout = max(.001, timeout)
                    elif run.phase == 'cast_confirm' and run.spells[run.index] == 'cold snap':
                        timeout = min(timeout, max(.001, run.next_at - time.monotonic()))
                self.wakeup.wait(timeout)
        finally:
            self.enabled = False
            self.active = None
            self.activity.stop()

    def close(self):
        self.closed.set()
        self.wakeup.set()
        self.thread.join(timeout=2)
