from html.parser import HTMLParser
import os
import re
import time

import attr
import click
from ebooklib import epub
from termcolor import colored

from . import jncapi

RANGE_SEP = ":"


@click.command(help="Generate EPUB files for J-Novel Club pre-pub novels")
@click.argument("url_or_slug", metavar="JNOVEL_CLUB_URL")
@click.option(
    "-l", "--email", required=True, help="Login email for J-Novel Club account",
)
@click.option(
    "-p", "--password", required=True, help="Login password for J-Novel Club account",
)
@click.option(
    "-o",
    "--output",
    "output_filepath",
    type=click.Path(),
    help="Output EPUB file or folder (must exist)",
)
@click.option(
    "-s",
    "--parts",
    "part_specs",
    help=(
        "Specification of a range of parts to download in the form of "
        "<vol>[.part]:<vol>[.part]"
    ),
)
@click.option(
    "-a",
    "--absolute",
    "is_absolute",
    is_flag=True,
    help=(
        (
            "Indicates that the --parts option specifies part numbers globally, "
            "instead of relative to a volume i.e. <part>:<part>"
        )
    ),
)
def generate_epub(
    url_or_slug,
    email,
    password,
    part_specs=None,
    is_absolute=False,
    output_filepath=None,
):
    slug = jncapi.slug_from_url(url_or_slug)

    print(f"Login with email '{email}'...")
    token = jncapi.login(email, password)

    print(f"Fetching metadata for '{slug[0]}'...")
    metadata = jncapi.fetch_metadata(token, slug)

    novel = _analyze_novel_metadata(slug[1], metadata)
    if part_specs:
        print(
            f"Using part specification '{part_specs}' "
            f"(absolute={_to_yn(is_absolute)})..."
        )
        parts_to_download = _analyze_part_specs(novel, part_specs, is_absolute)
    else:
        parts_to_download = _analyze_requested(novel)

    # preview => parts 1 of each volume, always available
    # not expired => prepub
    available_parts_to_download = list(
        filter(
            lambda p: p.raw_part.preview or not p.raw_part.expired, parts_to_download
        )
    )

    if len(available_parts_to_download) == 0:
        raise NoRequestedPartAvailableError(
            "None of the requested parts are available for reading"
        )

    if len(available_parts_to_download) != len(parts_to_download):
        print(
            colored(
                "Some of the requested parts are not available for reading !", "yellow"
            )
        )

    contents, downloaded_img_urls = _get_book_content_and_images(
        token, novel, available_parts_to_download
    )

    identifier, title, author, cover_url = _get_book_details(
        novel, available_parts_to_download
    )

    if cover_url in downloaded_img_urls:
        # no need to redownload
        # tuple : index 0 => bytes content
        # TODO do not add same file (same content, different name) in EPUB
        cover_bytes = downloaded_img_urls[cover_url][0]
    else:
        print("Fetching cover image...")
        cover_bytes = jncapi.fetch_image_from_cdn(cover_url)

    if not output_filepath:
        output_folder = os.getcwd()
        output_filename = _to_safe_filename(title) + ".epub"
        output_filepath = os.path.join(output_folder, output_filename)
    else:
        if not output_filepath.lower().endswith(".epub"):
            # assumes it is folder : must exist or error later
            output_folder = output_filepath
            output_filename = _to_safe_filename(title) + ".epub"
            output_filepath = os.path.join(output_folder, output_filename)

    _create_epub(
        output_filepath,
        identifier,
        title,
        author,
        cover_bytes,
        available_parts_to_download,
        contents,
        downloaded_img_urls,
    )
    print(colored(f"Success! EPUB generated in '{output_filepath}'!", "green"))


@attr.s
class Novel:
    raw_serie = attr.ib()
    raw_metadata = attr.ib()
    requested_type = attr.ib()
    volumes = attr.ib(default=None)
    parts = attr.ib(default=None)


@attr.s
class Volume:
    raw_volume = attr.ib()
    volume_id = attr.ib()
    parts = attr.ib(factory=list)


@attr.s
class Part:
    raw_part = attr.ib()
    num_in_volume = attr.ib()
    volume = attr.ib()
    content = attr.ib(default=None)


class NoRequestedPartAvailableError(Exception):
    def __init__(self, msg):
        super().__init__(self, msg)


def _get_book_content_and_images(token, novel, parts_to_download):
    downloaded_img_urls = {}
    contents = []
    for part in parts_to_download:
        print(f"Fetching part '{part.raw_part.title}'...")
        content = jncapi.fetch_content(token, part.raw_part.id)

        img_urls = _img_urls(content)
        if len(img_urls) > 0:
            print("Fetching images found in part content...")
            for i, img_url in enumerate(img_urls):
                print(f"Image {i + 1}...")
                # TODO catch, log  and ignore if error ?
                img_bytes = jncapi.fetch_image_from_cdn(img_url)
                # the filename relative to the epub content root
                # file will be added to the Epub archive
                # safe_filename on the base name (without the extension)
                new_local_filename = _to_safe_filename(img_url[:-4]) + img_url[-4:]
                downloaded_img_urls[img_url] = (img_bytes, new_local_filename)
                content = content.replace(img_url, new_local_filename)

        contents.append(content)

    return contents, downloaded_img_urls


