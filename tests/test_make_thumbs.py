import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import make_thumbs as mt  # noqa: E402


def test_main_photo_id_prefers_main():
    alert = {"photos": [{"photo_id": 1, "main": False}, {"photo_id": 2, "main": True}]}
    assert mt.main_photo_id(alert) == 2


def test_main_photo_id_falls_back_to_first():
    alert = {"photos": [{"photo_id": 7, "main": False}, {"photo_id": 8, "main": False}]}
    assert mt.main_photo_id(alert) == 7


def test_main_photo_id_none_when_no_photos():
    assert mt.main_photo_id({"photos": []}) is None
    assert mt.main_photo_id({}) is None


def _write_alert(src: Path, alert_id: int, photos: list[dict]) -> None:
    (src / f"{alert_id}.json").write_text(json.dumps({"id": alert_id, "photos": photos}))


def test_needed_photo_ids_skips_existing_and_empty(tmp_path):
    src = tmp_path / "alerts"
    out = tmp_path / "thumbs"
    src.mkdir()
    out.mkdir()
    _write_alert(src, 100, [{"photo_id": 11, "main": True}])
    _write_alert(src, 200, [{"photo_id": 22, "main": True}])
    _write_alert(src, 300, [])  # no photo → nothing needed
    (out / "22.webp").write_bytes(b"existing")  # already thumbnailed → skip

    assert mt.needed_photo_ids(src, out) == [11]


def test_needed_photo_ids_dedupes_shared_photo(tmp_path):
    src = tmp_path / "alerts"
    out = tmp_path / "thumbs"
    src.mkdir()
    out.mkdir()
    _write_alert(src, 1, [{"photo_id": 5, "main": True}])
    _write_alert(src, 2, [{"photo_id": 5, "main": True}])  # same photo, once only

    assert mt.needed_photo_ids(src, out) == [5]


def test_to_thumb_fits_box_and_is_webp():
    src = Image.new("RGB", (650, 500), (10, 20, 30))
    buf = io.BytesIO()
    src.save(buf, "JPEG")
    out = mt.to_thumb(buf.getvalue(), size=240, quality=72)

    result = Image.open(io.BytesIO(out))
    assert result.format == "WEBP"
    assert max(result.size) <= 240
    assert len(out) < len(buf.getvalue())  # smaller than the source
