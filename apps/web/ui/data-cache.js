"use strict";

window.AgenticOs = window.AgenticOs || {};

(function initDataCache(Ao) {
  const cache = new Map();
  const inflight = new Map();

  async function get(key, loader, ttlMs = 1000) {
    const now = Date.now();
    const current = cache.get(key);
    if (current && now - current.createdAt <= ttlMs) {
      return current.value;
    }
    if (inflight.has(key)) {
      return inflight.get(key);
    }
    const request = Promise.resolve(loader())
      .then((value) => {
        cache.set(key, { value, createdAt: Date.now() });
        return value;
      })
      .finally(() => inflight.delete(key));
    inflight.set(key, request);
    return request;
  }

  function invalidate(prefix = "") {
    for (const key of cache.keys()) {
      if (key.startsWith(prefix)) {
        cache.delete(key);
      }
    }
  }

  Ao.DataCache = { get, invalidate };
})(window.AgenticOs);
