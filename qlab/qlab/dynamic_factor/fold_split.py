"""Pure common splitter: no file I/O and no fitted model dependencies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FoldViews:
    fold: dict
    splitter: object
    train: tuple
    warmup: tuple


def shared_views(calendar, fold, *, train_days, warmup_days):
    train = train_dates(calendar, fold)
    start = calendar.index(train[0])
    warmup = tuple(calendar[max(0, start - warmup_days) : start])
    if len(train) != train_days or len(warmup) != warmup_days:
        raise ValueError("reference.only_complete_train_warmup_visible")
    return FoldViews(fold, train_dates, train, warmup)


def reference_view(candidate_view, fold, splitter):
    if (
        candidate_view.fold is not fold
        or candidate_view.splitter is not splitter
        or splitter is not train_dates
    ):
        raise ValueError("reference.shared_splitter_or_fold_object_mismatch")
    # Return the SAME tuples, not another independently reconstructed date slice.
    return candidate_view.train, candidate_view.warmup


def train_dates(calendar, fold):
    start = calendar.index(fold["train_start"])
    end = calendar.index(fold["history_end"])
    if start > end:
        raise ValueError("wf.train_bounds_invalid")
    return tuple(calendar[start : end + 1])


def train_slice(rows, dates):
    allowed = set(dates)
    selected = [r for r in rows if r["date"] in allowed]
    if [r["date"] for r in selected] != list(dates):
        raise ValueError("wf.train_input_calendar_incomplete")
    return selected
