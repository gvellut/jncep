from functools import wraps
import json
import logging

from addict import Dict as Addict
import httpx
import trio

from . import utils
from .utils import deep_freeze

logger = logging.getLogger(__name__)
console = utils.getConsole()

API_COMMON_PARAMS = {"format": "json"}
API_COMMON_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
}

logging.getLogger("httpx").disabled = True


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


async def paginate(func, key):
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


class JNC_API:
    def __init__(
        self,
        config,
        *,
        api_connections=10,
        cdn_connections=20,
        api_default_timeout=20,
        cdn_default_timeout=30,
    ):
        self.config = config

        hooks = None
        if logging.getLogger("jncep").level == logging.DEBUG:

            async def log_request(request):
                logger.debug(
                    "HTTP Request: %s %s",
                    request.method,
                    request.url,
                )
                logger.debug(f"HTTP Request Headers: {request.headers}")

            async def log_response(response):
                logger.debug(
                    "HTTP Response: %s %d %s",
                    response.http_version,
                    response.status_code,
                    response.reason_phrase,
                )
                logger.debug(f"HTTP Response Headers: {response.headers}")

            hooks = {"request": [log_request], "response": [log_response]}

        timeout = httpx.Timeout(api_default_timeout, pool=None)
        self.api_session = httpx.AsyncClient(
            base_url=config.API_URL_BASE,
            limits=httpx.Limits(max_connections=api_connections),
            headers=API_COMMON_HEADERS,
            timeout=timeout,
            event_hooks=hooks,
        )

        # full URL always provided (CDN) so no need for base location parameter
        # also multiple URL possible
        timeout = httpx.Timeout(cdn_default_timeout, pool=None)
        self.cdn_session = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=cdn_connections),
            timeout=timeout,
            event_hooks=hooks,
        )

        self.token = None

    @property
    def is_logged_in(self):
        return self.token is not None

    async def login(self, email, password):
        path = f"{self.config.API_PATH_BASE}/auth/login"
        # slim: just the token, no cookie
        payload = {"login": email, "password": password, "slim": True}
        params = {**API_COMMON_PARAMS}

        r = await self.api_session.post(
            path, content=json.dumps(payload), params=params
        )
        r.raise_for_status()

        data = r.json()
        self.token = data["id"]

    async def logout(self):
        path = f"{self.config.API_PATH_BASE}/auth/logout"
        await self._call_authenticated("POST", path)
        self.token = None

    async def me(self):
        path = f"{self.config.API_PATH_BASE}/me"
        return await self.fetch_resource(path)

    @with_cache
    async def fetch_data(self, resource_type, slug_id, sub_resource="", skip=None):
        if sub_resource:
            sub_resource = f"/{sub_resource}"

        path = f"{self.config.API_PATH_BASE}/{resource_type}/{slug_id}{sub_resource}"
        return await self.fetch_resource(path, skip=skip)

    @with_cache
    async def fetch_content(self, slug_id, content_type):
        # not API base for embed queries
        path = f"{self.config.EMBED_PATH_BASE}/{slug_id}/{content_type}"

        logger.debug(f"API {self.config.ORIGIN} EMBED {path}")

        r = await self._call_authenticated("GET", path)
        return r.text

    @with_cache
    async def fetch_all_series(self, limit=500, skip=None):
        path = f"{self.config.API_PATH_BASE}/series"
        params = {"limit": limit}
        return await self.fetch_resource(path, params=params, skip=skip)

    @with_cache
    async def fetch_events(self, skip=None, **params):
        path = f"{self.config.API_PATH_BASE}/events"
        return await self.fetch_resource(path, params=params, skip=skip)

    @with_cache
    async def fetch_follows(self, skip=None):
        path = f"{self.config.API_PATH_BASE}/series"
        body = json.dumps({"only_follows": True})
        return await self.fetch_resource(path, "POST", body=body, skip=skip)

    async def fetch_resource(
        self, path, verb="GET", *, params=None, body=None, skip=None
    ):
        logger.debug(
            f"API {self.config.ORIGIN} {verb} {path} params={params} body={body} "
            + f"skip={skip}"
        )

        if not params:
            params = {}

        params.update(API_COMMON_PARAMS)
        if skip is not None:
            params.update(skip=skip)

        r = await self._call_authenticated(verb, path, params=params, body=body)

        d = Addict(r.json())
        deep_freeze(d)
        return d

    async def _call_authenticated(
        self,
        verb,
        path,
        *,
        headers=None,
        params=None,
        body=None,
        **kwargs,
    ):
        # ~common base path + params set in caller: some calls (embed) to the Labs API
        # do not have them

        auth = {"Authorization": f"Bearer {self.token}"}

        if not headers:
            headers = auth
        else:
            headers = {**auth, **headers}

        request = self.api_session.build_request(
            verb, path, headers=headers, params=params, content=body, **kwargs
        )
        r = await self.api_session.send(request)
        r.raise_for_status()

        return r

    async def follow_series(self, series_id):
        await self._set_follow(series_id, True)

    async def unfollow_series(self, series_id):
        await self._set_follow(series_id, False)

    async def _set_follow(self, series_id, is_follow):
        verb = "PUT" if is_follow else "DELETE"
        path = f"{self.config.API_PATH_BASE}/me/follow/{series_id}"

        logger.debug(f"FOLLOW {verb} {path}")

        r = await self._call_authenticated(verb, path)
        r.raise_for_status()

    @with_cache
    async def fetch_url(self, url: str):
        # used to access CDN images
        # no longer check the URL domain cf CDN_IMG_URL_BASE
        logger.debug(f"IMAGE {url}")
        r = await self.cdn_session.get(url)
        r.raise_for_status()
        # should be JPEG
        # TODO check ?
        # if code 200 and not JPEG, image will be broken or will not appear.
        # TODO try to read and print warning?
        return r.content


def _url_starts_with(url, choice_urls):
    if isinstance(choice_urls, str):
        choice_urls = [choice_urls]

    return any(url.startswith(choice_url) for choice_url in choice_urls)
