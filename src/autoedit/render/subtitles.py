"""Subtitle generation — karaoke-style ASS subtitles from word-level timestamps.

Each subtitle *line* covers a phrase of up to ``words_per_line`` words.
Within a line every word is wrapped in an ASS karaoke marker ``{\\kN}``
(N = duration in centiseconds) so media players highlight each word as it
is spoken — matching the ConnorDawg / TikTok caption style.

A new phrase is forced when:
* the word count reaches ``words_per_line``, OR
* the gap between consecutive words exceeds ``max_line_gap_sec``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Word:
    """A single word with its start/end time in seconds."""

    text: str
    start_sec: float
    end_sec: float


def build_ass_subtitles(
    words: list[Word],
    play_res_x: int = 1920,
    play_res_y: int = 1080,
    words_per_line: int = 5,
    max_line_gap_sec: float = 1.5,
) -> str:
    """Build a complete ASS subtitle document with karaoke word markers.

    Args:
        words: Ordered list of :class:`Word` objects with timestamps.
        play_res_x: Canvas width in pixels (1920 for 16:9 YouTube, 1080 for 9:16 TikTok).
        play_res_y: Canvas height in pixels (1080 for 16:9 YouTube, 1920 for 9:16 TikTok).
        words_per_line: Maximum words before a line break is forced.
        max_line_gap_sec: Force a line break when silence between words
            exceeds this threshold (natural speech pause detection).

    Returns:
        A complete ``.ass`` document as a single string.
    """
    header = [
        "[Script Info]",
        f"PlayResX: {play_res_x}",
        f"PlayResY: {play_res_y}",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "Collisions: Normal",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        # White text, yellow karaoke highlight, thick black outline, bottom-center
        (
            "Style: Default,Arial Black,72,"
            "&H00FFFFFF,&H00FFFF00,&H00000000,&H80000000,"
            "-1,0,0,0,100,100,0,0,1,4,1,2,40,40,200,1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    if not words:
        return "\n".join(header)

    # ----------------------------------------------------------------
    # Group words into phrase lines
    # ----------------------------------------------------------------
    phrases: list[list[Word]] = []
    current: list[Word] = []

    for word in words:
        if current:
            gap = word.start_sec - current[-1].end_sec
            if len(current) >= words_per_line or gap >= max_line_gap_sec:
                phrases.append(current)
                current = []
        current.append(word)

    if current:
        phrases.append(current)

    # ----------------------------------------------------------------
    # Emit one Dialogue event per phrase
    # ----------------------------------------------------------------
    dialogue_lines: list[str] = []
    for phrase in phrases:
        phrase_start = _format_ass_time(phrase[0].start_sec)
        phrase_end = _format_ass_time(phrase[-1].end_sec)

        karaoke_parts: list[str] = []
        for word in phrase:
            # Duration in centiseconds (minimum 1 cs to avoid zero-duration markers)
            dur_cs = max(1, int((word.end_sec - word.start_sec) * 100))
            karaoke_parts.append(f"{{\\k{dur_cs}}}{word.text}")

        # Words joined by space; the karaoke timing accounts for gaps
        text = " ".join(karaoke_parts)
        dialogue_lines.append(
            f"Dialogue: 0,{phrase_start},{phrase_end},Default,,0,0,0,,{text}"
        )

    return "\n".join(header + dialogue_lines)


def _format_ass_time(sec: float) -> str:
    """Format *sec* (float, non-negative) as ASS timestamp ``H:MM:SS.cc``."""
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int((sec % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
