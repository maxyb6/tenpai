// Minimal service worker so the officer view is installable. Network only for
// now; the offline visit queue is designed for but not built in the demo.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
