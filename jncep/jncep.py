from collections import defaultdict
from html.parser import HTMLParser
import json
import os
import pickle
import re
import sys
from urllib.parse import urlparse

from addict import Dict as Addict
from ebooklib import epub
import requests
import requests_toolbelt.utils.dump

IMG_BASE_URL = "https://d2dq7ifhe7bu0f.cloudfront.net/"


def dump(response):
    data = requests_toolbelt.utils.dump.dump_response(response)
    print(data.decode("utf-8"))


def generate_epub(email, password, url_or_slug, part_specs=None, is_absolute=False):
    try:
        slug = slug_from_url(url_or_slug)
    except ValueError:
        # assume this is already a slug
        slug = url_or_slug

    if part_specs:
        specs = parse_part_specs(part_specs, is_absolute)
        # TODO more validation from < to, no 0, etc...

    token = login(email, password)
    metadata = fetch_metadata(token, slug)

    # TODO make struct of volumes => parts => volume
    # TODO struct should include part num relative to volume + cover links + id

    if "partNumber" in metadata:
        book_type = "PART"
        novel = metadata.serie
        if not part_specs:
            is_absolute = True
            specs = (metadata.partNumber,)
    elif "volumeNumber" in metadata:
        book_type = "VOLUME"
        novel = metadata.serie
        if not part_specs:
            is_absolute = False
            specs = ((metadata.volumeNumber,),)
    else:
        book_type = "NOVEL"
        novel = metadata
        if not part_specs:
            is_absolute = False
            specs = ()

    parts_to_download = _analyze_part_specs(novel, specs)

    contents = []
    for part in parts_to_download:
        contents.append(fetch_content(token, part.id))

    # TODO download images : cover + text images + add to epub + update links
    # TODO make TOC with image covers + sections if parts from multiple volumes
    # in same epub

    first_part = parts_to_download[0]
    identifier = first_part.titleslug
    title = first_part.title
    author = first_part.author

    create_epub(identifier, title, author, parts_to_download, contents)


def login(email, password):
    url = "https://api.j-novel.club/api/users/login?include=user"
    headers = {"accept": "application/json", "content-type": "application/json"}
    payload = {"email": email, "password": password}

    r = requests.post(url, data=json.dumps(payload), headers=headers)
    r.raise_for_status()

    access_token_cookie = r.cookies["access_token"]
    access_token = access_token_cookie[4 : access_token_cookie.index(".")]

    return access_token


def fetch_metadata(token, slug):
    url = "https://api.j-novel.club/api/parts/findOne"
    headers = {
        "authorization": token,
        "accept": "application/json",
        "content-type": "application/json",
    }
    qfilter = {
        "where": {"titleslug": slug},
        "include": [{"serie": ["volumes", "parts"]}, "volume"],
    }
    payload = {"filter": json.dumps(qfilter)}

    r = requests.get(url, headers=headers, params=payload)
    r.raise_for_status()

    return Addict(r.json())


def fetch_content(token, part_id):
    url = f"https://api.j-novel.club/api/parts/{part_id}/partData"
    headers = {
        "authorization": token,
        "accept": "application/json",
        "content-type": "application/json",
    }
    r = requests.get(url, headers=headers)
    r.raise_for_status()

    return r.json()["dataHTML"]


def create_epub(identifier, title, author, parts, contents):
    lang = "en"
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)

    book.set_cover("cover.jpg", open("cover.jpg", "rb").read(), False)

    style = """body {color: pink;}
img {width: 100%; page-break-after: always;page-break-before: always;}"""
    css = epub.EpubItem(
        uid="style", file_name="book.css", media_type="text/css", content=style
    )
    book.add_item(css)

    cover_page = epub.EpubHtml(title="Cover", file_name="cover.xhtml", lang=lang)
    cover_page.content = '<img src="cover.jpg" alt="lalala" />'
    cover_page.add_item(css)
    book.add_item(cover_page)

    chapters = []
    for i, content in enumerate(contents):
        # TODO real title based on volume + part relative to volume
        c = epub.EpubHtml(
            title=parts[i].title, file_name=f"chap_{i +1}.xhtml", lang=lang
        )
        c.content = content
        c.add_item(css)
        book.add_item(c)
        chapters.append(c)

    book.toc = ((epub.Section("Simple book"), chapters),)

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    book.spine = ["nav", cover_page, *chapters]

    epub.write_epub("test.epub", book, {})


def slug_from_url(url):
    pu = urlparse(url)

    if pu.scheme == "":
        raise ValueError(f"Not a URL: {url}")
    # normally /c/<slug>/... or /s/<slug>/...
    if len(pu.path) <= 1 or pu.path[2] != "/":
        raise ValueError(f"Invalid slug for URL: {url}")

    slug_index = 3
    # valid even if no final /
    slug_rindex = pu.path.find("/", slug_index)
    return pu.path[slug_index:slug_rindex]


class ImgUrlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.img_urls = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return

        for attr in attrs:
            if attr[0] == "src":
                self.img_urls.append(attr[1])
                break


def get_img_urls(content):
    parser = ImgUrlParser()
    parser.feed(content)
    return parser.img_urls


def _analyze_part_specs(novel, specs, is_absolute):
    # TODO index volumes
    if specs == ():
        # download everything:
        download_specs = []
        for part in novel.parts:
            # TODO named tuple
            download_specs.append(part)
            return download_specs
    else:
        if is_absolute:
            return _analyze_absolute_part_specs(novel, specs)
        else:
            return _analyze_volume_part_specs(novel, specs)


