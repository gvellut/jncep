from collections import namedtuple
from html.parser import HTMLParser
import json
import logging
import os
import os.path
from pathlib import Path
import re
import time

from addict import Dict as Addict
from atomicwrites import atomic_write
import attr
from ebooklib import epub

from . import jncapi
from .utils import green

logger = logging.getLogger(__package__)

RANGE_SEP = ":"

CONFIG_DIRPATH = Path.home() / ".jncep"


@attr.s
class Series:
    raw_series = attr.ib()
    volumes = attr.ib(default=None)
    parts = attr.ib(default=None)


@attr.s
class Volume:
    raw_volume = attr.ib()
    volume_id = attr.ib()
    num = attr.ib()
    parts = attr.ib(factory=list)


@attr.s
class Part:
    raw_part = attr.ib()
    volume = attr.ib()
    num_in_volume = attr.ib()
    absolute_num = attr.ib(default=None)
    content = attr.ib(default=None)


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


class CoverImageException(Exception):
    pass


def to_relative_part_string(series, part):
    volume_number = part.volume.num
    part_number = part.num_in_volume
    return f"{volume_number}.{part_number}"


def to_part(series, relpart_str) -> Part:
    # there will be an error if the relpart does not not existe
    parts = _analyze_volume_part_specs(series, relpart_str)
    return parts[0]


def to_pretty_part_name(series, part) -> str:
    part_str = f"Part_{part.num_in_volume}"
    title = part.volume.raw_volume.title
    return f"{_to_safe_filename(title)}_{part_str}"


def create_epub(token, series, parts, epub_generation_options):
    # here normally all parts in parameter are available
    contents, downloaded_img_urls, raw_contents = get_book_content_and_images(
        token, series, parts, epub_generation_options.is_not_replace_chars
    )
    identifier, title, author, cover_url_candidates, toc = get_book_details(
        series, parts
    )

    logger.info("Fetching cover image...")
    for cover_url in cover_url_candidates:
        if cover_url in downloaded_img_urls:
            # no need to redownload
            # tuple : index 0 => bytes content
            # TODO do not add same file (same content, different name) in EPUB
            cover_bytes = downloaded_img_urls[cover_url][0]
            break
        else:
            try:
                cover_bytes = jncapi.fetch_image_from_cdn(cover_url)
                break
            except Exception:
                logger.warning(
                    f"Unable to download cover image with URL: '{cover_url}'. "
                    "Trying next candidate..."
                )
                continue
    else:
        raise CoverImageException("No suitable cover could be downloaded!")

    output_filename = _to_safe_filename(title) + ".epub"
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
                to_pretty_part_name(series, part)
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
            content_filename = to_pretty_part_name(series, part) + ".html"
            content_filepath = os.path.join(
                epub_generation_options.output_dirpath, content_filename
            )
            with open(content_filepath, "w", encoding="utf-8") as content_f:
                content_f.write(content)

    create_epub_file(
        output_filepath,
        identifier,
        title,
        author,
        cover_bytes,
        parts,
        toc,
        contents,
        downloaded_img_urls,
    )
    logger.info(green(f"Success! EPUB generated in '{output_filepath}'!"))


def get_book_content_and_images(token, series, parts_to_download, is_not_replace_chars):
    downloaded_img_urls = {}
    contents = []
    raw_contents = []
    for part in parts_to_download:
        logger.info(f"Fetching part '{part.raw_part.title}'...")
        content = jncapi.fetch_content(token, part.raw_part.id)
        raw_contents.append(content)

        if not is_not_replace_chars:
            # both the chars to replace and replacement are hardcoded
            # U+2671 => East Syriac Cross (used in Her Majesty's Swarm)
            # U+25C6 => Black Diamond (used in SOAP)
            # U+1F3F6 => Black Rosette
            chars_to_replace = ["\u2671", "\u25C6", "\U0001F3F6"]
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
                    img_bytes = jncapi.fetch_image_from_cdn(img_url)
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


def get_book_details(series, parts_to_download):
    # shouldn't change between parts
    author = series.raw_series.author
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

            part1 = to_relative_part_string(series, parts_to_download[0])
            part2 = to_relative_part_string(series, parts_to_download[-1])

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

    return identifier, title, author, cover_url_candidates, toc


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


def create_epub_file(
    output_filepath,
    identifier,
    title,
    author,
    cover_bytes,
    parts,
    toc,
    contents,
    img_urls,
):
    lang = "en"
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)

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
        c = epub.EpubHtml(title=toc[i], file_name=f"chap_{i +1}.xhtml", lang=lang)
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
            return f"{jncapi.IMG_URL_BASE}/{cover.fullpath}"
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


