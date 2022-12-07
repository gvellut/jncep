import logging

import attr
from ebooklib import epub
import importlib_resources as imres

from .model import Image

logger = logging.getLogger(__name__)


@attr.s
class BookDetails:
    identifier = attr.ib()
    title = attr.ib()
    title_segments = attr.ib()
    author = attr.ib()
    collection = attr.ib()
    cover_image = attr.ib()
    toc = attr.ib()
    contents = attr.ib()
    images = attr.ib()


@attr.s
class CollectionMetadata:
    collection_id = attr.ib()
    collection_title = attr.ib()
    position = attr.ib()


DEFAULT_STYLE_CSS_PATH = "res/style.css"
DEFAULT_STYLE_CSS = None


def read_default_style_css():
    global DEFAULT_STYLE_CSS
    DEFAULT_STYLE_CSS = (
        imres.files(__package__).joinpath(DEFAULT_STYLE_CSS_PATH).read_text()
    )


def get_css(style_css_path):
    if style_css_path:
        with open(style_css_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if not DEFAULT_STYLE_CSS:
        read_default_style_css()

    return DEFAULT_STYLE_CSS


def output_epub(output_filepath, book_details: BookDetails, style_css_path=None):
    lang = "en"
    book = epub.EpubBook()
    book.set_identifier(book_details.identifier)
    book.set_title(book_details.title)
    book.set_language(lang)
    book.add_author(book_details.author)

    # metadata for series GH issue #9
    collection_meta = book_details.collection
    book.add_metadata(
        "OPF",
        "belongs-to-collection",
        collection_meta.collection_title,
        {"property": "belongs-to-collection", "id": collection_meta.collection_id},
    )
    book.add_metadata(
        "OPF",
        "collection-type",
        "series",
        {"property": "collection-type", "refines": f"#{collection_meta.collection_id}"},
    )

    book.add_metadata(
        "OPF",
        "group-position",
        str(collection_meta.position),
        {"property": "group-position", "refines": f"#{collection_meta.collection_id}"},
    )

    if book_details.cover_image:
        content = book_details.cover_image.content
        # in case cover image also present in content, use the file name
        # (same URL => same local filename or cover.jpg (renamed in core.py))
        cover_image_filename = book_details.cover_image.local_filename
    else:
        # the lib handles that semi-gracefully (doesn't crash)
        # may look broken in epub reader
        # TODO handle problem with missing cover => use dummy jpeg
        content = None
        # dummy file name
        cover_image_filename = "cover.jpg"

    # TODO why not True ? check
    book.set_cover(cover_image_filename, content, False)

    style = get_css(style_css_path)

    css = epub.EpubItem(
        uid="style", file_name="book.css", media_type="text/css", content=style
    )
    book.add_item(css)

    # TODO cf why not True ? above
    cover_page = epub.EpubHtml(title="Cover", file_name="cover.xhtml", lang=lang)
    cover_page.content = f'<img src="{cover_image_filename}" alt="cover" />'
    cover_page.add_item(css)
    book.add_item(cover_page)

    image: Image
    for image in book_details.images:
        # do not add if already added through cover or problems when writing:
        # "Duplicate name" warning from epublib + maybe issue in the epub zip structure
        if image.local_filename == cover_image_filename:
            continue
        img = epub.EpubImage()
        img.file_name = image.local_filename
        # TODO always ? check ?
        img.media_type = "image/jpeg"
        img.content = image.content
        book.add_item(img)

    chapters = []
    for i, content in enumerate(book_details.contents):
        c = epub.EpubHtml(
            title=book_details.toc[i], file_name=f"chap_{i}.xhtml", lang=lang
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
