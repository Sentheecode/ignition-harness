"""Adapter errors. The public message is a kind code, never a URL or header value."""


class AdapterError(Exception):
    def __init__(self, kind, status=None):
        super().__init__(kind)
        self.kind = kind
        self.status = status
