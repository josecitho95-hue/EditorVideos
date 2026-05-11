"""
TC-DOM-003 to TC-DOM-008: Pydantic domain schema tests for EditDecision and related types.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from autoedit.domain.edit_decision import (
    EditDecision,
    MemeOverlay,
    NarrationCue,
    SubtitleStyle,
    Trim,
    ZoomEvent,
    ZoomKind,
)
from autoedit.domain.ids import HighlightId, VodId, WindowId, new_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_edit_decision(highlight_id: HighlightId | None = None) -> EditDecision:
    return EditDecision(
        highlight_id=highlight_id or HighlightId(new_id()),
        title="Test clip",
        trim=Trim(start_sec=10.0, end_sec=50.0, reason="Test"),
        rationale="Test rationale",
    )


def _make_zoom_event(**overrides: Any) -> ZoomEvent:
    defaults: dict[str, Any] = {"at_sec": 5.0, "duration_sec": 0.5, "kind": ZoomKind.PUNCH_IN, "intensity": 1.8}
    defaults.update(overrides)
    return ZoomEvent(**defaults)


def _make_meme_overlay(**overrides: Any) -> MemeOverlay:
    defaults: dict[str, Any] = {
        "asset_id": new_id(),
        "at_sec": 6.0,
        "duration_sec": 1.5,
        "position": "center",
        "scale": 0.4,
        "enter_anim": "pop",
        "exit_anim": "fade",
    }
    defaults.update(overrides)
    return MemeOverlay(**defaults)


# ---------------------------------------------------------------------------
# TC-DOM-003 — round-trip serialization
# ---------------------------------------------------------------------------


class TestEditDecisionRoundTrip:
    def test_round_trip_full_object(self, sample_edit_decision: EditDecision) -> None:
        """TC-DOM-003: EditDecision must round-trip via JSON without data loss."""
        serialized = sample_edit_decision.model_dump_json()
        restored = EditDecision.model_validate_json(serialized)

        assert restored.highlight_id == sample_edit_decision.highlight_id
        assert restored.title == sample_edit_decision.title
        assert restored.trim.start_sec == sample_edit_decision.trim.start_sec
        assert restored.trim.end_sec == sample_edit_decision.trim.end_sec
        assert len(restored.zoom_events) == len(sample_edit_decision.zoom_events)
        assert len(restored.meme_overlays) == len(sample_edit_decision.meme_overlays)
        assert len(restored.sfx_cues) == len(sample_edit_decision.sfx_cues)
        assert len(restored.narration_cues) == len(sample_edit_decision.narration_cues)

    def test_round_trip_preserves_float_precision(self) -> None:
        """Numeric fields must not lose precision after JSON round-trip."""
        ed = _make_minimal_edit_decision()
        ed2 = EditDecision.model_validate_json(ed.model_dump_json())
        assert ed2.trim.start_sec == ed.trim.start_sec
        assert ed2.trim.end_sec == ed.trim.end_sec

    def test_model_dump_json_is_valid_json(self, sample_edit_decision: EditDecision) -> None:
        import json

        raw = sample_edit_decision.model_dump_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
        assert "highlight_id" in parsed
        assert "zoom_events" in parsed


# ---------------------------------------------------------------------------
# TC-DOM-004 — ZoomEvent.intensity validation
# ---------------------------------------------------------------------------


class TestZoomEventValidation:
    def test_intensity_at_lower_bound(self) -> None:
        """intensity=1.0 is valid (no zoom)."""
        z = _make_zoom_event(intensity=1.0)
        assert z.intensity == 1.0

    def test_intensity_at_upper_bound(self) -> None:
        """intensity=2.5 is the max allowed punch."""
        z = _make_zoom_event(intensity=2.5)
        assert z.intensity == 2.5

    def test_intensity_below_lower_bound_raises(self) -> None:
        """TC-DOM-004: intensity < 1.0 must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            _make_zoom_event(intensity=0.9)
        assert "intensity" in str(exc_info.value).lower()

    def test_intensity_above_upper_bound_raises(self) -> None:
        """TC-DOM-004: intensity > 2.5 must raise ValidationError."""
        with pytest.raises(ValidationError):
            _make_zoom_event(intensity=2.6)

    def test_duration_lower_bound(self) -> None:
        z = _make_zoom_event(duration_sec=0.1)
        assert z.duration_sec == 0.1

    def test_duration_above_upper_bound_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_zoom_event(duration_sec=5.1)

    def test_zoom_kind_enum_values(self) -> None:
        for kind in ZoomKind:
            z = _make_zoom_event(kind=kind)
            assert z.kind == kind

    def test_region_zoom_requires_region_field_optional(self) -> None:
        """For REGION zoom kind, region is optional but can be set."""
        z = ZoomEvent(
            at_sec=3.0,
            duration_sec=1.0,
            kind=ZoomKind.REGION,
            intensity=1.5,
            region=(0.2, 0.1, 0.4, 0.6),
        )
        assert z.region == (0.2, 0.1, 0.4, 0.6)


# ---------------------------------------------------------------------------
# TC-DOM-005 — meme_overlays max_length
# ---------------------------------------------------------------------------


