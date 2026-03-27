"""Formatting utilities for Telegram bot output."""


def fmt_number(value, prefix="$", decimals=0, suffix=""):
    """Format a number with commas and optional prefix/suffix."""
    if value is None:
        return "N/A"
    if decimals > 0:
        formatted = f"{value:,.{decimals}f}"
    else:
        formatted = f"{value:,.0f}"
    return f"{prefix}{formatted}{suffix}"


def fmt_millions(value, prefix="$", decimals=0):
    """Format a number in millions."""
    if value is None:
        return "N/A"
    return fmt_number(value / 1_000_000, prefix=prefix, decimals=decimals, suffix="")


def fmt_pct(value, decimals=1, plus=True):
    """Format a percentage with optional + sign."""
    if value is None:
        return "N/A"
    sign = "+" if plus and value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def fmt_multiplier(value, decimals=1):
    """Format as a multiplier (e.g., 40.2x)."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}x"


def build_table(headers, rows, alignments=None):
    """Build an ASCII table string.

    Args:
        headers: list of column header strings
        rows: list of lists, each inner list is a row of values
        alignments: list of 'l' or 'r' for left/right alignment per column.
                    Defaults to left for first column, right for rest.
    """
    num_cols = len(headers)
    if alignments is None:
        alignments = ['l'] + ['r'] * (num_cols - 1)

    # Convert all values to strings
    str_rows = [[str(v) for v in row] for row in rows]

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, val in enumerate(row):
            if i < num_cols:
                widths[i] = max(widths[i], len(val))

    # Add padding
    widths = [w + 1 for w in widths]

    def fmt_cell(val, width, align):
        if align == 'r':
            return val.rjust(width)
        return val.ljust(width)

    # Build header line
    header_line = " | ".join(
        fmt_cell(h, widths[i], alignments[i]) for i, h in enumerate(headers)
    )

    # Build separator
    sep_line = "-|-".join("-" * widths[i] for i in range(num_cols))

    # Build data rows
    data_lines = []
    for row in str_rows:
        padded = row + [""] * (num_cols - len(row))
        line = " | ".join(
            fmt_cell(padded[i], widths[i], alignments[i]) for i in range(num_cols)
        )
        data_lines.append(line)

    return "\n".join([header_line, sep_line] + data_lines)


def telegram_msg(title, body, footer=None):
    """Wrap content in HTML pre tags for Telegram monospace display."""
    parts = [f"<b>{title}</b>", f"<pre>{body}</pre>"]
    if footer:
        parts.append(footer)
    return "\n".join(parts)


def escape_html(text):
    """Escape HTML special characters for Telegram HTML mode."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
