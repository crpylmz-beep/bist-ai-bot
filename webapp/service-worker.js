'use strict';
// No offline HTML/data caching: stale market data must not look live.
self.addEventListener('push', event => {
    let message;
    try { message = event.data.json(); } catch (_) { return; }
    const stock = /^\/\?stock=[A-Z0-9]{2,12}$/.test(message.url || '') ? message.url : '/';
    event.waitUntil(self.registration.showNotification(message.title || 'BIST Asistanı', {
        body: message.body || '', tag: message.id, renotify: false,
        icon: '/icon.svg', data: {url: stock}
    }));
});
self.addEventListener('notificationclick', event => {
    event.notification.close();
    const path = event.notification.data?.url;
    const url = new URL(/^\/\?stock=[A-Z0-9]{2,12}$/.test(path || '') ? path : '/', self.location.origin).href;
    event.waitUntil((async () => {
        const windows = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
        for (const client of windows) {
            if (new URL(client.url).origin === self.location.origin) {
                await client.navigate(url);
                return client.focus();
            }
        }
        return self.clients.openWindow(url);
    })());
});
