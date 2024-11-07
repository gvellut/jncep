import logging
import re
from urllib.parse import urlparse, urlunparse

import attr

from .jncalts import find_origin, get_alt_config_for_origin

logger = logging.getLogger(__name__)


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
    origin = attr.ib()
    prefix = attr.ib()

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

    origin = find_origin(url)

    # try legacy URL first
    # path is: /c/<slug>/...  or /v/<slug>/... or /s/<slug>/...
    # for c_hapter, v_olume, s_erie
    m = re.match(r"^/(v|c|s)/(.+?)(?:(?=/)|$)", pu.path)
    if m:
        prefix = None
        # TODO still relevant ? maybe some stalled series are still present in the
        # tracking configuration
        return JNCResource(
            url, m.group(2), False, _to_const_legacy(m.group(1)), origin, prefix
        )
    else:
        # new site
        # new site changed titles to series in URL
        # so process both
        # Nina in FR has fr at root of path
        s_re = r"^(?:/(.{2}))?/(?:series|titles)/(.+?)(?:(?=/)|$)"
        c_re = r"^(?:/(.{2}))?/read/(.+?)(?:(?=/)|$)"
        v_re = r"^volume-(\d+)$"

        m = re.match(s_re, pu.path)
        if m:
            series_slug = m.group(2)
            prefix = m.group(1)
            if not pu.fragment:
                return JNCResource(
                    url, series_slug, True, RESOURCE_TYPE_SERIES, origin, prefix
                )
            m = re.match(v_re, pu.fragment)
            if m:
                # tuple with volume
                return JNCResource(
                    url,
                    (series_slug, int(m.group(1))),
                    True,
                    RESOURCE_TYPE_VOLUME,
                    origin,
                    prefix,
                )
        else:
            m = re.match(c_re, pu.path)
            if m:
                series_slug = m.group(2)
                prefix = m.group(1)
                return JNCResource(
                    url, series_slug, True, RESOURCE_TYPE_PART, origin, prefix
                )

    raise BadWebURLError(f"Invalid path for URL: {url}")


def url_from_series_slug(origin, series_slug):
    config = get_alt_config_for_origin(origin)

    # we ignore the path prefix : in Nina, /fr : to indicate the language of the web
    # page. Not present in JNC Main or for the DE version of Nina
    # If not there for Nina : default DE (but the series page is displayed correctly
    # event if the surrounding website is in other language so doesn't matter much)
    return f"{config.WEB_URL_BASE}/series/{series_slug}"


def to_new_website_series_url(series_url):
    # supports legacy URLs + new
    jnc_resource = resource_from_url(series_url)
    # outputs new URL
    new_series_url = url_from_series_slug(jnc_resource.origin, jnc_resource.slug)
    return new_series_url


def _to_const_legacy(req_type):
    if req_type == "c":
        return RESOURCE_TYPE_PART
    elif req_type == "v":
        return RESOURCE_TYPE_VOLUME
    else:
        return RESOURCE_TYPE_SERIES