def analyze_metadata(jnc_resource: jncapi.JNCResource):
    # takes order of parts as returned by API
    # (irrespective of actual partNumber)
    # reorder by volume ordering

    if jnc_resource.resource_type in (
        jncapi.RESOURCE_TYPE_PART,
        jncapi.RESOURCE_TYPE_VOLUME,
    ):
        series = Series(jnc_resource.raw_metadata.serie)
    else:
        series = Series(jnc_resource.raw_metadata)

    volumes = []
    volume_index = {}
    for raw_volume in series.raw_series.volumes:
        volume_num = len(volumes) + 1
        volume = Volume(raw_volume, raw_volume.id, volume_num)
        volume_index[volume.volume_id] = volume
        volumes.append(volume)

    is_warned = False
    for raw_part in series.raw_series.parts:
        volume_id = raw_part.volumeId
        volume: Volume = volume_index[volume_id]
        num_in_volume = len(volume.parts) + 1
        part = Part(raw_part, volume, num_in_volume)
        volume.parts.append(part)

    parts = []
    for volume in volumes:
        for part in volume.parts:
            # volume number ordering and part number ordering sometimes do not match
            # actually just for Altina volume 8 / 9
            # so set absolute num in sequential order according to volumes
            part.absolute_num = len(parts) + 1
            parts.append(part)

            # some series have a gap in the part number ie index does not correspond
            # to field partNumber e.g. economics of prophecy starting at part 10
            # print warning
            if part.absolute_num != part.raw_part.partNumber and not is_warned:
                # not an issue in practice so leave it in debug mode only
                logger.debug(
                    f"Absolute part number returned by API doesn't correspond to "
                    f"its actual position in series (corrected, starting at part "
                    f"{part.raw_part.partNumber} found in volume {volume.num})"
                )
                is_warned = True

    series.volumes = volumes
    series.parts = parts

    return series


def analyze_requested(jnc_resource, series):
    if jnc_resource.resource_type == jncapi.RESOURCE_TYPE_PART:
        # because partNumber sometimes has a gap => loop through all parts
        # to find the actual object (instead of using [partNumber] directly)
        for part in series.parts:
            if part.raw_part.partNumber == jnc_resource.raw_metadata.partNumber:
                return [part]

    if jnc_resource.resource_type == jncapi.RESOURCE_TYPE_VOLUME:
        iv = jnc_resource.raw_metadata.volumeNumber - 1
        return list(series.volumes[iv].parts)

    # series: all parts
    return list(series.parts)


def analyze_part_specs(series, part_specs, is_absolute):
    """ v(.p):v2(.p) or v(.p): or :v(.p) or v(.p) or : """

    part_specs = part_specs.strip()

    if part_specs == RANGE_SEP:
        return series.parts

    if is_absolute:
        return _analyze_absolute_part_specs(series, part_specs)

    return _analyze_volume_part_specs(series, part_specs)


def _analyze_absolute_part_specs(series, part_specs):  # noqa: C901
    parts = []
    sides = part_specs.split(RANGE_SEP)
    if len(sides) > 2:
        raise ValueError("Multiple ':' in part specs")

    reg = r"^\s*(\d+)\s*$"
    if len(sides) == 1:
        # not a range: single part
        m = re.match(reg, sides[0])
        if not m:
            raise ValueError("Specified part must be a number")
        fp = int(m.group(1))
        ifp = _validate_absolute_part_number(series, fp)
        return [series.parts[ifp]]

    # range
    m1 = re.match(reg, sides[0])
    m2 = re.match(reg, sides[1])
    if not m1 and not m2:
        msg = "Part specification must be <number>:<number> or <number>: or :<number>"
        raise ValueError(msg)

    if m1:
        fp = int(m1.group(1))
        ifp = _validate_absolute_part_number(series, fp)

    if m2:
        lp = int(m2.group(1))
        ilp = _validate_absolute_part_number(series, lp)

    if m1 and not m2:
        # to the end
        for ip in range(ifp, len(series.parts)):
            parts.append(series.parts[ip])
        return parts

    if m2 and not m1:
        # since the beginning
        # + 1 => include the second side of the range
        for ip in range(0, ilp + 1):
            parts.append(series.parts[ip])
        return parts

    # both sides are present
    if ifp > ilp:
        msg = "Second side of the part range must be greater than first"
        raise ValueError(msg)

    # + 1 => include the second side of the range
    for ip in range(ifp, ilp + 1):
        parts.append(series.parts[ip])
    return parts


def _validate_absolute_part_number(series, p):
    if p == 0:
        raise ValueError("Specified part number must be at least 1")
    # part specs start at 1 => transform to Python index
    ip = p - 1
    if ip >= len(series.parts):
        raise ValueError(
            "Specified part number must be less than the number of parts in series"
        )
    return ip


