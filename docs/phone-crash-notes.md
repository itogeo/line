# Phone crashes: where to look

Reported 2026-11-21: the map crashes on a phone. This is a read of the code on
2026-11-21, not a measurement. Nothing here was tested on a device. Line
numbers are for `main` on that date and will drift.

Memory figures are estimates: decoded size = width x height x 4 bytes. The
per-date chunk images are not in git, so their real dimensions were not
measured. Each map's `snowline.json` reports 12,000,000 imaged pixels for a
full chunk, which is about 48 MB decoded if the image is that size.

## Likely causes, most likely first

1. **Twelve large images load at boot.** The Photo toggle starts checked
   (`index.html:806`), so `updateTileLayers` (`index.html:3636`) adds 6
   true-colour and 6 snow image sources at once. About 576 MB decoded by the
   estimate above. No phone guard exists: `isMobile()` (`index.html:3356`) only
   changes layout.
2. **True colour is also prefetched.** `index.html:3579-3582` creates an
   `Image()` for every true-colour chunk on each date load, although the comment
   at `index.html:3551-3553` says it is not fetched eagerly.
3. **Recent and latest views stack true colour from every source pass.**
   `stackCompositeImagery` (`index.html:3679-3702`) adds up to 6 chunks per pass
   in the 10-day window.
4. **The forest mask loads at boot with its toggle off.** `addForestLayer()`
   (`index.html:1951`, source at `:4084`) adds a 4000x2823 image, about 45 MB
   decoded.
5. **Tapping for a spot's history decodes a whole snow tile per pass**, four at
   a time, over every pass of the season (`spotClass`, `index.html:2099-2115`,
   loop at `:2250`).
6. **3D terrain** drapes all of the above over 512 px elevation tiles, pitch up
   to 85 (`maxPitch` at `index.html:949`, terrain at `:1831-1841`).
7. **`terrain.html` allocates roughly 250 MB** of canvases and typed arrays for
   the 3600x2784 class image (`terrain.html:260-312`), and another full-size
   `ImageData` on each selection (`:426`).
8. **`range.html` adds up to 12 image sources** for the chunks that overlap the
   zone (`range.html:587-596`).
9. **No pixel-ratio or antialias cap.** `index.html:942-952` creates the map
   with `antialias: true`.

Probably not the cause: date changes remove their layers before adding new ones
(`index.html:3562-3567`); `wind.js` only makes 32 px canvases; boot JSON is about
2 to 3 MB in total.

## Quickest check

Open the page on the phone with remote inspection (Safari Web Inspector or
Chrome DevTools) and watch memory while turning Photo off. If items 1 to 3 are
the cause, memory should fall sharply.
