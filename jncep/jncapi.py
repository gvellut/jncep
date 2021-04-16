import json
import logging
import re
from urllib.parse import urlparse, urlunparse

from addict import Dict as Addict
import attr
import requests
import requests_toolbelt.utils.dump

logger = logging.getLogger(__package__)

IMG_URL_BASE = "https://d2dq7ifhe7bu0f.cloudfront.net"
JNC_URL_BASE = "https://j-novel.club"
API_JNC_URL_BASE = "https://api.j-novel.club"

COMMON_API_HEADERS = {"accept": "application/json", "content-type": "application/json"}

RESOURCE_TYPE_NOVEL = "NOVEL"
RESOURCE_TYPE_VOLUME = "VOLUME"
RESOURCE_TYPE_PART = "PART"


@attr.s
class JNCResource:
    url = attr.ib()
    slug = attr.ib()
    is_new_website = attr.ib()
    resource_type = attr.ib()
    raw_metadata = attr.ib(default=None)

    def __str__(self):
        pu = urlparse(self.url)
        # remove scheme + domain
        return urlunparse(("", "", *pu[2:]))


def login(email, password):
    url = f"{API_JNC_URL_BASE}/api/users/login?include=user"
    headers = COMMON_API_HEADERS
    payload = {"email": email, "password": password}

    r = requests.post(url, data=json.dumps(payload), headers=headers)
    r.raise_for_status()

    access_token_cookie = r.cookies["access_token"]
    access_token = access_token_cookie[4 : access_token_cookie.index(".")]

    return access_token


def logout(token):
    url = f"{API_JNC_URL_BASE}/api/users/logout"
    headers = {"authorization": token, **COMMON_API_HEADERS}
    r = requests.post(url, headers=headers)
    r.raise_for_status()


def fetch_metadata(token, jnc_resource: JNCResource):
    if jnc_resource.resource_type == RESOURCE_TYPE_PART:
        res_type = "parts"
        include = [{"serie": ["volumes", "parts"]}, "volume"]
        where = {"titleslug": jnc_resource.slug}
    elif jnc_resource.resource_type == RESOURCE_TYPE_VOLUME:
        if jnc_resource.is_new_website:
            # for volume on new website => where is a tuple (series_slug, volume num)
            series_slug, volume_number = jnc_resource.slug

            # TODO is the volume sluge always : <series_slug>-volume-<vol_num>
            # TOOD if so can be simplified

            # just in case do 2 queries

            # first fetch series since we have the slug for it
            res_type = "series"
            include = []
            where = {"titleslug": series_slug}
            series = _fetch_metadata_internal(token, res_type, where, include)

            serie_id = series.id
            res_type = "volumes"
            include = [{"serie": ["volumes", "parts"]}, "parts"]
            where = {"volumeNumber": volume_number, "serieId": serie_id}

        else:
            # old website URL
            res_type = "volumes"
            include = [{"serie": ["volumes", "parts"]}, "parts"]
            where = {"titleslug": jnc_resource.slug}
    else:
        res_type = "series"
        include = ["volumes", "parts"]
        where = {"titleslug": jnc_resource.slug}

    metadata = _fetch_metadata_internal(token, res_type, where, include)
    jnc_resource.raw_metadata = metadata
    return jnc_resource


def _fetch_metadata_internal(token, res_type, where, include):
    headers = {"authorization": token, **COMMON_API_HEADERS}
    url = f"{API_JNC_URL_BASE}/api/{res_type}/findOne"

    qfilter = {
        "where": where,
        "include": include,
    }
    payload = {"filter": json.dumps(qfilter)}

    r = requests.get(url, headers=headers, params=payload)
    r.raise_for_status()

    return Addict(r.json())


def fetch_content(token, part_id):
    url = f"{API_JNC_URL_BASE}/api/parts/{part_id}/partData"
    headers = {"authorization": token, **COMMON_API_HEADERS}
    r = requests.get(url, headers=headers)
    r.raise_for_status()

    return r.json()["dataHTML"]


def fetch_image_from_cdn(url):
    r = requests.get(url)
    r.raise_for_status()
    # should be JPEG
    return r.content


def fetch_follows(token):
    headers = {"authorization": token, **COMMON_API_HEADERS}
    url = f"{API_JNC_URL_BASE}/api/users/me"
    qfilter = {"include": [{"serieFollows": "serie"}]}
    payload = {"filter": json.dumps(qfilter)}

    r = requests.get(url, headers=headers, params=payload)
    r.raise_for_status()

    me_data = Addict(r.json())
    followed_series = []
    for s in me_data.serieFollows:
        series = s.serie
        slug = series.titleslug
        # the metadata is not as complete as the usual (with fetch_metadata)
        # but it can still be useful to avoid a call later to the API
        jnc_resource = JNCResource(
            url_from_series_slug(slug), slug, True, RESOURCE_TYPE_NOVEL, series
        )
        followed_series.append(jnc_resource)

    return followed_series


def follow_series(token, series_id):
    _set_follow(token, series_id, True)


def unfollow_series(token, series_id):
    _set_follow(token, series_id, False)


def _set_follow(token, series_id, is_follow):
    headers = {"authorization": token, **COMMON_API_HEADERS}

    action = "follow" if is_follow else "unfollow"
    url = f"{API_JNC_URL_BASE}/api/users/me/{action}"

    payload = {"serieId": series_id, "serieType": 1}

    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()


def resource_from_url(url):
    pu = urlparse(url)

    if pu.scheme == "":
        raise ValueError(f"Not a URL: {url}")

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
                return JNCResource(url, series_slug, True, RESOURCE_TYPE_NOVEL)
            m = re.match(v_re, pu.fragment)
            if m:
                # tuple with volume
                return JNCResource(
                    url, (series_slug, m.group(1)), True, RESOURCE_TYPE_VOLUME
                )
        else:
            m = re.match(c_re, pu.path)
            if m:
                return JNCResource(url, m.group(1), True, RESOURCE_TYPE_PART)

    raise ValueError(f"Invalid path for URL: {url}")


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
        return RESOURCE_TYPE_NOVEL


def _dump(response):
    data = requests_toolbelt.utils.dump.dump_response(response)
    logger.debug(data.decode("utf-8"))
