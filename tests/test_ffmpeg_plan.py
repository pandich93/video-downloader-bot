"""План обработки и команда FFmpeg — без запуска самого FFmpeg."""
from pathlib import Path

import pytest

from bot.editor.ffmpeg import EditFailed, Probe, build_command, build_filter, make_plan
from bot.editor.options import EditOptions

MB = 1024 * 1024
HORIZONTAL = Probe(width=1920, height=1080, duration=60, fps=30, has_audio=True)
VERTICAL = Probe(width=1080, height=1920, duration=30, fps=30, has_audio=True)


def test_horizontal_goes_to_blurred_9x16():
    plan = make_plan(HORIZONTAL, EditOptions(), 50 * MB)
    assert plan.frame == "blur"
    assert (plan.out_w, plan.out_h) == (1080, 1920)
    assert plan.duration == 60
    assert 400 <= plan.video_kbps <= 8000


def test_vertical_is_cropped():
    plan = make_plan(VERTICAL, EditOptions(), 50 * MB)
    assert plan.frame == "crop"
    assert (plan.out_w, plan.out_h) == (1080, 1920)


def test_low_resolution_source_stays_720p():
    small = Probe(width=640, height=360, duration=30, fps=30, has_audio=True)
    plan = make_plan(small, EditOptions(), 50 * MB)
    assert (plan.out_w, plan.out_h) == (720, 1280)


def test_bitrate_fits_size_limit():
    plan = make_plan(HORIZONTAL, EditOptions(), 50 * MB)
    total_kbps = plan.video_kbps + (128 if plan.audio else 0)
    assert total_kbps * 1000 / 8 * plan.duration <= 50 * MB


def test_cut_to_platform_limit():
    long = Probe(width=1080, height=1920, duration=900, fps=30, has_audio=True)
    tiktok = make_plan(long, EditOptions(platform="tiktok"), 50 * MB)
    assert tiktok.duration == 600 and tiktok.cut_to_limit
    reels = make_plan(long, EditOptions(platform="reels"), 50 * MB)
    assert reels.duration == 180 and reels.cut_to_limit


def test_fragment_and_speed():
    plan = make_plan(HORIZONTAL, EditOptions(start=10, end=32, speed=1.1), 50 * MB)
    assert plan.start == 10
    assert plan.duration == pytest.approx(20)


def test_mute_and_no_audio():
    assert make_plan(HORIZONTAL, EditOptions(audio="mute"), 50 * MB).audio is False
    silent = Probe(width=1920, height=1080, duration=60, fps=30, has_audio=False)
    assert make_plan(silent, EditOptions(), 50 * MB).audio is False


@pytest.mark.parametrize("opts, max_bytes", [
    (EditOptions(start=59.8), 50 * MB),                     # начало за концом видео
    (EditOptions(start=10, end=10.6), 50 * MB),             # фрагмент короче секунды
    (EditOptions(), 1 * MB),                                # в 1 МБ минута не влезает
])
def test_impossible_plans_fail_with_user_message(opts, max_bytes):
    with pytest.raises(EditFailed):
        make_plan(HORIZONTAL, opts, max_bytes)


@pytest.mark.parametrize("opts", [
    EditOptions(),
    EditOptions(frame="crop", style="warm", fade_in=True, speed=1.05),
    EditOptions(frame="original", style="contrast", progress=True, audio="orig"),
])
def test_filter_has_no_spaces(opts):
    """Граф фильтров без пробелов — так его безопасно передавать в командной строке Windows."""
    plan = make_plan(HORIZONTAL, opts, 50 * MB)
    graph = build_filter(HORIZONTAL, opts, plan, None, brand_color="FF4D00")
    assert " " not in graph
    assert graph.endswith("[a]") == plan.audio


def test_command_strips_metadata():
    opts = EditOptions(start=5)
    plan = make_plan(HORIZONTAL, opts, 50 * MB)
    cmd = build_command(Path("in.mp4"), Path("out.mp4"), HORIZONTAL, opts, plan, None)
    assert cmd[0] == "ffmpeg" and cmd[-1] == "out.mp4"
    assert cmd[cmd.index("-map_metadata") + 1] == "-1"
    assert cmd[cmd.index("-ss") + 1] == "5.000"
    assert "+faststart" in cmd
