from functools import wraps
import json
import logging

from addict import Dict as Addict
import asks
import trio

from . import jncweb, utils
from .utils import deep_freeze

logger = logging.getLogger(__name__)
console = utils.getConsole()

CDN_IMG_URL_BASE = "https://d2dq7ifhe7bu0f.cloudfront.net"

LABS_API_URL_BASE = "https://labs.j-novel.club"
LABS_API_PATH_BASE = "/app/v1"
LABS_API_COMMON_PARAMS = {"format": "json"}

LEGACY_API_URL_BASE = "https://api.j-novel.club"
LEGACY_API_PATH_BASE = "/api"
LEGACY_API_COMMON_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
}


class InvalidCDNRequestException(Exception):
    pass


def with_cache(f):
    @wraps(f)
    async def wrapper(*args, **kwargs):
        # with_cache used only for JNCLabsAPI so fine
        api = args[0]
        if not hasattr(api, "__cache"):
            # cache scoped to api instance
            api.__cache = ({}, {})
        cache, events = api.__cache

        # first arg is the API instance
        key = (*args[1:], *kwargs.items())
        while True:
            if key in events:
                # query running
                # wait for it to finish
                logger.debug(f"{key} in events")
                event = events[key]
                await event.wait()
                if key in cache:
                    logger.debug(f"Cache hit {key}")
                    return _copy_or_raw(cache[key])
                # must have been error in the query
                # retry from the beginning in case
                # multiple are waiting
                # TODO raise instead ?
                continue

            event = trio.Event()
            events[key] = event

            try:
                response = await f(*args, **kwargs)
                cache[key] = _copy_or_raw(response)
                return response
            except Exception:
                del events[key]
                raise
            finally:
                # wake up the tasks waiting
                event.set()

    return wrapper


def _copy_or_raw(data):
    if type(data) is Addict:
        cp = data.deepcopy()
        # alway refreeze : fine in this context
        deep_freeze(cp)
        return cp
    # an image content ; won't be modifed so can be shared
    return data


