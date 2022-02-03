import attr


@attr.s
class Series:
    raw_data = attr.ib()
    volumes = attr.ib(None)


@attr.s
class Volume:
    raw_data = attr.ib()
    volume_id = attr.ib()
    num = attr.ib()
    parts = attr.ib(None)
    is_dl = attr.ib(False)


@attr.s
class Part:
    raw_data = attr.ib()
    volume = attr.ib()
    part_id = attr.ib()
    num_in_volume = attr.ib()
    content = attr.ib(None)
    images = attr.ib(None)
    is_dl = attr.ib(False)

    pub_content = attr.ib(None)


@attr.s
class Image:
    url = attr.ib()
    part = attr.ib()
    content = attr.ib(None)
    local_filename = attr.ib(None)

    order_in_part = attr.ib(None)
    # TODO for the cover
    dimensions = attr.ib(None)
