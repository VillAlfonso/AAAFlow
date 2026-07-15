# composition — fern study (MEASURED, not guessed)

Evidence: 584 shots across 5 videos, each read against the exact narration
spoken over it (`app/composer_analysis.py`), plus the whole-film arc.
This REPLACES the earlier hand-guessed version, which was wrong in the way
that matters most.

## THE HEADLINE: fern is an EVIDENCE channel, not a reconstruction channel

What is actually on screen, across 584 shots:

| device | share |
|---|---|
| archival video | 23% |
| screenshots (chats, forums, posts, articles) | 22% |
| documents (records, filings, letters) | 18% |
| **3D mannequin reconstruction** | **16%** |
| archival photos | 7% |
| talking heads | 5% |

**The mannequins are a garnish, not the meal.** A channel built as 100%
reconstruction copies the most visually distinctive sixth of fern and throws
away the five sixths that carry the documentary weight. That mistake is what
made our first Fathom board feel hollow: pretty dioramas of nothing, proving
nothing.

## THE SECOND HEADLINE: they rarely draw what the line says

How the picture answers the words:

| relation | share | meaning |
|---|---|---|
| **evidence** | **35%** | the picture PROVES the claim (a document, a screenshot, a record) |
| **context** | **33%** | the wider place, time or scale around the line |
| literal | 19% | the picture shows the thing the line names |
| metaphor | 13% | it stands in for an abstract idea |
| reaction | 1% | aftermath |

Only **19%** of shots are literal. Our board was almost entirely literal —
"the line says a coin, draw a coin". Fern answers a claim with a RECEIPT.

## THE COMPOSER LOOKUP (what each KIND of line gets shown)

| the line is… | fern shows |
|---|---|
| an event / action | **evidence/document** or **evidence/screenshot** (by far the most common pairing) |
| a person | **evidence/screenshot** (their post, profile, record), then context/archival |
| a number or claim | **context/archival-video** or **evidence/screenshot** |
| an explanation | **context/talking-head** or context/document |
| a quote / speech | **context/talking-head** or the document it came from |
| a date or time | evidence/screenshot, or a literal b-roll beat |
| an abstraction | evidence/screenshot, or context/archival |

Rule: **when in doubt, show the proof, not the picture.**

## THE ARC (the whole film, not the scene)

Measured on both long videos:

1. **Opening — fastest cutting (16-21 cuts/min).** Screenshots and archival,
   relations skew metaphor + evidence. A montage barrage: hook first, orient
   second.
2. **Middle — SLOWS to 12-14 cuts/min, and turns to CONTEXT (up to 57%).**
   This is where reconstruction (the mannequins) actually appears — they are
   building a world, not proving a point. Documents run alongside.
3. **Long holds of 20-41 seconds**, placed deep in the middle. Uncut evidence:
   a recorded call, a document, footage allowed to play. The pace has room
   because the cutting slowed.
4. **Close — picks back up (14-15 cuts/min), returns to context + evidence.**
   Almost never literal. One video lifts metaphor to 32% at the end, as the
   argument generalises past the story.

## WHAT THIS MEANS FOR OUR PIPELINE

Target media budget for a Fathom video (mirroring fern, within what we can
lawfully source):

| device | target | how WE make it |
|---|---|---|
| evidence: documents + screenshots | **~40%** | `playwright` screenshots of public records, court filings, government pages; `receipts.py` float-in + highlight sweep on the spoken word |
| context: archival photos / footage | **~20%** | `archival.py` (Wikimedia PD/CC, US government works — public domain) |
| reconstruction (mannequins) | **~25%** | Wan t2v + the fern LoRA — reserved for the MIDDLE, for what cannot be filmed |
| typeset cards / maps | **~15%** | Remotion (SegmentCard, DateChip, ArrowCallout) + the overlay director |

**Copyright reality (be honest about this):** fern uses copyrighted news
footage and photos under fair-use commentary. We should NOT auto-scrape that.
Our safe evidence lanes are: US government works (court records, DOJ/FBI
filings — public domain), Wikimedia PD/CC, and our own screenshots of public
web pages for commentary. That is enough to build an evidence-led video; it
is not enough to clone their archival cut, and we should not try.
