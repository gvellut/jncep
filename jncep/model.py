import attr


@attr.s
class Series:
    raw_data = attr.ib()
    series_id = attr.ib()
    volumes = attr.ib(None)


@attr.s
class Volume:
    raw_data = attr.ib()
    volume_id = attr.ib()
    num = attr.ib()
    parts = attr.ib(None)
    is_analyzed = attr.ib(False)
    cover = attr.ib(None)
    series = attr.ib(None)
    parts_count = attr.ib(None)


@attr.s
class Part:
    raw_data = attr.ib()
    part_id = attr.ib()
    num_in_volume = attr.ib()
    volume = attr.ib(None)
    series = attr.ib(None)
    content = attr.ib(None)
    images = attr.ib(None)

    epub_content = attr.ib(None)


@attr.s
class Image:
    url = attr.ib()
    content = attr.ib(None)
    part = attr.ib(None)
    local_filename = attr.ib(None)

    order_in_part = attr.ib(None)
