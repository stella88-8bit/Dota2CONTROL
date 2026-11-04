"""Keep active voice control responsive when its window is in the background."""
import sys


class LowLatencyActivity:
    def __init__(self):
        self._process = self._token = None

    def start(self):
        if sys.platform != 'darwin' or self._token is not None:
            return
        from Foundation import (NSProcessInfo, NSActivityLatencyCritical,
                                NSActivityUserInitiatedAllowingIdleSystemSleep)
        self._process = NSProcessInfo.processInfo()
        self._token = self._process.beginActivityWithOptions_reason_(
            NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityLatencyCritical,
            'DOTA MAGIC active voice control')

    def stop(self):
        if self._token is not None:
            self._process.endActivity_(self._token)
            self._token = None
