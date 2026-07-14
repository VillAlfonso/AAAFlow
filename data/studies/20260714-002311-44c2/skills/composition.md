# composition — fern study (what fills the screen)

## THE STYLE DNA (trigger: `3d mannequin documentary`)

The signature look, measured across 762 3D-render frames ("mannequin" is
the single most common subject word): **faceless matte humanoid MANNEQUIN
figures** — no faces, no clothing detail, smooth grey/white body forms —
acting out reconstructions inside stylized 3D environments. Dark low-key
lighting, deep shadows, and ONE red rim-light or accent per frame.
Surveillance framings recur (REC overlays, thermal/night-vision, CCTV
angles), as do miniature diorama city models and red-on-black data maps.
Real archival footage, documents and screenshots are cut in between.

This is why the channel can reconstruct ANY event without deepfaking a real
person: mannequins are deliberately anonymous. Use them for every human
reenactment. Real people appear only as archival photos/footage.

Every image and clip prompt on this channel leads with the trigger phrase
`3d mannequin documentary` (it is also the channel's style_suffix and the
LoRA's trained trigger).


Measured media mix across 5,002 VLM-tagged frames:

| media | share (range across videos) |
|---|---|
| live-footage (real/archival/reenactment) | 20-45% |
| screenshot (documents, chats, articles, terminals) | 10-40% |
| 3d-render (maps, reconstructions, device models) | 12-22% |
| typeset-card (name tags, date stamps, labels) | 5-15% |
| talking-head (interviews, hearings) | 0-25% (815f-heavy) |
| real-photo (portraits, case photos) | 3-10% |
| map | 1-5% (but signature: bc3b is built ON one) |

On-screen text share: **75-91% of frames** — near-constant utilitarian
typesetting: name+role tags on people, location+date stamps on scene
changes, evidence labels on documents, map annotations.

## The five moves (with executors)

1. **The reconstruction**: a 3D map/space the camera moves through while
   labels pin actors and distances (bc3b's whole spine). Ours: Wan t2v
   clip of the space + Remotion ArrowCallout/typeset labels.
2. **The document dive**: real screenshot/paper, camera pushes slowly, a
   highlight or label lands on the key line as narration reads it. Ours:
   receipts machinery + archival fetcher.
3. **The identity card**: first mention of any person = their real photo
   (or silhouette when unknown) + typeset name/role tag. Ours: ref cards
   with real archival photos, label mandatory.
4. **The atmosphere shot**: a held location/mood clip with NO text, under
   music, buying breathing room between chapters. Ours: Wan t2v, no
   overlays, part of the 17-30% no-speech air.
5. **The stamp**: chapter/date/location typeset card on a dark or plain
   frame at every time jump (fade + stamp together). Ours: Remotion
   SegmentCard.

Rule: NEVER two consecutive scenes from the same media class unless inside
a document dive or reconstruction sequence. The mix IS the look.
Everything visual is evidence-flavored: if a generated shot could not
plausibly be footage, a document, or a reconstruction, reframe it so it
could.
