"""Pure common splitter: no file I/O and no fitted model dependencies."""


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
