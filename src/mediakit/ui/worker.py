"""Qt adapter around `core.batch`. This is the ONLY place QThread lives.

Pattern: worker-object + QThread (not QThread subclassing). The worker is
a plain QObject; `moveToThread` puts its slots on the worker thread.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from mediakit.core.batch import BatchReport, CancelToken, WorkFn, run_batch


class BatchWorker(QObject):
    """Runs a batch on a worker thread and reports back with signals."""

    progress = Signal(int, int, str)  # done, total, current file name
    finished = Signal(object)  # BatchReport
    failed = Signal(str)  # unexpected, batch-level error

    def __init__(self, items: list[Path], work: WorkFn, cancel: CancelToken) -> None:
        super().__init__()
        self._items = items
        self._work = work
        self._cancel = cancel

    def run(self) -> None:
        try:
            report = run_batch(
                self._items,
                self._work,
                on_progress=self._emit_progress,
                cancel=self._cancel,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(report)

    def _emit_progress(self, done: int, total: int, name: str) -> None:
        # Called on the worker thread; the signal hops to the GUI thread
        # automatically (queued connection across threads).
        self.progress.emit(done, total, name)


class BatchJob(QObject):
    """Owns a worker + its thread and keeps both alive until finished.

    Without holding a Python reference the QThread is garbage collected
    mid-run and the app crashes. That is why this wrapper exists.
    """

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        items: list[Path],
        work: WorkFn,
        parent: QObject | None = None,
        cancel: CancelToken | None = None,
    ) -> None:
        super().__init__(parent)
        # A caller may pass its own token so the work function can poll
        # it too (cancel in the middle of one long item).
        self.cancel_token = cancel or CancelToken()
        self._thread = QThread()
        self._worker = BatchWorker(items, work, self.cancel_token)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def _shutdown(self) -> None:
        self._thread.quit()
        self._thread.wait()

    def _on_finished(self, report: BatchReport) -> None:
        self._shutdown()
        self.finished.emit(report)

    def _on_failed(self, message: str) -> None:
        self._shutdown()
        self.failed.emit(message)


# on_progress(done, total) - units are up to the task (bytes, steps...)
TaskFn = Callable[[Callable[[int, int], None], CancelToken], object]


class _TaskWorker(QObject):
    progress = Signal(object, object)  # done, total (object: ints > 2**31)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: TaskFn, cancel: CancelToken) -> None:
        super().__init__()
        self._fn = fn
        self._cancel = cancel

    def run(self) -> None:
        try:
            result = self._fn(lambda d, t: self.progress.emit(d, t), self._cancel)
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class TaskJob(QObject):
    """One long-running call (model download, single preview) on a
    worker thread. Same lifetime rules as BatchJob."""

    progress = Signal(object, object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: TaskFn, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cancel_token = CancelToken()
        self._thread = QThread()
        self._worker = _TaskWorker(fn, self.cancel_token)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def _shutdown(self) -> None:
        self._thread.quit()
        self._thread.wait()

    def _on_finished(self, result: object) -> None:
        self._shutdown()
        self.finished.emit(result)

    def _on_failed(self, message: str) -> None:
        self._shutdown()
        self.failed.emit(message)
