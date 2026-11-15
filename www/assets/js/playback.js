/* Download and decode the whole sequence before allowing local playback. */
window.SpherexPlayback = (() => {
    let frames = [];
    let index = 0;
    let timer = null;
    let rate = 2;
    let controller = null;
    let imageElement;
    let labelElement;
    const MAX_BYTES = 128 * 1024 * 1024; // Include decoded pixel memory.

    function pause() {
        clearInterval(timer);
        timer = null;
    }

    function release(items) {
        for (const item of items) URL.revokeObjectURL(item.url);
    }

    function show() {
        if (!frames.length) return;
        const frame = frames[index];
        // Reuse the already decoded <img>, avoiding decode/fetch on frame changes.
        imageElement.replaceChildren(frame.image);
        labelElement.textContent = `${index + 1} / ${frames.length} — ${frame.date || ''}`;
        if (frame.example) labelElement.textContent += ' — Example data';
    }

    function step(offset) {
        if (!frames.length) return;
        index = (index + offset + frames.length) % frames.length;
        show();
    }

    function play() {
        pause();
        if (frames.length) timer = setInterval(() => step(1), 1000 / rate);
    }

    function setRate(value) {
        rate = Math.max(1, Math.min(30, Number(value) || 2));
        if (timer !== null) play();
    }

    async function load(items, imageId, labelId) {
        pause();
        if (controller) controller.abort();
        const current = new AbortController();
        controller = current;
        release(frames);
        frames = [];
        imageElement = document.getElementById(imageId);
        labelElement = document.getElementById(labelId);
        imageElement.replaceChildren();
        const loaded = new Array(items.length);
        let next = 0;
        let completed = 0;
        let bytes = 0;
        let failure = null;
        const timeout = setTimeout(() => current.abort(), 120000);

        async function worker() {
            while (next < items.length && !current.signal.aborted) {
                const position = next++;
                const frame = items[position];
                let url;
                try {
                    const response = await fetch(frame.src, {signal: current.signal});
                    if (!response.ok) throw new Error(`Frame ${position + 1} failed to load (${response.status}).`);
                    if (!response.headers.get('Content-Type')?.startsWith('image/')) {
                        throw new Error(`Frame ${position + 1} is not an image.`);
                    }
                    const blob = await response.blob();
                    bytes += blob.size;
                    if (bytes > MAX_BYTES) throw new Error('Sequence is too large. Choose a shorter date range.');
                    url = URL.createObjectURL(blob);
                    const image = new Image();
                    image.src = url;
                    await image.decode();
                    if (current.signal.aborted) throw new Error('Loading cancelled or timed out.');
                    bytes += image.naturalWidth * image.naturalHeight * 4;
                    if (bytes > MAX_BYTES) throw new Error('Sequence is too large. Choose a shorter date range.');
                    image.style.width = '100%';
                    image.style.display = 'block';
                    image.alt = `SPHEREx frame ${position + 1}`;
                    loaded[position] = {...frame, url, image,
                        example: response.headers.get('X-SPHEREx-Source') === 'example'};
                    url = null; // Ownership passes to loaded[].
                    completed++;
                    labelElement.textContent = `Loading images… ${completed} / ${items.length}`;
                } catch (error) {
                    if (url) URL.revokeObjectURL(url);
                    failure ||= error;
                    current.abort();
                }
            }
        }

        // Bound concurrent renders on the server, preserving manifest order.
        await Promise.all(Array.from({length: Math.min(3, items.length)}, worker));
        clearTimeout(timeout);
        if (current.signal.aborted || failure) {
            release(loaded.filter(Boolean));
            return {error: failure?.message || 'Loading cancelled or timed out.'};
        }
        frames = loaded;
        index = 0;
        show();
        return {count: frames.length, example: frames.some(frame => frame.example)};
    }

    window.addEventListener('pagehide', () => {
        pause();
        if (controller) controller.abort();
        release(frames);
        frames = [];
    });

    return {load, play, pause, step, setRate};
})();
