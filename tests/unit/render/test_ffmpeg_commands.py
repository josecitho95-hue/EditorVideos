from __future__ import annotations

"""
TC-REN-001 to TC-REN-009
Tests for FFmpeg command building, crop computation, and ASS subtitle generation.
"""


from autoedit.domain.edit_decision import (
    MemeOverlay,
    NarrationCue,
    SfxCue,
    ZoomEvent,
    ZoomKind,
)
from autoedit.domain.ids import AssetId
from autoedit.render.compositor import (
    build_audio_filter,
    build_filter_complex,
    build_render_command,
)
from autoedit.render.reframe import CropParams, compute_center_crop
from autoedit.render.subtitles import Word, build_ass_subtitles

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cmd(
    source: str = "input.mp4",
    output: str = "output.mp4",
    start: float = 0.0,
    end: float = 60.0,
    output_codec: str = "h264_nvenc",
    nvenc_preset: str = "p4",
    crop: CropParams | None = None,
    meme_overlays: list[MemeOverlay] | None = None,
    sfx_cues: list[SfxCue] | None = None,
    narration_cues: list[NarrationCue] | None = None,
    zoom_events: list[ZoomEvent] | None = None,
    subtitle_path: str | None = None,
) -> list[str]:
    return build_render_command(
        source=source,
        output=output,
        start=start,
        end=end,
        output_codec=output_codec,
        nvenc_preset=nvenc_preset,
        crop=crop,
        meme_overlays=meme_overlays or [],
        sfx_cues=sfx_cues or [],
        narration_cues=narration_cues or [],
        zoom_events=zoom_events or [],
        subtitle_path=subtitle_path,
    )


# ---------------------------------------------------------------------------
# TC-REN-001 — trim arguments
# ---------------------------------------------------------------------------

class TestTrimArgs:
    def test_uses_ss_and_to(self) -> None:
        cmd = _make_cmd(start=100.0, end=140.0)
        assert "-ss" in cmd
        assert "100.0" in cmd
        assert "-to" in cmd
        assert "140.0" in cmd

    def test_output_path_in_cmd(self) -> None:
        output = "my_output.mp4"
        cmd = _make_cmd(output=output)
        assert output in cmd


# ---------------------------------------------------------------------------
# TC-REN-002 — filter_complex contents
# ---------------------------------------------------------------------------

class TestFilterComplex:
    def test_meme_overlay_has_between_filter(self) -> None:
        overlay = MemeOverlay(asset_id=AssetId("meme.png"), at_sec=5.0, duration_sec=2.0)
        fc = build_filter_complex(
            meme_overlays=[overlay],
            sfx_cues=[],
            zoom_events=[],
            subtitle_path=None,
        )
        assert "between(t,5.0,7.0)" in fc, (
            f"Expected 'between(t,5.0,7.0)' in filter_complex, got:\n{fc}"
        )

    def test_sfx_adelay_ms(self) -> None:
        # SFX mixing requires separate file inputs — test via build_filter_complex
        # with sfx_available=1 (telling it one SFX file input is present at index 1).
        sfx = SfxCue(asset_id=AssetId("boom.wav"), at_sec=3.0)
        fc = build_filter_complex(
            meme_overlays=[],
            sfx_cues=[sfx],
            narration_cues=[],
            sfx_available=1,
        )
        assert "adelay=3000|3000" in fc, (
            f"Expected 'adelay=3000|3000' in filter_complex, got:\n{fc}"
        )

    def test_zoom_punch_generates_zoompan(self) -> None:
        zoom = ZoomEvent(kind=ZoomKind.PUNCH_IN, at_sec=2.0, duration_sec=1.0)
        fc = build_filter_complex(
            meme_overlays=[],
            sfx_cues=[],
            zoom_events=[zoom],
            subtitle_path=None,
        )
        assert "zoompan" in fc, (
            f"Expected 'zoompan' in filter_complex for PUNCH_IN zoom, got:\n{fc}"
        )

    def test_subtitles_filter_present(self) -> None:
        fc = build_filter_complex(
            meme_overlays=[],
            sfx_cues=[],
            zoom_events=[],
            subtitle_path="subs.ass",
        )
        assert "subtitles=" in fc, (
            f"Expected 'subtitles=' in filter_complex when subtitle_path given, got:\n{fc}"
        )


