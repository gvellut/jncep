from __future__ import annotations

from collections import defaultdict
from enum import Enum, auto

import attr


class AltOrigin(Enum):
    JNC_MAIN = auto()
    JNC_NINA = auto()

    def __str__(self):
        return ALT_CONFIGS[self].DISPLAY_NAME


# TODO lower case
@attr.s
class AltConfig:
    ORIGIN = attr.ib()
    DISPLAY_NAME = attr.ib()

    API_URL_BASE = attr.ib()
    API_PATH_BASE = attr.ib()
    EMBED_PATH_BASE = attr.ib()
    CDN_IMG_URL_BASE = attr.ib()

    WEB_URL_BASE = attr.ib()


JNC_MAIN_CONFIG = AltConfig(
    ORIGIN=AltOrigin.JNC_MAIN,
    DISPLAY_NAME="J-Novel Club",
    API_URL_BASE="https://labs.j-novel.club",
    API_PATH_BASE="/app/v2",
    EMBED_PATH_BASE="/embed/v2",
    # multiple URLs possible (after v2 update October 2024)
    CDN_IMG_URL_BASE=[
        "https://cdn.j-novel.club",
        "https://d2dq7ifhe7bu0f.cloudfront.net",
    ],
    WEB_URL_BASE="https://j-novel.club",
)

# after main Labs API v2 update October 2024 => properties very similar to Nina API
JNC_NINA_CONFIG = AltConfig(
    ORIGIN=AltOrigin.JNC_NINA,
    DISPLAY_NAME="JNC Nina",
    API_URL_BASE="https://api.jnc-nina.eu",
    API_PATH_BASE="/app/v2",
    EMBED_PATH_BASE="/embed/v2",
    CDN_IMG_URL_BASE="https://cdn.jnc-nina.eu",
    WEB_URL_BASE="https://jnc-nina.eu",
)


ALT_CONFIGS: dict[AltOrigin, AltConfig] = {
    AltOrigin.JNC_MAIN: JNC_MAIN_CONFIG,
    AltOrigin.JNC_NINA: JNC_NINA_CONFIG,
}


class AltOriginError(Exception):
    pass


@attr.s
class AltCredentials:
    # contains mapping : origin => tuple (email, pw)
    credential_mapping: dict = attr.ib()

    def get_credentials(self, origin: AltOrigin):
        # just the login, pw tuple
        if credentials := self.credential_mapping.get(origin):
            return credentials

        raise AltOriginError(f"No credential for: {origin}")

    def origins_with_credentials(self):
        return list(self.credential_mapping.keys())

    def extract_for_origin(self, origin):
        # as if only the login, pw for the orign had been passed
        mapping = {origin: self.get_credentials(origin)}
        credentials = AltCredentials(mapping)
        return credentials


def find_origin(url: str):
    for origin, config in ALT_CONFIGS.items():
        if url.startswith(config.WEB_URL_BASE):
            return origin

    # TODO better message
    raise AltOriginError(f"Unknown origin for URL: {url}")


def get_alt_config_for_origin(origin: AltOrigin):
    return ALT_CONFIGS[origin]


async def call_for_each_origin(
    credentials: AltCredentials, func, tracked_series, only_with_credentials=True
):
    tracked_series_origin = split_by_origin(tracked_series)

    if only_with_credentials:
        origins = credentials.origins_with_credentials()
    else:
        # so error if try to login using an origin without credentials
        origins = list(tracked_series_origin.keys())

    # TODO instead of sequential : use tasks + bag : but need to change the output
    # since only one status line (updated) + confusing to read the interleaved logs
    results = []
    # not a big deal if there is only one origin (unnecessary trio nursery)
    for origin in origins:
        alt_config = get_alt_config_for_origin(origin)

        result = await func(
            alt_config,
            tracked_series_origin[origin],
        )
        results.append(result)

    tracked_series = _merge_from_origins(tracked_series_origin)

    return results, tracked_series


def split_by_origin(t):
    t_split = defaultdict(dict)
    for url, v in t.items():
        # TODO catch or assume the tracked series all have correct origin ?
        origin = find_origin(url)
        t_split[origin][url] = v

    return t_split


def merge_single_origin(t_split, origin, tracked_series_for_origin):
    t_split[origin] = tracked_series_for_origin
    _merge_from_origins(t_split)


def _merge_from_origins(t_split):
    t = {}
    for track_series in t_split.values():
        t.update(track_series)
    return t
