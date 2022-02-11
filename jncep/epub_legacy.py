from collections import namedtuple
from html.parser import HTMLParser
import logging
import os
import os.path
import re
import time

from ebooklib import epub

from . import jncapi_legacy, spec
from .utils import green

logger = logging.getLogger(__package__)


EpubGenerationOptions = namedtuple(
    "EpubGenerationOptions",
    [
        "output_dirpath",
        "is_by_volume",
        "is_extract_images",
        "is_extract_content",
        "is_not_replace_chars",
    ],
)

BookDetails = namedtuple(
    "BookDetails",
    ["identifier", "title", "author", "collection", "cover_url_candidates", "toc"],
)


class CoverImageException(Exception):
    pass


def _to_pretty_part_name(series, part) -> str:
    part_str = f"Part_{part.num_in_volume}"
    title = part.volume.raw_volume.title
    return f"{_to_safe_filename(title)}_{part_str}"


def create_epub(token, series, parts, epub_generation_options):
    # here normally all parts in parameter are available
    contents, downloaded_img_urls, raw_contents = _get_book_content_and_images(
        token, series, parts, epub_generation_options.is_not_replace_chars
    )
    book_details = _get_book_details(series, parts)

    logger.info("Fetching cover image...")
    for cover_url in book_details.cover_url_candidates:
        if cover_url in downloaded_img_urls:
            # no need to redownload
            # tuple : index 0 => bytes content
            # TODO do not add same file (same content, different name) in EPUB
            cover_bytes = downloaded_img_urls[cover_url][0]
            break
        else:
            try:
                cover_bytes = jncapi_legacy.fetch_image_from_cdn(cover_url)
                break
            except Exception:
                logger.warning(
                    f"Unable to download cover image with URL: '{cover_url}'. "
                    "Trying next candidate..."
                )
                continue
    else:
        raise CoverImageException("No suitable cover could be downloaded!")

    output_filename = _to_safe_filename(book_details.title) + ".epub"
    output_filepath = os.path.join(
        epub_generation_options.output_dirpath, output_filename
    )

    if epub_generation_options.is_extract_images:
        logger.info("Extracting images...")
        current_part = None
        img_index = -1
        for img_bytes, img_filename, part in downloaded_img_urls.values():
            if part is not current_part:
                img_index = 1
                current_part = part
            else:
                img_index += 1
            # change filename to something more readable since visible to
            # user
            _, ext = os.path.splitext(img_filename)
            img_filename = (
                _to_pretty_part_name(series, part)
                # extension at the end
                + f"_Image_{img_index}{ext}"
            )
            img_filepath = os.path.join(
                epub_generation_options.output_dirpath, img_filename
            )
            with open(img_filepath, "wb") as img_f:
                img_f.write(img_bytes)

    if epub_generation_options.is_extract_content:
        logger.info("Extracting content...")
        for content, part in zip(raw_contents, parts):
            content_filename = _to_pretty_part_name(series, part) + ".html"
            content_filepath = os.path.join(
                epub_generation_options.output_dirpath, content_filename
            )
            with open(content_filepath, "w", encoding="utf-8") as content_f:
                content_f.write(content)

    _create_epub_file(
        output_filepath,
        book_details,
        cover_bytes,
        parts,
        contents,
        downloaded_img_urls,
    )
    logger.info(green(f"Success! EPUB generated in '{output_filepath}'!"))


