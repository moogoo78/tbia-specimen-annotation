"""Image size variants — the rule table, and what the pipeline sends.

TBIA's export ships one URL per image, and for HAST it is a 1024px derivative:
enough to see a herbarium sheet, not enough to read its label. The larger
renditions exist on the same bucket under a different suffix, which is knowledge
that lives in `data/media_variants.json` and nowhere else.

The invariant these tests defend is that **a size is a request, never a
promise**: everything that cannot be rewritten comes back as the URL the export
shipped, so a record from an unruled source behaves exactly as it did before any
of this existed.
"""

import json

import pytest

from app import media, pipeline

HAST = "https://brmas-media.s3-ap-northeast-1.amazonaws.com/hast/specimen/S_138530-l.jpg"
OTHER = "https://www.npgrc.tari.gov.tw/pic/12A00001-1.jpg"


def test_the_shipped_rule_finds_hasts_bigger_renditions():
    """Against the real data/media_variants.json — a typo there is a silently
    unchanged URL, which is exactly the failure this catches."""
    assert media.at_size(HAST, "x").endswith("/S_138530-x.jpg")
    assert media.at_size(HAST, "o").endswith("/S_138530-o.jpg")
    # Only the suffix moves; bucket, path and stem are untouched.
    assert media.at_size(HAST, "x").rsplit("-", 1)[0] == HAST.rsplit("-", 1)[0]


@pytest.mark.parametrize("url,size", [
    (OTHER, "x"),        # no rule for this source at all
    (HAST, "huge"),      # a size the rule does not list
    (HAST, ""),          # nothing asked for
    ("https://brmas-media.s3-ap-northeast-1.amazonaws.com/hast/odd/name.png", "x"),
])
def test_anything_it_cannot_rewrite_comes_back_unchanged(url, size):
    """The whole point: callers ask for a bigger image unconditionally instead of
    branching per source, which is only safe because the miss is a no-op rather
    than a 404."""
    assert media.at_size(url, size) == url


def test_the_ladder_is_offered_per_gallery_and_ordered_by_size():
    """The shipped ladder starts at what the export ships and only goes up: the
    picker exists so a label can be read, and the smaller renditions the bucket
    also carries (`-s`, `-m`) answer no question anyone has on this page."""
    sizes = media.sizes_for([HAST, HAST.replace("S_138530", "S_138531")])
    assert [s["size"] for s in sizes] == ["l", "x", "o"]
    assert [s["long_edge"] for s in sizes] == [1024, 2048, 4096]
    # Exactly one rung is what the export itself ships — the UI's default.
    assert [s["canonical"] for s in sizes] == [True, False, False]
    # URLs arrive rewritten and parallel to the input, so the browser builds none.
    assert sizes[1]["urls"] == [
        HAST.replace("-l.jpg", "-x.jpg"),
        HAST.replace("S_138530", "S_138531").replace("-l.jpg", "-x.jpg"),
    ]


def test_a_mixed_gallery_offers_nothing():
    """One picker sets the size for the whole gallery, so a record whose images
    don't all resolve under one rule has no coherent ladder to offer — better a
    missing control than one that silently moves only half the images."""
    assert media.sizes_for([HAST, OTHER]) == []
    assert media.sizes_for([]) == []


def test_an_unreadable_config_means_no_variants_not_a_500(tmp_path, monkeypatch):
    """A record page must not depend on this file parsing: without it, every URL
    is simply the one the export shipped."""
    broken = tmp_path / "media_variants.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(media, "CONFIG_PATH", str(broken))
    monkeypatch.setattr(media, "_cache", None)

    assert media.at_size(HAST, "x") == HAST
    assert media.sizes_for([HAST]) == []


def test_a_new_source_is_a_config_edit_and_nothing_else(tmp_path, monkeypatch):
    cfg = tmp_path / "media_variants.json"
    cfg.write_text(json.dumps({"rules": [{
        "url_prefix": "https://img.example.org/",
        "pattern": "_{suffix}.png",
        "canonical": "small",
        "sizes": [{"suffix": "small", "long_edge": 800},
                  {"suffix": "big", "long_edge": 3000}],
    }]}), encoding="utf-8")
    monkeypatch.setattr(media, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(media, "_cache", None)

    assert media.at_size("https://img.example.org/a_small.png", "big") \
        == "https://img.example.org/a_big.png"
    assert media.at_size(HAST, "x") == HAST      # the shipped rule is gone with it


def test_the_pipeline_reads_the_size_the_deployment_asked_for(monkeypatch):
    """`_image_urls` is the single definition of *which images at what size*, so
    the request blocks and the stored `image_urls` cannot disagree about what was
    read. Default is "x": 2048px is the largest rendition the vision API does not
    downscale, so "o" would be bandwidth paid for pixels the model never sees."""
    record = {"id": "r4", "media": [HAST]}

    assert pipeline._image_urls(record) == [HAST.replace("-l.jpg", "-x.jpg")]

    monkeypatch.setattr(pipeline.settings, "ocr_image_size", "o")
    assert pipeline._image_urls(record) == [HAST.replace("-l.jpg", "-o.jpg")]

    # An unset size, or a source with no rule, leaves the export's URL alone.
    monkeypatch.setattr(pipeline.settings, "ocr_image_size", "")
    assert pipeline._image_urls(record) == [HAST]


def test_a_record_with_no_image_still_fails_loudly(monkeypatch):
    with pytest.raises(ValueError):
        pipeline._image_urls({"id": "r9", "media": []})
