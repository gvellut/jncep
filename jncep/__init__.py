__version__ = "51"

# fix some issue with methods not present on some system (PyDroid)
# not actually used by jncep but import error
import socket


def if_nametoindex(_):
    raise OSError("not implemented")


def if_indextoname(_):
    raise OSError("not implemented")


if not hasattr(socket, "if_nametoindex"):
    socket.if_nametoindex = if_nametoindex
if not hasattr(socket, "if_indextoname"):
    socket.if_indextoname = if_indextoname
