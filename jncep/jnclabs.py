import json
import logging
from os import PathLike

from addict import Dict as Addict
import asks
import attr

from . import jncweb

logger = logging.getLogger(__package__)

IMG_URL_BASE = "https://d2dq7ifhe7bu0f.cloudfront.net"
LABS_API_JNC_URL_BASE = "https://labs.j-novel.club"
API_JNC_URL_BASE = "https://api.j-novel.club"

LABS_API_JNC_PATH_BASE = "/app/v1"
API_JNC_PATH_BASE = "/api"

COMMON_API_HEADERS = {"accept": "application/json", "content-type": "application/json"}
COMMON_LABS_API_PARAMS = {"format": "json"}


@attr.s
class Series:
    id_ = attr.ib()
    title = attr.ib()
    volumes = attr.ib(default=None)


@attr.s
class Volume:
    id_ = attr.ib()
    title = attr.ib()
    num = attr.ib(default=None)
    series = attr.ib(default=None)


@attr.s
class Part:
    id_ = attr.ib()
    title = attr.ib()
    num_in_volume = attr.ib(default=None)
    content = attr.ib(default=None)
    volume = attr.ib(default=None)
    series = attr.ib(default=None)


class JNCLabsAPI:
    def __init__(self, connections=20):
        self.jnc_api_session = asks.Session(
            API_JNC_URL_BASE, connections=connections, headers=COMMON_API_HEADERS
        )
        self.labs_api_session = asks.Session(
            LABS_API_JNC_URL_BASE, connections=connections, headers=COMMON_API_HEADERS
        )

        self.token = None

    @property
    def is_logged_in(self):
        return self.token is not None

    def api_authentication(self):
        return {"authorization": self.token}

    def labs_authentication(self):
        return {"Authorization": f"Bearer {self.token}"}

    async def login(self, email, password):
        path = f"{LABS_API_JNC_PATH_BASE}/auth/login"
        payload = {"login": email, "password": password, "slim": True}
        params = {**COMMON_LABS_API_PARAMS}

        r = await self.labs_api_session.post(
            path=path, data=json.dumps(payload), params=params
        )
        r.raise_for_status()

        data = r.json()
        self.token = data["id"]

    async def logout(self):
        path = "/auth/logout"
        await self._call_labs_authenticated("POST", path)
        self.token = None

    async def fetch_metadata(self, jnc_resource: jncweb.JNCResource):
        if jnc_resource.resource_type == jncweb.RESOURCE_TYPE_SERIES:
            path = f"/series/{jnc_resource.slug}"
            r = await self._call_labs_authenticated("GET", path)

            data = Addict(r.json())
            series = Series(data.legacyId, data.title)
            return series
        elif jnc_resource.resource_type == jncweb.RESOURCE_TYPE_VOLUME:
            # tuple for new website
            # do not handle old website any more
            series_slug, volume_num = jnc_resource.slug
            series_url = jncweb.url_from_series_slug(series_slug)
            # simple
            series_resource = jncweb.resource_from_url(series_url)
            series = await self.fetch_metadata(series_resource)

            path = f"/series/{series.id_}/volumes"

            jnc_volume = None
            async for page in self._paginate(self.labs_api_session, "GET", path):
                for v in page["volumes"]:
                    if v.number == volume_num:
                        jnc_volume = v
                        break

            # TODO error handling if not found => bad URL

            volume = Volume(jnc_volume.legacyId, jnc_volume.title, volume_num, series)
            return volume
        else:
            path = f"/parts/{jnc_resource.slug}"
            r = await self._call_labs_authenticated("GET", path)

            data = Addict(r.json())
            part = Part(data.legacyId, data.title)
            return part

    async def _call_api_authenticated(
        self, method, path, headers=None, params=None, **kwargs
    ):
        auth = self.api_authentication()
        if not headers:
            headers = COMMON_API_HEADERS
        else:
            headers = {**COMMON_API_HEADERS, **headers}

        path = f"{API_JNC_PATH_BASE}{path}"

        r = await self._call_authenticated(
            self.jnc_api_session, method, path, auth, headers, params, **kwargs
        )
        return r

    async def _call_labs_authenticated(
        self, method, path, headers=None, params=None, **kwargs
    ):
        auth = self.labs_authentication()
        if not params:
            params = COMMON_LABS_API_PARAMS
        else:
            params = {**COMMON_LABS_API_PARAMS, **params}

        path = f"{LABS_API_JNC_PATH_BASE}{path}"

        r = await self._call_authenticated(
            self.labs_api_session, method, path, auth, headers, params, **kwargs
        )
        return r

    async def _call_authenticated(
        self, session, method, path, auth, headers, params, **kwargs
    ):
        if not headers:
            headers = auth
        else:
            headers = {**auth, **headers}

        r = await session.request(
            method, path=path, headers=headers, params=params, **kwargs
        )
        r.raise_for_status()
        return r

    async def _paginate(self, session, method, path, headers=None, **kwargs):
        if "params" in kwargs:
            params = kwargs.pop("params")
        else:
            params = {}

        skip = 0
        while True:
            params.update(skip=skip)
            r = await self._call_labs_authenticated(
                session, method, path, headers=headers, params=params, **kwargs
            )
            r = r.json()

            pagination = Addict(r.pop("pagination"))

            # what is left : list of dicts
            yield Addict(r)

            if pagination.lastPage:
                break
            skip += pagination.limit

    async def fetch_follows(self):
        path = "/users/me"
        qfilter = {"include": [{"serieFollows": "serie"}]}
        payload = {"filter": json.dumps(qfilter)}

        r = await self._call_api_authenticated("GET", path, params=payload)
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

    async def follow_series(self, series_id):
        await self._set_follow(series_id, True)

    async def unfollow_series(self, series_id):
        await self._set_follow(series_id, False)

    async def _set_follow(self, series_id, is_follow):
        action = "follow" if is_follow else "unfollow"
        path = f"{API_JNC_PATH_BASE}/users/me/{action}"

        payload = {"serieId": series_id, "serieType": 1}

        r = await self._call_api_authenticated("POST", path, json=payload)
        r.raise_for_status()


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
