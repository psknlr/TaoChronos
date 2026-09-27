"""版面理解与 OCR (T1–T2): reading order from boxes, OCR formats, a vision model's reading, IIIF pages, OCR vs the store."""

from __future__ import annotations

import json

import pytest

from taochronos.capabilities.judge import Judge
from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics.vision import Token, analyse
from taochronos.plugins.classics.vision.formats import read_alto, read_file, read_hocr, read_page, read_paddle
from taochronos.plugins.classics.vision.iiif import canvases, image_url
from taochronos.plugins.classics.vision.ocr import compare, read_image
from taochronos.plugins.classics.vision.synth import layout_text, tokens
from taochronos.plugins.models.scripted import ScriptedProvider

TEXT = "太阳病头痛发热汗出恶风者（此太阳中风之证风伤卫也）桂枝汤主之桂枝三两（去皮）芍药三两甘草二两（炙）生姜三两（切）大枣十二枚（擘）"


def test_a_page_is_read_in_its_own_order_with_notes_and_apparatus_apart():
    segs, truth = layout_text(TEXT, rows=12, max_cols=8, title="伤寒论卷一", leaf="五", head_note="此条要")
    toks, kinds = tokens(segs, seed=3)
    g = analyse(toks)
    assert g.orientation == "vertical-rtl" and g.text == truth
    assert {(a["kind"], a["text"]) for a in g.apparatus} == {("header", "伤寒论卷一"), ("page_number", "五"), ("margin", "此条要")}
    note = next(b for b in g.blocks if b.kind == "commentary" and "风伤卫" in b.text)
    assert note.rule.startswith("双行小注") and len(note.parts) == 2  # the right half, then the left
    assert g.to_dict()["reading_order"][0] == next(b.id for b in g.blocks if b.order == 0)


def test_characters_reported_one_by_one_are_joined_into_columns():
    segs, truth = layout_text(TEXT, rows=10, max_cols=9)
    split = []
    for s in segs:
        h = s.h / len(s.text)
        split += [Token(c, s.x, s.y + j * h, s.w, h) for j, c in enumerate(s.text)]
    assert analyse(split).text == truth


def test_the_readers_of_ocr_formats_give_the_same_page(tmp_path):
    segs, truth = layout_text(TEXT, rows=12, max_cols=8)
    toks, _ = tokens(segs, seed=1, jitter=0.02)
    alto = "<alto><Layout><Page>" + "".join(
        f'<TextLine ID="{t.id}" HPOS="{t.x}" VPOS="{t.y}" WIDTH="{t.w}" HEIGHT="{t.h}"><String CONTENT="{t.text}" WC="0.9"/></TextLine>'
        for t in toks) + "</Page></Layout></alto>"
    hocr = "<div class='ocr_page'>" + "".join(
        f"<span class='ocr_line' title='bbox {int(t.x)} {int(t.y)} {int(t.x + t.w)} {int(t.y + t.h)}'>{t.text}</span>" for t in toks) + "</div>"
    page = "<PcGts><Page>" + "".join(
        f'<TextLine id="{t.id}"><Coords points="{t.x},{t.y} {t.x + t.w},{t.y + t.h}"/><TextEquiv><Unicode>{t.text}</Unicode></TextEquiv></TextLine>'
        for t in toks) + "</Page></PcGts>"
    paddle = [[[[t.x, t.y], [t.x + t.w, t.y + t.h]], [t.text, 0.95]] for t in toks]
    for reader, data in ((read_alto, alto), (read_hocr, hocr), (read_page, page), (read_paddle, paddle)):
        assert analyse(reader(data)).text == truth, reader.__name__
    f = tmp_path / "page.xml"
    f.write_text(alto, encoding="utf-8")
    assert analyse(read_file(f)).text == truth  # the format is guessed from the file


def test_compare_counts_ocr_errors_and_keeps_variant_forms_apart(harness):
    normalize = harness.pack.variants.normalize_text
    r = compare("太陽病發熱汗出惡風桂枝湯主之", "太阳病，发热汗出恶风，桂枝汤主之。", normalize)
    assert r["cer_normalized"] == 0.0 and r["variant_only"] == r["substitutions"] > 0
    typo = compare("太阳病发热汗出恶风桂枝场主之", "太阳病，发热汗出恶风，桂枝汤主之。", normalize)
    assert typo["substitutions"] == 1 and typo["confusions"][0]["pair"] == "场→汤"
    passage = max(harness.corpus.passages(), key=lambda p: len(p.text))
    han = "".join(ch for ch in passage.text if "一" <= ch <= "鿿")[10:70]
    found = harness.capabilities.get("vision").compare(han[:20] + "目" + han[21:])
    assert found["located"][0] == passage.id and found["substitutions"] + found["insertions"] + found["deletions"] >= 1


def test_a_vision_model_reads_an_image_without_adding_marks():
    blocks = {"blocks": [{"kind": "header", "text": "伤寒论卷一"}, {"kind": "main", "text": "太阳病发热汗出"},
                         {"kind": "commentary", "text": "此太阳中风"}, {"kind": "main", "text": "桂枝汤主之"}]}
    punctuated = {"blocks": [{"kind": "main", "text": "太阳病，发热。"}]}
    judge = Judge(ScriptedProvider([{"text": json.dumps(punctuated, ensure_ascii=False)}, {"text": json.dumps(blocks, ensure_ascii=False)}]), "m")
    r = read_image(judge, b"\x89PNG fake", "image/png")
    assert r["ok"] and r["text"] == "太阳病发热汗出（此太阳中风）桂枝汤主之" and r["apparatus"][0]["kind"] == "header"
    request = judge.provider.requests[0]
    assert request.messages[0].images and request.messages[0].images[0].media_type == "image/png"
    assert "punctuation was added" in judge.provider.requests[1].messages[-1].text  # the repair turn


def test_iiif_manifests_of_both_versions_give_page_images():
    v2 = {"sequences": [{"canvases": [{"label": "1", "width": 2000, "height": 3000,
                                       "images": [{"resource": {"@id": "https://x/iiif/p1/full/full/0/default.jpg",
                                                                "service": {"@id": "https://x/iiif/p1"}}}]}]}]}
    v3 = {"items": [{"label": {"none": ["一"]}, "items": [{"items": [{"body": {"id": "https://y/p1.jpg",
                                                                             "service": [{"id": "https://y/iiif/p1"}]}}]}]}]}
    assert image_url(canvases(v2)[0], 1200) == "https://x/iiif/p1/full/1200,/0/default.jpg"
    c3 = canvases(v3)[0]
    assert c3["label"] == "一" and image_url(c3) == "https://y/iiif/p1/full/1600,/0/default.jpg"


def test_vision_through_the_tools_and_the_cli(harness, capsys, tmp_path):
    segs, truth = layout_text(TEXT, rows=12, max_cols=8, title="伤寒论卷一")
    toks, _ = tokens(segs, seed=2)
    rows = [{"text": t.text, "bbox": [t.x, t.y, t.w, t.h]} for t in toks]
    out = harness.scheduler.execute(ToolCall("vision.layout", {"tokens": rows}), actor=Actor.kernel())
    assert out.ok and out.result["text"] == truth
    f = tmp_path / "tokens.json"
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    assert main(["--data", str(tmp_path), "vision", "layout", str(f), "--profile", "full-discovery"]) == 0
    page = capsys.readouterr().out
    assert page.startswith("# 版面") and truth in page and "header：伤寒论卷一" in page
    with pytest.raises(ValueError, match="needs a model"):
        harness.capabilities.get("vision").read(b"x")
