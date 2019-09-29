from __future__ import absolute_import

from cachetools import Cache

import collections

try:
    from time import monotonic as default_timer
except ImportError:
    from time import time as default_timer


class _Link(object):

    __slots__ = ('key', 'expire', 'next', 'prev')

    def __init__(self, key=None, expire=None):
        self.key = key
        self.expire = expire

    def __reduce__(self):
        return _Link, (self.key, self.expire)

    def unlink(self):
        next = self.next
        prev = self.prev
        prev.next = next
        next.prev = prev


class _Timer(object):

    def __init__(self, timer):
        self.__timer = timer
        self.__nesting = 0

    def __call__(self):
        if self.__nesting == 0:
            return self.__timer()
        else:
            return self.__time

    def __enter__(self):
        if self.__nesting == 0:
            self.__time = time = self.__timer()
        else:
            time = self.__time
        self.__nesting += 1
        return time

    def __exit__(self, *exc):
        self.__nesting -= 1

    def __reduce__(self):
        return _Timer, (self.__timer,)

    def __getattr__(self, name):
        return getattr(self.__timer, name)


class AccessRefreshedTTLCache(Cache):
    """LRU Cache implementation with per-item time-to-live (TTL) value.
    TTL is refreshed every time element is accessed, as well as when a key is set again after expiry or if it is new key.
    Setting a value of an existing unexpired key doesn't refresh its TTL.
    You can also perform an action when elements expire by specifying expiry_callback(list_of_expired_keys) function.
    """

    def __init__(self, maxsize, ttl, expiry_callback=None, timer=default_timer, getsizeof=None):
        Cache.__init__(self, maxsize, getsizeof)
        self.__root = root = _Link()
        root.prev = root.next = root
        self.__links = collections.OrderedDict()
        self.__timer = _Timer(timer)
        self.__ttl = ttl
        self.__expiry_callback = expiry_callback

    def __contains__(self, key):
        try:
            link = self.__links[key]  # no reordering
        except KeyError:
            return False
        else:
            return not (link.expire < self.__timer())

    def __getitem__(self, key, cache_getitem=Cache.__getitem__):
        try:
            link = self.__getlink(key)
        except KeyError:
            exists = False
            expired = False
        else:
            exists = True
            expired = link.expire < self.__timer()
        if expired:
            return self.__missing__(key)
        else:
            if exists:
                link.unlink()
                link.expire = self.__timer() + self.__ttl
                link.next = root = self.__root
                link.prev = prev = root.prev
                prev.next = root.prev = link
            return cache_getitem(self, key)

    def __setitem__(self, key, value, cache_setitem=Cache.__setitem__):
        self.expire()
        cache_setitem(self, key, value)
        try:
            link = self.__getlink(key)
        except KeyError:
            self.__links[key] = link = _Link(key)
        else:
            link.unlink()

        if link.expire is None:
            link.expire = self.__timer() + self.__ttl
        link.next = root = self.__root
        link.prev = prev = root.prev
        prev.next = root.prev = link

    def __delitem__(self, key, cache_delitem=Cache.__delitem__):
        cache_delitem(self, key)
        link = self.__links.pop(key)
        link.unlink()
        if link.expire < self.__timer():
            raise KeyError(key)

    def __iter__(self):
        root = self.__root
        curr = root.next
        while curr is not root:
            # "freeze" time for iterator access
            with self.__timer as time:
                if not (curr.expire < time):
                    yield curr.key
            curr = curr.next

    def __len__(self):
        root = self.__root
        curr = root.next
        time = self.__timer()
        count = len(self.__links)
        while curr is not root and curr.expire < time:
            count -= 1
            curr = curr.next
        return count

    def __setstate__(self, state):
        self.__dict__.update(state)
        root = self.__root
        root.prev = root.next = root
        for link in sorted(self.__links.values(), key=lambda obj: obj.expire):
            link.next = root
            link.prev = prev = root.prev
            prev.next = root.prev = link
        self.expire(self.__timer())

    def __repr__(self, cache_repr=Cache.__repr__):
        with self.__timer as time:
            self.expire(time)
            return cache_repr(self)

    @property
    def currsize(self):
        with self.__timer as time:
            self.expire(time)
            return super(GetRefreshedTTLCache, self).currsize

    @property
    def timer(self):
        """The timer function used by the cache."""
        return self.__timer

    @property
    def ttl(self):
        """The time-to-live value of the cache's items."""
        return self.__ttl

    def expire(self, time=None):
        """Remove expired items from the cache."""
        if time is None:
            time = self.__timer()
        root = self.__root
        curr = root.next
        links = self.__links
        cache_delitem = Cache.__delitem__
        deleted_items = []
        while curr is not root and curr.expire < time:
            cache_delitem(self, curr.key)
            deleted_items.append(curr.key)
            del links[curr.key]
            next = curr.next
            curr.unlink()
            curr = next

        if self.__expiry_callback is not None and len(deleted_items) > 0:
            self.__expiry_callback(deleted_items)

    def clear(self):
        with self.__timer as time:
            self.expire(time)
            Cache.clear(self)

    def get(self, *args, **kwargs):
        with self.__timer:
            return Cache.get(self, *args, **kwargs)

    def pop(self, *args, **kwargs):
        with self.__timer:
            return Cache.pop(self, *args, **kwargs)

    def setdefault(self, *args, **kwargs):
        with self.__timer:
            return Cache.setdefault(self, *args, **kwargs)

    def popitem(self):
        """Remove and return the `(key, value)` pair least recently used that
        has not already expired.
        """
        with self.__timer as time:
            self.expire(time)
            try:
                key = next(iter(self.__links))
            except StopIteration:
                raise KeyError('%s is empty' % self.__class__.__name__)
            else:
                return (key, self.pop(key))

    if hasattr(collections.OrderedDict, 'move_to_end'):
        def __getlink(self, key):
            value = self.__links[key]
            self.__links.move_to_end(key)
            return value
    else:
        def __getlink(self, key):
            value = self.__links.pop(key)
            self.__links[key] = value
            return value




