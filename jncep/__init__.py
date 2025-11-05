__version__ = "55"

# fix some issue with methods not present on some system (PyDroid)
# not actually used by jncep but import error
import socket

# not used so doesn't matter, just that the names are importable
socket.if_nametoindex = None
socket.if_indextoname = None