class TestMemeOverlaysMaxLength:
    def test_max_8_overlays_accepted(self) -> None:
        """TC-DOM-005: exactly 8 overlays is the boundary — must be accepted."""
        overlays = [_make_meme_overlay(at_sec=float(i)) for i in range(8)]
        ed = _make_minimal_edit_decision()
        ed2 = ed.model_copy(update={"meme_overlays": overlays})
        assert len(ed2.meme_overlays) == 8

    def test_9_overlays_raises_validation_error(self) -> None:
        """TC-DOM-005: 9 overlays must raise ValidationError."""
        overlays = [_make_meme_overlay(at_sec=float(i)) for i in range(9)]
        with pytest.raises(ValidationError) as exc_info:
            EditDecision(
                highlight_id=HighlightId(new_id()),
                title="Too many memes",
                trim=Trim(start_sec=0.0, end_sec=30.0, reason="test"),
                meme_overlays=overlays,
                rationale="x",
            )
        assert "meme_overlays" in str(exc_info.value)

    def test_empty_overlays_accepted(self) -> None:
        ed = _make_minimal_edit_decision()
        assert ed.meme_overlays == []


# ---------------------------------------------------------------------------
# TC-DOM-006 — NarrationCue text length
# ---------------------------------------------------------------------------


class TestNarrationCueTextLength:
    def test_300_chars_accepted(self) -> None:
        """TC-DOM-006: 300 characters is the boundary — must be accepted."""
        cue = NarrationCue(text="A" * 300, at_sec=5.0, voice_id="me_v1")
        assert len(cue.text) == 300

    def test_301_chars_raises(self) -> None:
        """TC-DOM-006: 301 characters must raise ValidationError."""
        with pytest.raises(ValidationError):
            NarrationCue(text="A" * 301, at_sec=5.0, voice_id="me_v1")

    def test_empty_text_raises(self) -> None:
        """Empty narration text is not meaningful."""
        with pytest.raises(ValidationError):
            NarrationCue(text="", at_sec=5.0, voice_id="me_v1")

    def test_duck_db_default(self) -> None:
        cue = NarrationCue(text="Hola", at_sec=1.0, voice_id="me_v1")
        assert cue.duck_main_audio_db == -10.0


# ---------------------------------------------------------------------------
# TC-DOM-007 — WindowCandidate score normalization
# ---------------------------------------------------------------------------


class TestWindowCandidateScore:
    def test_score_at_zero_accepted(self) -> None:
        from autoedit.domain.signals import WindowCandidate

        w = WindowCandidate(
            id=WindowId(new_id()), vod_id=VodId("v1"), start_sec=0.0, end_sec=30.0,
            score=0.0, score_breakdown={}, rank=1, transcript_excerpt="",
        )
        assert w.score == 0.0

    def test_score_at_one_accepted(self) -> None:
        from autoedit.domain.signals import WindowCandidate

        w = WindowCandidate(
            id=WindowId(new_id()), vod_id=VodId("v1"), start_sec=0.0, end_sec=30.0,
            score=1.0, score_breakdown={}, rank=1, transcript_excerpt="",
        )
        assert w.score == 1.0

    def test_score_above_one_raises(self) -> None:
        from autoedit.domain.signals import WindowCandidate

        with pytest.raises(ValidationError):
            WindowCandidate(
                id=WindowId(new_id()), vod_id=VodId("v1"), start_sec=0.0, end_sec=30.0,
                score=1.01, score_breakdown={}, rank=1, transcript_excerpt="",
            )

    def test_score_negative_raises(self) -> None:
        from autoedit.domain.signals import WindowCandidate

        with pytest.raises(ValidationError):
            WindowCandidate(
                id=WindowId(new_id()), vod_id=VodId("v1"), start_sec=0.0, end_sec=30.0,
                score=-0.01, score_breakdown={}, rank=1, transcript_excerpt="",
            )


# ---------------------------------------------------------------------------
# TC-DOM-008 — SubtitleStyle defaults
# ---------------------------------------------------------------------------


class TestSubtitleStyleDefaults:
    def test_default_font_family(self) -> None:
        """TC-DOM-008: default font must be Arial Black."""
        s = SubtitleStyle()
        assert s.font_family == "Arial Black"

    def test_default_primary_color(self) -> None:
        s = SubtitleStyle()
        assert s.primary_color == "#FFFFFF"

    def test_default_karaoke_highlight_color(self) -> None:
        s = SubtitleStyle()
        assert s.karaoke_highlight_color == "#FFD700"

    def test_default_outline_color(self) -> None:
        s = SubtitleStyle()
        assert s.outline_color == "#000000"

    def test_default_position(self) -> None:
        s = SubtitleStyle()
        assert s.position == "lower_third"

    def test_custom_values_override_defaults(self) -> None:
        s = SubtitleStyle(font_family="Impact", primary_color="#FF0000")
        assert s.font_family == "Impact"
        assert s.primary_color == "#FF0000"
        assert s.karaoke_highlight_color == "#FFD700"  # still default
