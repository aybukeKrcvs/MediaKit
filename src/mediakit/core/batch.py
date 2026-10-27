"""Generic batch runner. Pure Python, no Qt.

Every module (image / audio / pdf) reuses this: the caller supplies a
`work` callable that handles ONE item. This file knows nothing about
images, PDFs or audio.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path


class CancelToken:
    """Thread-safe cancel flag. The UI sets it, the worker polls it."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class ItemResult:
    source: Path
    output: Path | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.output is not None

    @property
    def skipped(self) -> bool:
        return self.error is None and self.output is None


@dataclass
class BatchReport:
    results: list[ItemResult] = field(default_factory=list)
    cancelled: bool = False

    @property
    def succeeded(self) -> list[ItemResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[ItemResult]:
        return [r for r in self.results if r.error is not None]

    @property
    def skipped(self) -> list[ItemResult]:
        return [r for r in self.results if r.skipped]


# work(item) -> output path, or None when the item was skipped
WorkFn = Callable[[Path], Path | None]
# on_progress(done, total, current_item_name)
ProgressFn = Callable[[int, int, str], None]


def run_batch(
    items: Iterable[Path],
    work: WorkFn,
    on_progress: ProgressFn | None = None,
    cancel: CancelToken | None = None,
) -> BatchReport:
    """Run `work` over `items`, collecting results instead of raising.

    One bad file must never kill the whole batch, so exceptions are
    captured per item and turned into `ItemResult.error`.
    """
    items = list(items)
    total = len(items)
    report = BatchReport()

    for index, item in enumerate(items, start=1):
        if cancel is not None and cancel.cancelled:
            report.cancelled = True
            break

        if on_progress is not None:
            on_progress(index - 1, total, item.name)

        try:
            output = work(item)
            report.results.append(ItemResult(source=item, output=output))
        except Exception as exc:  # noqa: BLE001 - deliberate: isolate per item
            report.results.append(ItemResult(source=item, error=f"{type(exc).__name__}: {exc}"))

        if on_progress is not None:
            on_progress(index, total, item.name)

    return report