def _get_book_details(novel, parts_to_download):
    # shouldn't change between parts
    author = novel.raw_metadata.author
    if len(parts_to_download) == 1:
        # single part
        part = parts_to_download[0]
        titleslug_base = part.raw_part.titleslug
        title = part.raw_part.title
        cover_url = _cover_url(part.raw_part)
    else:
        volume_index = set()
        volumes = []
        for part in parts_to_download:
            if part.volume.volume_id in volume_index:
                continue
            volume_index.add(part.volume.volume_id)
            volumes.append(part.volume)

        part_nums = [str(part.raw_part.partNumber) for part in parts_to_download]
        part_nums = f"Parts {part_nums[0]} to {part_nums[-1]}"

        if len(volumes) > 1:
            volume_nums = [str(volume.raw_volume.volume_number) for volume in volumes]
            volume_nums = ",".join(volume_nums[:-1]) + "&" + volume_nums[-1]
            title_base = f"{novel.raw_serie.title}: Volumes {volume_nums}"

            # TODO use cover of the first volume in current parts instead of volume 1

            # use the first part of the series
            # has cvr_860.jpg which is bigger than the cover_400 in novel
            # weird
            cover_url = _cover_url(novel.parts[0].raw_part)
        else:
            title_base = volumes[0].raw_volume.title
            # same : use first part in volume which has cvr_860
            cover_url = _cover_url(volumes[0].parts[0].raw_part)

        titleslug_base = novel.raw_serie.titleslug
        title = f"{title_base} [{part_nums}]"

    identifier = titleslug_base + str(int(time.time()))
    title = title
    author = author

    return identifier, title, author, cover_url


def _create_epub(
    output_filepath, identifier, title, author, cover_bytes, parts, contents, img_urls
):
    lang = "en"
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)

    book.set_cover("cover.jpg", cover_bytes, False)

    style = """body {color: black;}
h1 {page-break-before:always;}
img {width: 100%; page-break-after: always;page-break-before: always;}"""
    css = epub.EpubItem(
        uid="style", file_name="book.css", media_type="text/css", content=style
    )
    book.add_item(css)

    cover_page = epub.EpubHtml(title="Cover", file_name="cover.xhtml", lang=lang)
    cover_page.content = '<img src="cover.jpg" alt="cover" />'
    cover_page.add_item(css)
    book.add_item(cover_page)

    for img_url, img_content in img_urls.items():
        img_bytes, local_filename = img_content
        img = epub.EpubImage()
        img.file_name = local_filename
        img.media_type = "image/jpeg"
        img.content = img_bytes
        book.add_item(img)

    # TODO cover images between volumes if multiple
    chapters = []
    for i, content in enumerate(contents):
        c = epub.EpubHtml(
            title=parts[i].raw_part.title, file_name=f"chap_{i +1}.xhtml", lang=lang
        )
        c.content = content
        c.add_item(css)
        book.add_item(c)
        chapters.append(c)

    book.toc = chapters

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    book.spine = [cover_page, "nav", *chapters]

    epub.write_epub(output_filepath, book, {})


def _cover_url(raw_metadata):
    covers = list(
        filter(
            lambda a: "cvr" in a.filename or "cover" in a.filename,
            raw_metadata.attachments,
        )
    )
    cover = max(covers, key=lambda c: c.size)
    return f"{jncapi.IMG_BASE_URL}{cover.fullpath}"


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


def _analyze_novel_metadata(req_type, metadata):
    """ Assumes the JSON returned from the API has all the parts and
    that they are ordered """
    # TODO don't trust and reorder no matter what ?

    if req_type in ("PART", "VOLUME"):
        novel = Novel(metadata.serie, metadata, req_type)
    else:
        novel = Novel(metadata, metadata, "NOVEL")

    volume_index = {}
    volumes = []
    for raw_volume in novel.raw_serie.volumes:
        volume = Volume(raw_volume, raw_volume.id)
        volumes.append(volume)
        volume_index[volume.volume_id] = volume

    parts = []
    for raw_part in novel.raw_serie.parts:
        volume_id = raw_part.volumeId
        volume = volume_index[volume_id]
        part = Part(raw_part, len(volume.parts) + 1, volume)
        volume.parts.append(part)
        parts.append(part)

    novel.volumes = volumes
    novel.parts = parts

    return novel


def _analyze_requested(novel):
    if novel.requested_type == "PART":
        ip = novel.raw_metadata.partNumber - 1
        return [novel.parts[ip]]

    if novel.requested_type == "VOLUME":
        iv = novel.raw_metadata.volumeNumber - 1
        return list(novel.volumes[iv].parts)

    # novel: all parts
    return list(novel.parts)