def _get_book_content_and_images(
    token, series, parts_to_download, is_not_replace_chars
):
    downloaded_img_urls = {}
    contents = []
    raw_contents = []
    for part in parts_to_download:
        logger.info(f"Fetching part '{part.raw_part.title}'...")
        content = jncapi_legacy.fetch_content(token, part.raw_part.id)
        raw_contents.append(content)

        if not is_not_replace_chars:
            # both the chars to replace and replacement are hardcoded
            # U+2671 => East Syriac Cross (used in Her Majesty's Swarm)
            # U+25C6 => Black Diamond (used in SOAP)
            # U+1F3F6 => Black Rosette
            # U+25C7 => White Diamond
            # U+2605 => Black star
            chars_to_replace = ["\u2671", "\u25C6", "\U0001F3F6", "\u25C7", "\u2605"]
            replacement_char = "**"
            regex = "|".join(chars_to_replace)
            content_b = re.sub(regex, replacement_char, content)
            if content != content_b:
                logger.warning(
                    "Some Unicode characters unlikely to be readable with "
                    "the base fonts of an EPUB reader have been replaced "
                )
            content = content_b

        img_urls = _img_urls(content)
        if len(img_urls) > 0:
            logger.info("Fetching images found in part content...")
            for i, img_url in enumerate(img_urls):
                logger.info(f"Image {i + 1}...")
                try:
                    img_bytes = jncapi_legacy.fetch_image_from_cdn(img_url)
                except Exception:
                    logger.error(
                        f"Unable to download image with URL: '{img_url}'. "
                        "Ignoring..."
                    )
                    continue

                # the filename relative to the epub content root
                # file will be added to the Epub archive
                # ext is almost always .jpg but sometimes it is .jpeg
                # splitext  works fine with a url
                root, ext = os.path.splitext(img_url)
                new_local_filename = _to_safe_filename(root) + ext
                downloaded_img_urls[img_url] = (img_bytes, new_local_filename, part)
                content = content.replace(img_url, new_local_filename)

        contents.append(content)

    return contents, downloaded_img_urls, raw_contents


def _get_book_details(series, parts_to_download):
    # shouldn't change between parts
    author = series.raw_series.author
    collection = (series.raw_series.id, series.raw_series.title)
    if len(parts_to_download) == 1:
        # single part
        part = parts_to_download[0]
        identifier_base = part.raw_part.titleslug
        if _is_final(series, parts_to_download[-1]):
            complete_suffix = " - Final"
        else:
            complete_suffix = ""
        title = f"{part.raw_part.title}{complete_suffix}"

        cover_url_candidates = _cover_url_candidates(part.volume)
        # single part => single volume: part numbers relative to
        # that volume
        # TODO no TOC for single part ?
        toc = [f"Part {part.num_in_volume}"]
    else:
        volume_index = set()
        volumes = []
        for part in parts_to_download:
            if part.volume.volume_id in volume_index:
                continue
            volume_index.add(part.volume.volume_id)
            volumes.append(part.volume)

        if len(volumes) > 1:
            volume_nums = [str(volume.num) for volume in volumes]
            volume_nums = ", ".join(volume_nums[:-1]) + " & " + volume_nums[-1]
            title_base = f"{series.raw_series.title}: Volumes {volume_nums}"

            part1 = spec.to_relative_spec_from_part(parts_to_download[0])
            part2 = spec.to_relative_spec_from_part(parts_to_download[-1])

            part_nums = f"Parts {part1} to {part2}"

            # TODO simplify instead ?
            toc = [part.raw_part.title for part in parts_to_download]

            cover_url_candidates = _cover_url_candidates(volumes[0])
            title = f"{title_base} [{part_nums}]"
        else:
            volume = volumes[0]
            title_base = volume.raw_volume.title
            cover_url_candidates = _cover_url_candidates(volume)
            # relative to volume
            toc = [f"Part {part.num_in_volume}" for part in parts_to_download]

            if _is_complete(series, volume, parts_to_download):
                complete_suffix = " - Complete"
            elif _is_final(series, parts_to_download[-1]):
                complete_suffix = " - Final"
            else:
                complete_suffix = ""

            title = (
                f"{title_base} [Parts {parts_to_download[0].num_in_volume} to "
                f"{parts_to_download[-1].num_in_volume}{complete_suffix}]"
            )

        identifier_base = series.raw_series.titleslug

    identifier = identifier_base + str(int(time.time()))

    return BookDetails(identifier, title, author, collection, cover_url_candidates, toc)


def _is_final(series, part):
    """
    Tells if the part is the last one of the volume it belongs to
    """
    # if not last volume, can tell for sure
    if part.volume != series.volumes[-1]:
        return part == part.volume.parts[-1]

    # last volume

    # must be at the very least the last part listed for the volume
    # seen some bug where the test on totalPartNumber below
    # can be true even if not the last part
    if part != part.volume.parts[-1]:
        return False

    # totalPartNumber comes from the API and is set only for some
    # series; Sometimes set on unfinished volumes but not present once the
    # volume is complete... (in this case return false: not possible to tell)
    total_pn_in_volume = part.volume.raw_volume.totalPartNumber
    if total_pn_in_volume:
        # Should be == if no issue but...
        # >= instead : I saw a volume where the last part was bigger than
        # totalPartNumber (By the Grace of the Gods vol 6 => TPN = 10, but last
        # part is 11)
        return part.num_in_volume >= total_pn_in_volume
    else:
        # we can't tell
        return False


