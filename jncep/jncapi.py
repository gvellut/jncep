import json
import logging

from addict import Dict as Addict
import attr
import requests
import requests_toolbelt.utils.dump

from . import jncweb

logger = logging.getLogger(__package__)

IMG_URL_BASE = "https://d2dq7ifhe7bu0f.cloudfront.net"
API_JNC_URL_BASE = "https://api.j-novel.club"

COMMON_API_HEADERS = {"accept": "application/json", "content-type": "application/json"}

# TODO remove raw_... from structs => no dep on API response struct + move to own module


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


def fetch_metadata(token, jnc_resource: jncweb.JNCResource):
    if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_PART:
        res_type = "parts"
        include = [{"serie": ["volumes", "parts"]}, "volume"]
        where = {"titleslug": jnc_resource.slug}
    elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
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
        jnc_resource = jncweb.JNCResource(
            jncweb.url_from_series_slug(slug),
            slug,
            True,
            jncweb.RESOURCE_TYPE_SERIES,
            series,
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


def _dump(response):
    data = requests_toolbelt.utils.dump.dump_response(response)
    logger.debug(data.decode("utf-8"))