def _analyze_part_specs(novel, part_specs, is_absolute):
    """ v(.p):v2(.p) or v(.p): or :v(.p) or v(.p) or : """

    part_specs = part_specs.strip()

    if part_specs == RANGE_SEP:
        return novel.parts

    if is_absolute:
        return _analyze_absolute_part_specs(novel, part_specs)

    return _analyze_volume_part_specs(novel, part_specs)


def _analyze_absolute_part_specs(novel, part_specs):  # noqa: C901
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
        ifp = _validate_absolute_part_number(novel, fp)
        return [novel.parts[ifp]]

    # range
    m1 = re.match(reg, sides[0])
    m2 = re.match(reg, sides[1])
    if not m1 and not m2:
        msg = "Part specification must be <number>:<number> or <number>: or :<number>"
        raise ValueError(msg)

    if m1:
        fp = int(m1.group(1))
        ifp = _validate_absolute_part_number(novel, fp)

    if m2:
        lp = int(m2.group(1))
        ilp = _validate_absolute_part_number(novel, lp)

    if m1 and not m2:
        # to the end
        for ip in range(ifp, len(novel.parts)):
            parts.append(novel.parts[ip])
        return parts

    if m2 and not m1:
        # since the beginning
        # + 1 => include the second side of the range
        for ip in range(0, ilp + 1):
            parts.append(novel.parts[ip])
        return parts

    # both sides are present
    if ifp > ilp:
        msg = "Second side of the part range must be greater than first"
        raise ValueError(msg)

    # + 1 => include the second side of the range
    for ip in range(ifp, ilp + 1):
        parts.append(novel.parts[ip])
    return parts


def _validate_absolute_part_number(novel, p):
    if p == 0:
        raise ValueError("Specified part number must be at least 1")
    # part specs start at 1 => transform to Python index
    ip = p - 1
    if ip >= len(novel.parts):
        raise ValueError(
            "Specified part number must be less than the number of parts in novel"
        )
    return ip


def _analyze_volume_part_specs(novel, part_specs):  # noqa: C901
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
            iv, ip = _validate_volume_part_number(novel, fv, fp)
            return [novel.volumes[iv].parts[ip]]
        else:
            # full volume
            iv = _validate_volume_part_number(novel, fv)
            for part in novel.volumes[iv].parts:
                parts.append(part)
            return parts

    # range
    m1 = re.match(reg, sides[0])
    m2 = re.match(reg, sides[1])
    if not m1 and not m2:
        msg = (
            "Part specification must be vol[.part]:vol[.part] or vol[.part]: or "
            ":vol[.part]"
        )
        raise ValueError(msg)

    if m1:
        fv = int(m1.group(1))
        if m1.group(2):
            fp = int(m1.group(2))
            ifv, ifp = _validate_volume_part_number(novel, fv, fp)
        else:
            ifv = _validate_volume_part_number(novel, fv)
            # beginning of the volume
            ifp = 0
        ifp = _to_absolute_part_number(novel, ifv, ifp)

    if m2:
        lv = int(m2.group(1))
        if m2.group(2):
            lp = int(m2.group(2))
            ilv, ilp = _validate_volume_part_number(novel, lv, lp)
        else:
            ilv = _validate_volume_part_number(novel, lv)
            # end of the volume
            ilp = -1
        # this works too if ilp == -1
        ilp = _to_absolute_part_number(novel, ilv, ilp)

    # same as for absolute part spec

    if m1 and not m2:
        # to the end
        for ip in range(ifp, len(novel.parts)):
            parts.append(novel.parts[ip])
        return parts

    if m2 and not m1:
        # since the beginning
        # + 1 => include the second side of the range
        for ip in range(0, ilp + 1):
            parts.append(novel.parts[ip])
        return parts

    # both sides are present
    if ifp > ilp:
        msg = "Second side of the vol[.part] range must be greater than first"
        raise ValueError(msg)

    # + 1 => always include the second side of the range
    for ip in range(ifp, ilp + 1):
        parts.append(novel.parts[ip])
    return parts


def _validate_volume_part_number(novel, v, p=None):
    iv = v - 1

    if iv >= len(novel.volumes):
        raise ValueError(
            "Specified volume number must be less than the number of volumes in novel"
        )
    volume = novel.volumes[iv]

    if p is None:
        return iv

    ip = p - 1
    if ip >= len(volume.parts):
        raise ValueError(
            "Specified part number must be less than the number of parts in volume"
        )
    return iv, ip


def _to_absolute_part_number(novel, iv, ip):
    volume = novel.volumes[iv]
    return volume.parts[ip].raw_part.partNumber - 1


def _to_yn(b):
    if b:
        return "yes"
    return "no"


def main():
    try:
        generate_epub(auto_envvar_prefix="JNCEP")
    except Exception as ex:
        print(colored("*** An unrecoverable error occured ***", "red"))
        print(colored(str(ex), "red"))


if __name__ == "__main__":
    main()
