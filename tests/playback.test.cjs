const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');

const source = readFileSync('www/assets/js/playback.js', 'utf8');

function browser({fetchImage, decode, width = 10} = {}) {
    const calls = [];
    const revoked = [];
    const intervals = new Map();
    const listeners = {};
    const elements = {
        image: {replaceChildren(...children) {this.children = children;}},
        label: {textContent: ''},
    };
    let serial = 0;
    const window = {addEventListener(name, handler) {listeners[name] = handler;}};
    vm.runInNewContext(source, {
        window,
        document: {getElementById(id) {return elements[id];}},
        fetch: async (url, options) => {
            calls.push(url);
            return fetchImage ? fetchImage(url, options) : new Response('png', {
                headers: {'Content-Type': 'image/png'},
            });
        },
        AbortController,
        URL: {createObjectURL() {return `blob:${++serial}`;}, revokeObjectURL(url) {revoked.push(url);}},
        Image: class {
            constructor() {this.style = {}; this.naturalWidth = width; this.naturalHeight = width;}
            async decode() {if (decode) await decode();}
        },
        setInterval(fn, milliseconds) {const id = ++serial; intervals.set(id, {fn, milliseconds}); return id;},
        clearInterval(id) {intervals.delete(id);},
        setTimeout() {return ++serial;},
        clearTimeout() {},
    });
    return {player: window.SpherexPlayback, calls, revoked, intervals, elements, listeners};
}

const frames = Array.from({length: 5}, (_, i) => ({src: `/frame/${i}`, date: `date-${i}`}));

test('loads every frame with bounded concurrency and waits for decode before playback', async () => {
    let active = 0;
    let peak = 0;
    let decoded = 0;
    const b = browser({
        fetchImage: async () => {
            peak = Math.max(peak, ++active);
            await new Promise(setImmediate);
            active--;
            return new Response('png', {headers: {'Content-Type': 'image/png'}});
        },
        decode: async () => {await new Promise(setImmediate); decoded++;},
    });
    const ready = b.player.load(frames, 'image', 'label');
    b.player.play();
    assert.equal(b.intervals.size, 0);
    assert.equal((await ready).count, frames.length);
    assert.equal(decoded, frames.length);
    assert.equal(peak, 3);
    assert.equal(b.calls.length, frames.length);
    assert.match(b.elements.label.textContent, /^1 \/ 5 — date-0$/);
});

test('playback, seek, wrap, and rate changes reuse decoded images without requests', async () => {
    const b = browser();
    await b.player.load(frames, 'image', 'label');
    const firstImage = b.elements.image.children[0];
    b.player.step(-1);
    assert.match(b.elements.label.textContent, /5 \/ 5 — date-4/);
    b.player.play();
    b.intervals.values().next().value.fn();
    assert.equal(b.elements.image.children[0], firstImage);
    b.player.setRate(10);
    assert.equal(b.intervals.size, 1);
    assert.equal(b.intervals.values().next().value.milliseconds, 100);
    b.player.pause();
    assert.equal(b.intervals.size, 0);
    assert.equal(b.calls.length, frames.length);
});

test('failed download prevents partial playback and releases loaded images', async () => {
    const b = browser({fetchImage: async url => {
        if (url.endsWith('/4')) return new Response('unavailable', {status: 502});
        return new Response('png', {headers: {'Content-Type': 'image/png'}});
    }});
    const result = await b.player.load(frames, 'image', 'label');
    assert.match(result.error, /502/);
    assert.ok(b.revoked.length > 0);
    b.player.play();
    assert.equal(b.intervals.size, 0);
    assert.equal(b.elements.image.children.length, 0);
});

test('rejects non-image responses and decode failures', async () => {
    const b = browser({fetchImage: async () => new Response('html')});
    assert.match((await b.player.load(frames, 'image', 'label')).error, /not an image/);
    const corrupt = browser({decode: async () => {throw new Error('Corrupt image');}});
    assert.match((await corrupt.player.load(frames, 'image', 'label')).error, /Corrupt image/);
    assert.equal(corrupt.revoked.length, 3);
});

test('replacement and page exit release browser resources', async () => {
    const b = browser();
    await b.player.load(frames, 'image', 'label');
    await b.player.load(frames.slice(0, 2), 'image', 'label');
    assert.equal(b.revoked.length, 5);
    b.player.play();
    b.listeners.pagehide();
    assert.equal(b.revoked.length, 7);
    assert.equal(b.intervals.size, 0);
});

test('image-level fallback remains visible to the UI', async () => {
    const b = browser({fetchImage: async () => new Response('png', {
        headers: {'Content-Type': 'image/png', 'X-SPHEREx-Source': 'example'},
    })});
    assert.equal((await b.player.load(frames, 'image', 'label')).example, true);
    assert.match(b.elements.label.textContent, /Example data/);
});

test('decoded memory limit stops oversized sequences', async () => {
    const b = browser({width: 10000});
    assert.match((await b.player.load(frames, 'image', 'label')).error, /shorter date range/);
    assert.ok(b.revoked.length > 0);
    b.player.play();
    assert.equal(b.intervals.size, 0);
});