def _analyze_volume_part_specs(novel, specs):
    if len(specs == 1):
        download_specs = []
        vp = specs[0]
        if len(vp == 1):
            # full volume
            if vp[0] > len(novel.volumes):
                # TODO more specific error
                raise ValueError(f"Invalid spec for novel: {specs}")
            volumeId = novel.volumes[vp[0] - 1].id
            for part in novel.parts:
                if part.volumeId == volumeId and part.preview:
                    download_specs.append((part.id, part.volumeId))
    else:
        return _analyze_range_volume_part_specs(novel, specs)

    return download_specs


def _analyze_range_volume_part_specs(novel, specs):
    download_specs = []
    num_parts_in_volume = defaultdict(int)
    volume_ids = []
    for part in novel.parts:
        if part.volumeId not in num_parts_in_volume:
            volume_ids.append(part.volumeId)
        num_parts_in_volume[part.volumeId] += 1

    # range
    vpf, vpt = specs
    vf, pf = vpf
    ivf = vf - 1
    volume_id_f = volume_ids[ivf]
    if pf > num_parts_in_volume[volume_id_f]:
        # TODO more specific error
        raise ValueError(f"Invalid spec for novel: {specs}")
    ipf = sum([num_parts_in_volume[volume_id] for volume_id in volume_ids[:ivf]]) + (
        pf - 1
    )

    vt, pt = vpt
    if vt == -1:
        ivt = len(volume_ids)
    else:
        ivt = vt
    volume_id_t = volume_ids[ivt - 1]

    ipt = sum([num_parts_in_volume[volume_id] for volume_id in volume_ids[: ivt - 1]])
    if pt == -1:
        ipt += num_parts_in_volume[volume_id_t]
    else:
        ipt += pt

    # TODO more validation before this
    for part in novel.parts[ipf:ipt]:
        if part.preview:
            download_specs.append(part)

    return download_specs


def _analyze_absolute_part_specs(novel, specs):
    download_specs = []
    if len(specs == 1):
        # specs are 1-based
        part = novel.parts[specs[0] - 1]
        download_specs.append(part)
    else:
        # range
        pf, pt = specs
        ipf = pf - 1
        if pt == -1:
            ipt = len(novel.parts)
        else:
            # spec assumes range includes end of range
            # not python
            ipt = pt

        # ipt is same as pt except when -1
        if pf > len(novel.parts) or ipt > len(novel.parts):
            # TODO more specific error
            raise ValueError(f"Invalid spec for novel: {specs}")

        # TODO more validation before this
        for part in novel.parts[ipf:ipt]:
            if part.preview:
                download_specs.append(part)

    return download_specs


def parse_part_specs(part_specs, is_absolute):
    """ v(.p):v2(.p) or v(.p): or v(.p) """
    if part_specs == ":":
        return ()

    if is_absolute:
        reg = r"^(\d+)(?:(:)(\d+)?)?$"
        m = re.match(reg, part_specs)
        if m:
            fp = int(m.group(1))
            is_range = m.group(2) is not None
            if is_range:
                if m.group(3):
                    return (fp, int(m.group(3)))
                else:
                    return (fp, -1)
            else:
                return (fp,)
        else:
            raise ValueError(f"Invalid absolute part specification: {part_specs}")
    else:
        reg = r"^(\d+)(\.\d+)?(?:(:)(?:(\d+)(\.\d+)?)?)?$"
        m = re.match(reg, part_specs)
        if m:
            is_range = m.group(3) is not None
            if m.group(2):
                fp = (int(m.group(1)), int(m.group(2)))
            else:
                if is_range:
                    fp = (int(m.group(1)), 1)
                else:
                    fp = (int(m.group(1)),)
            if is_range:
                if m.group(4):
                    if m.group(5):
                        tp = (int(m.group(4)), int(m.group(5)))
                    else:
                        tp = (int(m.group(4)), -1)
                else:
                    tp = (-1, -1)
                return (fp, tp)
            else:
                return (fp,)
        else:
            raise ValueError(f"Invalid part specification: {part_specs}")


if __name__ == "__main__":
    # token = login(sys.argv[0], sys.argv[1])
    # print(token)
    # slug = slug_from_url(
    #     "https://j-novel.club/c/welcome-to-japan-ms-elf-volume-3-part-9/read"
    # )
    # print(slug)
    # token = sys.argv[0]
    # metadata = fetch_metadata(token, slug)

    # pickle_out = open("data.pickle", "wb")
    # pickle.dump(book, pickle_out)
    # pickle_out.close()

    pickle_in = open("data.pickle", "rb")
    metadata = pickle.load(pickle_in)

    print(metadata.title)

    if "totalVolumes" in metadata:
        # series
        novel = metadata
    else:
        novel = metadata.serie

    if "partNumber" in metadata:
        book_type = "PART"
    elif "volumeNumber" in metadata:
        book_type = "VOLUME"
    else:
        book_type = "NOVEL"

    if book_type == "PART":
        # html_content = fetch_content(token, metadata.id)

        identifier = metadata.titleslug
        title = metadata.title
        author = metadata.author

        create_epub(identifier, title, author, None)
    else:
        pass

    # specific part

    # partNumber, id
    # .serie.volumes : id
    # .serie.parts . volumeId, id, partNumber, preview

    # specific volume
    # volumeNumber + serie

    # series
    # totalVolumes
    # volumes
    # parts