class JNCLabsAPI:
    def __init__(
        self,
        labs_api_connections=10,
        legacy_api_connections=10,
        cdn_connections=20,
        jncweb_connections=10,
        labs_api_default_timeout=20,
        legacy_api_default_timeout=20,
        cdn_default_timeout=30,
        jncweb_default_timeout=20,
        connection_timeout=None,
    ):
        # connection timeout is disabled by default => no timeout waiting for a
        # connection to be available from the rate limiter
        self.labs_api_session = asks.Session(
            LABS_API_URL_BASE,
            connections=labs_api_connections,
            headers=LEGACY_API_COMMON_HEADERS,
        )

        self.legacy_api_session = asks.Session(
            LEGACY_API_URL_BASE,
            connections=legacy_api_connections,
            headers=LEGACY_API_COMMON_HEADERS,
        )

        # CDN_IMG_URL_BASE not really necessary
        self.cdn_session = asks.Session(CDN_IMG_URL_BASE, connections=cdn_connections)

        self.jncweb_session = asks.Session(
            jncweb.JNC_URL_BASE, connections=jncweb_connections
        )

        self.labs_api_default_timeout = labs_api_default_timeout
        self.legacy_api_default_timeout = legacy_api_default_timeout
        self.cdn_default_timeout = cdn_default_timeout
        self.jncweb_default_timeout = jncweb_default_timeout

        self.connection_timeout = connection_timeout

        self.token = None

    @property
    def is_logged_in(self):
        return self.token is not None

    async def login(self, email, password):
        path = f"{LABS_API_PATH_BASE}/auth/login"
        payload = {"login": email, "password": password, "slim": True}
        params = {**LABS_API_COMMON_PARAMS}

        r = await self.labs_api_session.post(
            path=path,
            data=json.dumps(payload),
            params=params,
            connection_timeout=self.connection_timeout,
            timeout=self.labs_api_default_timeout,
        )
        r.raise_for_status()

        data = r.json()
        self.token = data["id"]

    async def logout(self):
        path = f"{LABS_API_PATH_BASE}/auth/logout"
        await self._call_labs_api_authenticated("POST", path)
        self.token = None

    @with_cache
    async def fetch_data(self, resource_type, slug_id, sub_resource="", skip=None):
        if sub_resource:
            sub_resource = f"/{sub_resource}"

        path = f"{LABS_API_PATH_BASE}/{resource_type}/{slug_id}{sub_resource}"
        return await self._fetch_resource(path, skip=skip)

    async def paginate(self, func, key):
        skip = 0
        while True:
            page = await func(skip=skip)
            # flatten the pages
            for item in page[key]:
                yield item

            pagination = page.pagination
            if pagination.lastPage:
                break
            skip += pagination.limit

    @with_cache
    async def fetch_content(self, slug_id, content_type):
        # not LABS_API base for embed queries
        path = f"/embed/{slug_id}/{content_type}"

        logger.debug(f"LABS EMBED {path}")

        r = await self._call_labs_api_authenticated("GET", path)
        return r.text

    @with_cache
    async def fetch_events(self, skip=None, **params):
        path = f"{LABS_API_PATH_BASE}/events"
        return await self._fetch_resource(path, params=params, skip=skip)

    async def _fetch_resource(self, path, *, params=None, skip=None):
        logger.debug(f"LABS {path} params={params} skip={skip}")

        if not params:
            params = {}

        params.update(LABS_API_COMMON_PARAMS)
        if skip is not None:
            params.update(skip=skip)

        r = await self._call_labs_api_authenticated("GET", path, params=params)

        d = Addict(r.json())
        deep_freeze(d)
        return d

    async def _call_labs_api_authenticated(
        self, method, path, headers=None, params=None, **kwargs
    ):
        # ~common base path + params set in caller: some calls (embed) to the Labs API
        # do not have them
        auth = {"Authorization": f"Bearer {self.token}"}
        r = await self._call_authenticated(
            self.labs_api_session,
            method,
            path,
            auth,
            headers,
            params,
            connection_timeout=self.connection_timeout,
            timeout=self.labs_api_default_timeout,
            **kwargs,
        )

        return r

    async def _call_legacy_api_authenticated(
        self, method, path, headers=None, params=None, **kwargs
    ):
        auth = {"authorization": self.token}
        if not headers:
            headers = LEGACY_API_COMMON_HEADERS
        else:
            headers = {**LEGACY_API_COMMON_HEADERS, **headers}

        path = f"{LEGACY_API_PATH_BASE}{path}"

        r = await self._call_authenticated(
            self.legacy_api_session,
            method,
            path,
            auth,
            headers,
            params,
            connection_timeout=self.connection_timeout,
            timeout=self.legacy_api_default_timeout,
            **kwargs,
        )

        return r

    async def _call_authenticated(
        self, session, method, path, auth, headers=None, params=None, **kwargs
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

    async def fetch_follows(self):
        path = "/users/me"
        # filter for only novels, exclude manga
        qfilter = {"include": [{"serieFollows": "serie"}]}
        payload = {"filter": json.dumps(qfilter)}

        r = await self._call_legacy_api_authenticated("GET", path, params=payload)
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
        verb = "PUT" if is_follow else "DELETE"
        path = f"{LABS_API_PATH_BASE}/me/follow/{series_id}"

        logger.debug(f"FOLLOW {verb} {path}")

        r = await self._call_labs_api_authenticated(verb, path)
        r.raise_for_status()

    @with_cache
    async def fetch_url(self, url: str):
        if not url.startswith(CDN_IMG_URL_BASE):
            raise InvalidCDNRequestException(
                f"{url} doesn't start with {CDN_IMG_URL_BASE}"
            )

        # for CDN images
        logger.debug(f"IMAGE {url}")
        r = await self.cdn_session.get(
            url=url,
            connection_timeout=self.connection_timeout,
            timeout=self.cdn_default_timeout,
        )
        r.raise_for_status()
        # should be JPEG
        # TODO check ?
        return r.content

    @with_cache
    async def fetch_jnc_webpage(self, series_slug):
        url = jncweb.url_from_series_slug(series_slug)
        logger.debug(f"JNCWEB {url}")
        r = await self.jncweb_session.get(
            url=url,
            connection_timeout=self.connection_timeout,
            timeout=self.jncweb_default_timeout,
        )
        r.raise_for_status()
        return r.text