def _is_complete(series, volume, parts_in_volume_to_dl):
    last_volume = series.volumes[-1]
    if volume is not last_volume:
        return len(parts_in_volume_to_dl) == len(volume.parts)
    else:
        return len(parts_in_volume_to_dl) == len(volume.parts) and _is_final(
            series, parts_in_volume_to_dl[-1]
        )


def _create_epub_file(
    output_filepath,
    book_details,
    cover_bytes,
    parts,
    contents,
    img_urls,
):
    lang = "en"
    book = epub.EpubBook()
    book.set_identifier(book_details.identifier)
    book.set_title(book_details.title)
    book.set_language(lang)
    book.add_author(book_details.author)

    # metadata for series GH issue #9
    collection_id, collection_title = book_details.collection
    book.add_metadata(
        "OPF",
        "belongs-to-collection",
        collection_title,
        {"property": "belongs-to-collection", "id": collection_id},
    )
    book.add_metadata(
        "OPF",
        "collection-type",
        "series",
        {"property": "collection-type", "refines": f"#{collection_id}"},
    )
    # as position, set the volume number of the first part in the epub
    # in Calibre, display 1 (I) if not set so a bit better
    book.add_metadata(
        "OPF",
        "group-position",
        str(parts[0].volume.num),
        {"property": "group-position", "refines": f"#{collection_id}"},
    )

    book.set_cover("cover.jpg", cover_bytes, False)

    style = """body {color: black;}
h1 {page-break-before: always;}
img {width: 100%; page-break-after: always; page-break-before: always;}
p {text-indent: 1.3em;}
.centerp {text-align: center; text-indent: 0em;}
.noindent {text-indent: 0em;}"""
    css = epub.EpubItem(
        uid="style", file_name="book.css", media_type="text/css", content=style
    )
    book.add_item(css)

    cover_page = epub.EpubHtml(title="Cover", file_name="cover.xhtml", lang=lang)
    cover_page.content = '<img src="cover.jpg" alt="cover" />'
    cover_page.add_item(css)
    book.add_item(cover_page)

    for img_url, img_content in img_urls.items():
        img_bytes, local_filename, _ = img_content
        img = epub.EpubImage()
        img.file_name = local_filename
        img.media_type = "image/jpeg"
        img.content = img_bytes
        book.add_item(img)

    chapters = []
    for i, content in enumerate(contents):
        c = epub.EpubHtml(
            title=book_details.toc[i], file_name=f"chap_{i +1}.xhtml", lang=lang
        )
        # explicit encoding to bytes or some issue with lxml on some platforms (PyDroid)
        # some message about USC4 little endian not supported
        c.content = content.encode("utf-8")
        c.add_item(css)
        book.add_item(c)
        chapters.append(c)

    book.toc = chapters

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    book.spine = [cover_page, "nav", *chapters]

    epub.write_epub(output_filepath, book, {})


def _cover_url_candidates(volume):
    # for each part in the volume, get the biggest cover image attachment
    # usually the first part will have the biggest (cvr_860.jpg), but API
    # may return invalid file ; so generate multiple candidates
    # TODO get the max for all candidates not all individually
    candidates = list(
        filter(None, [_cover_url(part.raw_part) for part in volume.parts])
    )

    # cover in the volume as ultimate fallback
    # usually has a cover_400.jpg
    candidates.append(_cover_url(volume.raw_volume))

    return candidates


def _cover_url(raw_metadata):
    if raw_metadata.attachments:
        covers = list(
            filter(
                lambda a: "cvr" in a.filename or "cover" in a.filename,
                raw_metadata.attachments,
            )
        )
        if len(covers) > 0:
            cover = max(covers, key=lambda c: c.size)
            return f"{jncapi_legacy.IMG_URL_BASE}/{cover.fullpath}"
    return None


class ImgUrlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.img_urls = []

    def handle_starttag(self, tag, tag_attrs):
        if tag != "img":
            return

        for tag_attr in tag_attrs:
            if tag_attr[0] == "src":
                self.img_urls.append(tag_attr[1])
                break


def _img_urls(content):
    parser = ImgUrlParser()
    parser.feed(content)
    return parser.img_urls


def _to_safe_filename(name):
    s = re.sub("[^0-9a-zA-Z]+", "_", name).strip("_")
    return s