# ---------------------------------------------------------------------------
# TC-REN-003 — crop computation
# ---------------------------------------------------------------------------

class TestCropComputation:
    def test_9_16_crop_width(self) -> None:
        # compute_center_crop uses floor-to-even: int(1080*1080/1920)=607 → 606
        crop = compute_center_crop(input_w=1920, input_h=1080)
        assert crop.w == 606, f"Expected crop.w=606 for 1920x1080, got {crop.w}"
        # Sanity: crop must stay within source bounds
        assert crop.x + crop.w <= 1920

    def test_9_16_crop_height(self) -> None:
        crop = compute_center_crop(input_w=1920, input_h=1080)
        assert crop.h == 1080

    def test_crop_x_centers(self) -> None:
        crop = compute_center_crop(input_w=1920, input_h=1080)
        assert crop.x == (1920 - 606) // 2, (
            f"Expected crop.x={(1920-606)//2}, got {crop.x}"
        )

    def test_4k_input(self) -> None:
        # floor-to-even: int(2160*1080/1920)=1215 → 1214
        crop = compute_center_crop(input_w=3840, input_h=2160)
        assert crop.w == 1214, f"Expected crop.w=1214 for 3840x2160, got {crop.w}"
        assert crop.x + crop.w <= 3840


# ---------------------------------------------------------------------------
# TC-REN-004 — NVENC preset / codec flags
# ---------------------------------------------------------------------------

class TestNvencPreset:
    def test_codec_in_cmd(self) -> None:
        cmd = _make_cmd(output_codec="h264_nvenc")
        assert "-c:v" in cmd
        assert "h264_nvenc" in cmd

    def test_preset_in_cmd(self) -> None:
        cmd = _make_cmd(nvenc_preset="p4")
        assert "-preset" in cmd
        assert "p4" in cmd

    def test_faststart_always_present(self) -> None:
        cmd = _make_cmd()
        joined = " ".join(cmd)
        assert "-movflags" in joined
        assert "+faststart" in joined


# ---------------------------------------------------------------------------
# TC-REN-005 — audio ducking / narration
# ---------------------------------------------------------------------------

class TestAudioDucking:
    def test_volume_factor_for_minus10db(self) -> None:
        cue = NarrationCue(
            text="test narration",
            at_sec=0.0,
            voice_id="me_v1",
            duck_main_audio_db=-10.0,
        )
        af = build_audio_filter(sfx_cues=[], narration_cues=[cue])
        # 10^(-10/20) ≈ 0.31623; must appear rounded to 3 decimal places
        assert "0.316" in af, (
            f"Expected volume factor '0.316' (≈10^(-10/20)) in audio filter, got:\n{af}"
        )

    def test_narration_at_sec_appears_in_volume_filter(self) -> None:
        # build_audio_filter emits a volume/ducking filter that uses seconds (not ms).
        # The at_sec=5.0 must appear as the window start in the between() expression.
        cue = NarrationCue(
            text="test narration",
            at_sec=5.0,
            voice_id="me_v1",
            duck_main_audio_db=-10.0,
        )
        af = build_audio_filter(sfx_cues=[], narration_cues=[cue])
        assert "between(t,5.0," in af, (
            f"Expected 'between(t,5.0,...' in audio filter for at_sec=5.0, got:\n{af}"
        )


# ---------------------------------------------------------------------------
# TC-REN-006 — ASS subtitle generation
# ---------------------------------------------------------------------------

class TestAssSubtitles:
    def _three_words(self) -> list[Word]:
        return [
            Word(text="Hola", start_sec=0.0, end_sec=0.4),
            Word(text="qué", start_sec=0.4, end_sec=0.7),
            Word(text="tal", start_sec=0.7, end_sec=1.0),
        ]

    def test_karaoke_markers_count(self) -> None:
        ass = build_ass_subtitles(words=self._three_words())
        # Each word gets a \k marker
        count = ass.count("\\k")
        assert count == 3, f"Expected 3 \\k karaoke markers, got {count}"

    def test_style_header_present(self) -> None:
        ass = build_ass_subtitles(words=self._three_words())
        assert "[V4+ Styles]" in ass, "Missing [V4+ Styles] section in ASS output"

    def test_events_header_present(self) -> None:
        ass = build_ass_subtitles(words=self._three_words())
        assert "[Events]" in ass, "Missing [Events] section in ASS output"
