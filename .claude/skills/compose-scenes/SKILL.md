---
name: compose-scenes
description: Write image prompts that are specific, recognizable and varied, so a video never reads as generic AI slop. Load before writing or reviewing any storyboard's image_prompts.
---

# Composing scenes (the anti-boring rulebook)

User verdict that created this skill (2026-07-14): *"don't make the image
prompt so bland, actually have it be close and recognizable to what the
narrator is saying"* and *"what we are producing right now is boring."*

The failure it names: narration said "Barack Obama's account posts it. Then
Joe Biden's. Then Jeff Bezos and Bill Gates," and the prompt said *"a grid of
glowing screens showing an abstract social feed."* Four of the most
recognizable people alive, rendered as **wallpaper**. That is slideshow
filler, and it is the difference between a video someone watches and one they
scroll past.

## LAW 1 — Name the thing. Never write the generic noun.

If the line names a person, a company, a place or an object, the picture
shows THAT one, close enough to recognize.

| bland (banned) | specific (do this) |
|---|---|
| "a person at a desk" | "a mannequin in a hoodie hunched at a cluttered bedroom desk, three monitors, energy drink cans" |
| "a grid of screens" | "four mannequins at podiums: one tall in a dark suit, one in aviator sunglasses, one bald in a puffer vest, one in a v-neck sweater and glasses" |
| "abstract network nodes" | "a wall of employee profile photos, red lines connecting three of them" |
| "coins on a table" | "a single physical bitcoin coin, macro, on a scratched phone screen" |
| "a car" | "a black sedan with a lit rideshare windshield sign, rain, night street" |

## LAW 2 — Real people become mannequins with SIGNATURE traits, never faces.

This is the whole reason the mannequin style exists: it lets you stage real,
named people without deepfaking anyone. Recognition comes from silhouette,
hair, wardrobe, props and setting.

- Trump: swept blond hair, dark suit, long red tie, rally podium, flags.
- Obama: tall, slim, dark suit, presidential-style podium.
- Musk: black t-shirt or leather jacket, rocket hangar / car factory.
- Bezos: bald mannequin head, puffer vest.
- Gates: round glasses, v-neck sweater.
- A cop: duty belt, vest, cruiser light spill.

Never write "a face", "a likeness", "a photo of <real person>". The faceless
head IS the ethical and stylistic device. Real people may also appear as
genuine ARCHIVAL photos (app/archival.py) — that is the other sanctioned way.

## LAW 3 — Brands are products and places, never drawn logos.

The video models paint garbled glyphs, and text/logos are banned in the
negative prompt anyway. Show the brand through its unmistakable physical
world:

- Apple -> a minimalist glass storefront, brushed aluminium laptop, white cable.
- Uber -> a sedan with a lit windshield sign, phone map with a car icon.
- Twitter -> a bird-blue interface glow, an open-plan SF office.
- A bank -> marble columns, a vault door.

If a real logo is genuinely needed, Remotion composites a real asset. Wan
never draws it.

## LAW 4 — The mannequin must DO the verb.

The narration's verb is the shot. "He convinced a phone carrier" is not a
person standing near a phone; it is a mannequin mid-call, leaning forward,
one hand raised, papers scattered. Reenactment beats portrait. Static figures
staring at monitors, three scenes running, is how a video dies.

## LAW 5 — Rotate scale and framing. Never the same shot twice.

Cycle deliberately across neighbours:

1. **wide establisher** (a street, an office at night)
2. **miniature diorama** (a whole house/block as a tabletop model — a
   signature move of the reference style)
3. **medium action** (the mannequin doing the verb)
4. **macro detail** (a SIM card, a coin, a key, fingers on a keyboard)
5. **surveillance framing** (CCTV/thermal/REC overlay, security-cam angle)
6. **data map** (glowing red routes on black, top-down)
7. **archival/document insert** (a real photo, a paper, a screenshot)

Three consecutive scenes at the same scale = a flag. Every act should carry
at least one diorama, one macro and one surveillance/map frame.

## LAW 6 — Every prompt leads with the channel trigger, ends with the mood.

`<TRIGGER>, <specific subject doing the verb>, <framing/scale>, <light + one
accent>` — e.g. `3d mannequin documentary, a faceless mannequin in a hoodie
mid-phone-call at a cluttered bedroom desk, medium reenactment shot, dark
low-key light, red monitor rim glow`.

## Checklist before any storyboard ships

- [ ] Every named person/brand/place in narration appears in ITS scene's prompt.
- [ ] No prompt contains: "abstract", "generic", "a person", "some", "various".
- [ ] No three neighbouring scenes share a scale (see LAW 5).
- [ ] At least one diorama, one macro, one surveillance/map shot per act.
- [ ] Mannequins are DOING the verb, not standing.
- [ ] No text or logos requested anywhere (Remotion handles those).
