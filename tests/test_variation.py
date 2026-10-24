"""Вариация: диапазоны уровней, повторяемость по seed, различие файлов пакета."""
from itertools import combinations
from pathlib import Path

import pytest

from bot.editor.ffmpeg import (BAND_PAD, VARIATION_RANGES, Probe, RenderResult, build_filter,
                               make_plan, random_variation, random_variations)
from bot.editor.keyboards import changes_summary
from bot.editor.options import EditOptions, toggle

MB = 1024 * 1024
HORIZONTAL = Probe(width=1920, height=1080, duration=60, fps=30, has_audio=True)
PARAMS = ("zoom", "x", "y", "brightness", "contrast", "saturation")


@pytest.mark.parametrize("level", list(VARIATION_RANGES))
def test_values_stay_in_range(level):
    for seed in range(300):
        for n in (1, 3):
            for var in random_variations(n, level, seed):
                assert var.level == level and var.seed == seed
                for k, (lo, hi) in VARIATION_RANGES[level].items():
                    assert lo - 1e-3 <= getattr(var, k) <= hi + 1e-3, (k, seed)


def test_light_is_softer_than_medium():
    light, medium = VARIATION_RANGES["light"], VARIATION_RANGES["medium"]
    for k in ("zoom", "brightness", "contrast", "saturation"):
        assert light[k][1] - light[k][0] < medium[k][1] - medium[k][0], k


def test_same_seed_same_variation():
    assert random_variations(3, "medium", 42) == random_variations(3, "medium", 42)
    assert random_variation("light", 7) == random_variation("light", 7)
    assert random_variation("medium", 1) != random_variation("medium", 2)


def test_random_seed_is_recorded():
    var = random_variation()
    assert var == random_variation(var.level, var.seed)


@pytest.mark.parametrize("level", list(VARIATION_RANGES))
def test_batch_files_differ_in_every_parameter(level):
    """У трёх файлов пакета каждый параметр — в своей трети диапазона, с запасом между ними."""
    n = 3
    for seed in range(300):
        batch = random_variations(n, level, seed)
        for k in PARAMS:
            lo, hi = VARIATION_RANGES[level][k]
            min_gap = (hi - lo) * 2 * BAND_PAD / n
            for a, b in combinations(batch, 2):
                # округление до 3–4 знаков съедает не больше тысячной доли
                assert abs(getattr(a, k) - getattr(b, k)) >= min_gap - 1e-3, (k, seed)


def test_unknown_level_fails():
    with pytest.raises(KeyError):
        random_variation("strong")


@pytest.mark.parametrize("opts", [
    EditOptions(),
    EditOptions(frame="crop", style="warm", fade_in=True, speed=1.05),
    EditOptions(frame="original", style="contrast", progress=True, audio="orig"),
])
def test_filter_with_variation_has_no_spaces(opts):
    plan = make_plan(HORIZONTAL, opts, 50 * MB)
    graph = build_filter(HORIZONTAL, opts, plan, random_variation(seed=1), brand_color="FF4D00")
    assert " " not in graph
    assert "eq=brightness=" in graph and graph.startswith("[0:v]crop=")


def test_original_frame_keeps_planned_size_after_zoom():
    """После зума вариации кадр масштабируется обратно к размеру плана — под него рассчитаны оверлеи."""
    opts = EditOptions(frame="original")
    plan = make_plan(HORIZONTAL, opts, 50 * MB)
    graph = build_filter(HORIZONTAL, opts, plan, random_variation(seed=1))
    assert f"scale={plan.out_w}:{plan.out_h}," in graph


def test_toggle_cycles_variation_levels():
    opts = EditOptions()
    assert opts.variation == "medium"           # по умолчанию — как раньше
    seen = [opts.variation]
    for _ in range(3):
        opts = toggle(opts, "var")
        seen.append(opts.variation)
    assert seen == ["medium", "light", "off", "medium"]


def test_summary_names_variation_level():
    var = random_variation("light", seed=3)
    r = RenderResult(Path("out.mp4"), 1080, 1920, 30, 10 * MB, variation=var)
    assert "вариация (слабая): зум +" in changes_summary(r, EditOptions(variation="light"))
    no_var = RenderResult(Path("out.mp4"), 1080, 1920, 30, 10 * MB)
    assert "вариация" not in changes_summary(no_var, EditOptions(variation="off"))