def _analyze_volume_part_specs(series, part_specs):  # noqa: C901
    parts = []
    sides = part_specs.split(RANGE_SEP)
    if len(sides) > 2:
        raise ValueError("Multiple ':' in part specs")

    reg = r"^\s*(\d+)(?:\.(\d+))?\s*$"
    if len(sides) == 1:
        # not a range: single part
        m = re.match(reg, sides[0])
        if not m:
            raise ValueError(
                "Specification must be a of the form 'vol[.part]' (part is optional)"
            )
        fv = int(m.group(1))
        if m.group(2):
            # only the part specified
            fp = int(m.group(2))
            iv, ip = _validate_volume_part_number(series, fv, fp)
            return [series.volumes[iv].parts[ip]]
        else:
            # full volume
            iv = _validate_volume_part_number(series, fv)
            for part in series.volumes[iv].parts:
                parts.append(part)
            return parts

    # range
    m1 = re.match(reg, sides[0])
    m2 = re.match(reg, sides[1])
    if (
        (not m1 and not m2)
        # left side not valid
        or (not m1 and len(sides[0]) > 0)
        # right side not valid
        or (not m2 and len(sides[1]) > 0)
    ):
        msg = (
            "Part specification must be vol[.part]:vol[.part] or vol[.part]: or "
            ":vol[.part]"
        )
        raise ValueError(msg)

    if m1:
        fv = int(m1.group(1))
        if m1.group(2):
            fp = int(m1.group(2))
            ifv, ifp = _validate_volume_part_number(series, fv, fp)
        else:
            ifv = _validate_volume_part_number(series, fv)
            # beginning of the volume
            ifp = 0
        ifp = _to_absolute_part_index(series, ifv, ifp)

    if m2:
        lv = int(m2.group(1))
        if m2.group(2):
            lp = int(m2.group(2))
            ilv, ilp = _validate_volume_part_number(series, lv, lp)
        else:
            ilv = _validate_volume_part_number(series, lv)
            # end of the volume
            ilp = -1
        # this works too if ilp == -1
        ilp = _to_absolute_part_index(series, ilv, ilp)

    # same as for absolute part spec

    if m1 and not m2:
        # to the end
        for ip in range(ifp, len(series.parts)):
            parts.append(series.parts[ip])
        return parts

    if m2 and not m1:
        # since the beginning
        # + 1 => include the second side of the range
        for ip in range(0, ilp + 1):
            parts.append(series.parts[ip])
        return parts

    # both sides are present
    if ifp > ilp:
        msg = "Second side of the vol[.part] range must be greater than first"
        raise ValueError(msg)

    # + 1 => always include the second side of the range
    for ip in range(ifp, ilp + 1):
        parts.append(series.parts[ip])
    return parts


def _validate_volume_part_number(series, v, p=None):
    iv = v - 1

    if iv >= len(series.volumes):
        raise ValueError(
            "Specified volume number must be less than the number of volumes in series"
        )
    volume = series.volumes[iv]

    if p is None:
        return iv

    ip = p - 1
    if ip >= len(volume.parts):
        raise ValueError(
            "Specified part number must be less than the number of parts in volume"
        )
    return iv, ip


def _to_absolute_part_index(series, iv, ip):
    volume = series.volumes[iv]
    return volume.parts[ip].absolute_num - 1


def read_tracked_series():
    try:
        with _tracked_series_filepath().open() as json_file:
            data = json.load(json_file)
            return _convert_to_latest_format(Addict(data))
    except FileNotFoundError:
        # first run ?
        return Addict({})


def _convert_to_latest_format(data):
    converted = {}
    # while at it convert from old format
    # legacy format for tracked parts : just the part instead of object
    # with keys part, name
    # key is slug
    # TODO rename "name" field into "title"
    for series_url_or_slug, value in data.items():
        if not isinstance(value, dict):
            series_slug = series_url_or_slug
            series_url = jncapi.url_from_series_slug(series_slug)
            # low effort way to get some title
            name = series_slug.replace("-", " ").title()
            value = Addict({"name": name, "part": value})
            converted[series_url] = value
        else:
            converted[series_url_or_slug] = value

    converted_b = {}
    for legacy_series_url, value in converted.items():
        new_series_url = jncapi.to_new_website_series_url(legacy_series_url)
        converted_b[new_series_url] = value

    return converted_b


def write_tracked_series(tracked):
    _ensure_config_dirpath_exists()
    with atomic_write(str(_tracked_series_filepath().resolve()), overwrite=True) as f:
        f.write(json.dumps(tracked, sort_keys=True, indent=2))


def _tracked_series_filepath():
    return CONFIG_DIRPATH / "tracked.json"


def _ensure_config_dirpath_exists():
    CONFIG_DIRPATH.mkdir(parents=False, exist_ok=True)
