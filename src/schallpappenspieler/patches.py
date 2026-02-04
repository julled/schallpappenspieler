import argparse
import io
from pathlib import Path
from typing import List, Optional, Tuple

import qrcode
import requests
from PIL import Image
from tqdm import tqdm

from schallpappenspieler.config import load_config, load_env
from schallpappenspieler.discogs import DiscogsClient
from schallpappenspieler.pdf_layout import PatchAssets, render_patches_to_pdf


def _parse_m3u(path: str) -> List[str]:
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
    return lines


def _make_qr_image(text: str) -> Image.Image:
    qr = qrcode.QRCode(border=1, box_size=10)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img.convert("RGB")


def _image_from_bytes(data: bytes) -> Image.Image | None:
    if not data:
        return None
    return Image.open(io.BytesIO(data)).convert("RGB")


def _load_image_from_url(url: str) -> Image.Image | None:
    if not url:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; schallpappenspieler/0.1)",
        "Accept": "image/*,*/*;q=0.8",
    }
    if "discogs.com" in url:
        headers["Referer"] = "https://www.discogs.com/"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def _split_artist_title(name: str) -> Tuple[Optional[str], str]:
    if " - " in name:
        artist, title = name.split(" - ", 1)
        return artist.strip() or None, title.strip()
    return None, name.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate song patch PDFs from M3U")
    parser.add_argument("--config", default="config.toml", help="Path to config TOML")
    parser.add_argument("--m3u", default="test.m3u", help="Path to M3U playlist")
    parser.add_argument("--output", help="Output PDF path (overrides config)")
    parser.add_argument(
        "--cover-source",
        choices=["discogs", "none"],
        help="Cover image source (default: config patches.cover_source)",
    )
    parser.add_argument(
        "--layout",
        choices=["halfsize_cover", "fullsize_cover"],
        help="Patch layout mode (default: config patches.layout_mode)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    discogs_cfg = config.get("discogs", {})
    patches_cfg = config.get("patches", {})

    cover_source = args.cover_source or patches_cfg.get("cover_source", "discogs")
    layout_mode = args.layout or patches_cfg.get("layout_mode", "halfsize_cover")

    env = load_env(Path(args.config).resolve().parent / ".env")

    discogs_client = None
    if cover_source == "discogs":
        discogs_token = env.get("DISCOGS_TOKEN") or discogs_cfg.get("token")
        user_agent = env.get("DISCOGS_USER_AGENT") or discogs_cfg.get(
            "user_agent", "schallpappenspieler/0.1"
        )
        if not discogs_token:
            print("Discogs token missing; continuing without Discogs covers.")
        else:
            discogs_client = DiscogsClient(discogs_token, user_agent)

    output_pdf = args.output or patches_cfg.get("output_pdf", "songpatches.pdf")

    entries = _parse_m3u(args.m3u)[0:8]
    assets: List[PatchAssets] = []

    progress = tqdm(entries, desc="Building patches")
    for entry in progress:
        filename = Path(entry).name
        display_name = Path(entry).stem
        print(f"Processing: {display_name}")

        artist, title = _split_artist_title(display_name)

        album_img = None

        if cover_source == "discogs" and discogs_client:
            artist, title = _split_artist_title(display_name)
            cover_url = discogs_client.search_cover(title, artist)
            if cover_url:
                album_img = _load_image_from_url(cover_url)
            rate = discogs_client.last_rate
            if rate and rate.remaining is not None:
                progress.set_postfix_str(f"discogs_remaining={rate.remaining}")
            waited = discogs_client.wait_if_limited()
            if waited > 0:
                progress.set_postfix_str(f"discogs_wait={waited}s")

        if cover_source == "none":
            album_img = None

        qr_img = _make_qr_image(filename)

        assets.append(
            PatchAssets(
                display_name=display_name,
                filename=filename,
                qr_image=qr_img,
                album_image=album_img,
                artist=artist,
                title=title,
            )
        )

    render_patches_to_pdf(
        assets,
        output_pdf,
        patches_cfg.get("patch_size_cm", 5.0),
        patches_cfg.get("qr_size_cm", 3.0),
        patches_cfg.get("page_width_mm", 210),
        patches_cfg.get("page_height_mm", 297),
        layout_mode,
    )
    print(f"Wrote {output_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
