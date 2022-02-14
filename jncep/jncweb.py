import logging
import re
from urllib.parse import urlparse, urlunparse

import attr

logger = logging.getLogger(__name__)

JNC_URL_BASE = "https://j-novel.club"

RESOURCE_TYPE_SERIES = "SERIES"
RESOURCE_TYPE_VOLUME = "VOLUME"
RESOURCE_TYPE_PART = "PART"


class BadWebURLError(Exception):
    pass


@attr.s
class JNCResource:
    url = attr.ib()
    slug = attr.ib()
    is_new_website = attr.ib()
    resource_type = attr.ib()
    # used when fetching the follows and building a JNCRes
    follow_raw_data = attr.ib(None)

    def __str__(self):
        pu = urlparse(self.url)
        # remove scheme + domain
        return urlunparse(("", "", *pu[2:]))


def resource_from_url(url):
    pu = urlparse(url)

    if pu.scheme == "":
        raise BadWebURLError(f"Not a URL: {url}")

    # try legacy URL first
    # path is: /c/<slug>/...  or /v/<slug>/... or /s/<slug>/...
    # for c_hapter, v_olume, s_erie
    m = re.match(r"^/(v|c|s)/(.+?)(?:(?=/)|$)", pu.path)
    if m:
        return JNCResource(url, m.group(2), False, _to_const_legacy(m.group(1)))
    else:
        # new site
        # new site changed titles to series in URL
        # so process both
        s_re = r"^/(?:series|titles)/(.+?)(?:(?=/)|$)"
        c_re = r"^/read/(.+?)(?:(?=/)|$)"
        v_re = r"^volume-(\d+)$"

        m = re.match(s_re, pu.path)
        if m:
            series_slug = m.group(1)
            if not pu.fragment:
                return JNCResource(url, series_slug, True, RESOURCE_TYPE_SERIES)
            m = re.match(v_re, pu.fragment)
            if m:
                # tuple with volume
                return JNCResource(
                    url, (series_slug, int(m.group(1))), True, RESOURCE_TYPE_VOLUME
                )
        else:
            m = re.match(c_re, pu.path)
            if m:
                return JNCResource(url, m.group(1), True, RESOURCE_TYPE_PART)

    raise BadWebURLError(f"Invalid path for URL: {url}")


def url_from_series_slug(series_slug):
    # new URL
    return f"{JNC_URL_BASE}/series/{series_slug}"


def to_new_website_series_url(series_url):
    # supports legacy URLs + new
    jnc_resource = resource_from_url(series_url)
    # outputs new URL
    new_series_url = url_from_series_slug(jnc_resource.slug)
    return new_series_url


def _to_const_legacy(req_type):
    if req_type == "c":
        return RESOURCE_TYPE_PART
    elif req_type == "v":
        return RESOURCE_TYPE_VOLUME
    else:
        return RESOURCE_TYPE_SERIES
