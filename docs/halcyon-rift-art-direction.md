# Halcyon Rift — Art Direction and AI Asset Pipeline

Status: Provisional art-direction brief  
Purpose: Prepare a consistent AI-generated art pipeline for Halcyon Rift  
Scope: Visual style, generation workflow, asset standards, and quality gates  
This is not an implementation specification.

## 1. Goal

Create a cohesive original 2D visual identity for Halcyon Rift that feels appropriate for a fast top-down projectile action RPG and can scale to a large amount of content.

The target is not to generate isolated attractive images. The target is a repeatable art system that can produce:

- player class skins;
- enemies;
- bosses;
- dungeon rooms;
- terrain and props;
- projectiles;
- ability effects;
- item icons;
- UI graphics;
- animation frames;
- future visual variants.

All assets should look as though they were made for the same game.

## 2. Recommended visual direction

Use original crisp 2D raster/pixel-style art with:

- a top-down or slightly angled top-down camera;
- chunky, readable silhouettes;
- limited palettes;
- hard-edged color clusters;
- clear outlines;
- restrained detail;
- strong contrast between gameplay hazards and scenery;
- simple but expressive animation;
- large, recognizable shapes at actual gameplay scale.

The visual language should be inspired by the readability and compactness of classic browser action RPGs, but must not copy another game's sprites, names, exact designs, palettes, or distinctive visual identity.

### 2.1 Character model

There are no modular character layers.

Each class has a complete standard character skin with its own:

- body;
- clothing or armor appearance;
- weapon presentation;
- animation states;
- ability animation;
- hit reaction;
- death animation.

Equipment does not need to be visually composited onto the character. Equipment can instead be represented through:

- inventory icons;
- weapon/projectile changes;
- ability effects;
- unique attack visuals;
- rarity or enchantment effects.

This substantially reduces the consistency problem for AI-generated art.

### 2.2 Effects and readability

Projectile and danger readability is more important than visual complexity.

Use:

- simple projectile silhouettes;
- high-contrast cores and outlines;
- consistent danger colors;
- clear attack wind-ups;
- minimal visual noise;
- effects that remain recognizable when scaled down.

Avoid:

- muddy gradients;
- excessively detailed projectiles;
- scenery that competes with enemy attacks;
- effects that hide the player;
- decorative particles that resemble damage.

### 2.3 Color roles — RECOMMENDED (2026-11-18)

With lethal burst damage in the design (game design §8.3), a player has to tell **danger** from **everything else** at a glance. Assign every hue family one job and keep it:

| Role | Hue family | Value / saturation |
|---|---|---|
| Environment (floor, walls, props) | each dungeon's own ground color (purple-gray stone for deep dungeons, muted sand and gray-green for the daylit Shallows) | low saturation — always the quietest thing on screen |
| Player + player shots + player abilities | cyan, blue, white | bright; the player needs a light rim or accent so it never sinks into the floor |
| Enemies + **all** enemy projectiles and telegraphs | red, orange, hot magenta | brightest and most saturated on screen; a projectile is a bright core inside a dark outline |
| Pickups and loot | gold, green | bright but never warm-red |
| Bosses | free body color, but their attacks follow the enemy row | — |

What this means for the approved style board ([`halcyon-rift-style-board.webp`](halcyon-rift-style-board.webp)):

- **The player is purple on a purple floor.** Keep the robe if it is liked, but add a cyan/white accent or rim so the silhouette separates from the room.
- **The health potion is red**, the same family as the enemy slime and enemy eyes. Move recovery pickups to the pickup row (green or gold), or a player will hesitate at the one object they should run to.
- **The torches are bright orange flames** — decorative fire in the exact family enemy projectiles will use. Keep light sources in the room, but dimmer and less saturated than any enemy shot.
- The blue orb and blue flame ring already sit in the player row, which is right.

## 3. Provisional technical art standards

These values are starting points for the style test, not permanent commitments.

### 3.1 Generation and finalization

Recommended pipeline:

1. Generate a larger source image with the AI model.
2. Remove or replace the background.
3. Crop to a fixed canvas and anchor point.
4. Reduce to the chosen logical pixel size.
5. Apply a controlled palette.
6. Clean artifacts and stray pixels.
7. Assemble animation frames.
8. Validate in an in-game-sized preview.

Do not rely on the AI model to produce perfect tiny pixel art directly.

### 3.2 Direction and animation

Recommended initial test:

- three drawn facings for the player — down, up and side, with the other side made by mirroring (revised 2026-11-18 from eight directions: eight directions times six animation states is the hardest possible consistency problem for AI generation, and at this sprite size the extra four facings are barely visible);
- two to four idle frames;
- four to six walking frames;
- a short attack animation;
- a short ability animation;
- a two-frame hit reaction;
- a short death animation.

Normal enemies may use fewer directions and fewer frames. Bosses can use bespoke animation standards.

### 3.3 Background and transparency

Final sprite assets should have:

- transparent backgrounds;
- no generated text;
- no watermarks;
- no decorative frames;
- no baked interface elements;
- no accidental secondary objects.

Background removal and edge cleanup should be treated as a required pipeline step.

## 4. The style-anchor pack

Before bulk generation, create and approve a small set of anchor assets:

1. One complete player class skin.
2. One small normal enemy.
3. One large enemy or boss.
4. One dungeon room or environment sample.
5. One basic projectile.
6. One complex projectile pattern or ability effect.
7. One item icon.
8. One UI panel or inventory element.

These assets must be displayed together at the intended gameplay scale.

The anchor pack is approved only if:

- the assets look like one game;
- their scale relationships are clear;
- the palette is coherent;
- projectiles are readable;
- the environment does not overwhelm the characters;
- the UI feels related to the world art;
- the style can plausibly be reproduced across dozens of future assets.

If the anchor pack fails, do not generate hundreds of additional assets yet.

## 5. AI generation workflow

### 5.1 Style exploration

Start with several broad style explorations, not final assets.

Each exploration should show the same small sample:

- player silhouette;
- enemy silhouette;
- projectile;
- room fragment;
- item icon.

The purpose is to compare visual systems, not individual illustrations.

Once a direction is selected, freeze:

- reference images;
- preferred model and version;
- prompt structure;
- negative constraints;
- source-image size;
- palette treatment;
- pixelization process;
- cropping rules.

### 5.2 Reference-guided generation

Every later generation should use one or more approved anchor images as references.

Text prompts alone should not define the style. References should carry:

- proportions;
- camera angle;
- palette;
- outline;
- shading;
- level of detail;
- silhouette language.

Use image-to-image, reference conditioning, inpainting, or equivalent controls when available.

### 5.3 Generate candidates, not one-offs

For each asset:

1. Generate several candidates.
2. Reject anything that violates the style rules.
3. Select the best silhouette and composition.
4. Correct the selected image.
5. Use it as the reference for related assets.
6. Record the final prompt and source reference.

Do not accept the first visually attractive output automatically.

### 5.4 Animation generation

Do not depend on a model to produce a perfect finished sprite sheet in one pass.

Instead:

1. Generate a canonical key pose.
2. Generate a small number of related key poses using the same reference.
3. Keep the canvas, scale, and anchor point fixed.
4. Assemble the frames.
5. Correct size drift and inconsistent anatomy.
6. Test the animation at gameplay scale.

The final animation should be judged in motion, not as a collection of individually attractive frames.

## 6. Prompt structure

Use a consistent prompt structure for every asset family.

~~~text
Use case: stylized-concept
Asset type: <player sprite / enemy sprite / boss / environment / projectile / icon>
Primary request: <specific asset>
Input images: approved style anchor references
Scene/backdrop: <transparent background or specified environment>
Subject: <single asset and its gameplay role>
Style/medium: original crisp 2D top-down pixel-style raster art
Composition/framing: centered, readable silhouette, fixed canvas, game-asset framing
Lighting/mood: consistent light direction, restrained shading
Color palette: approved palette family
Materials/textures: simple readable material cues
Text: none
Constraints: one asset, fixed perspective, consistent scale, transparent background
Avoid: text, watermark, extra objects, frame, photorealism, smooth anti-aliased edges,
uncontrolled gradients, unrelated style, excessive detail, cropped subject
~~~

The exact prompt should change by asset, but the style and constraint sections should remain largely stable.

Do not use prompts that ask for an exact copy of Realm of the Mad God, Darza's Dominion, or another copyrighted game's style. Use descriptive visual characteristics instead.

## 7. Asset-family workflows

### 7.1 Player classes

For each class:

- establish one canonical full-body design;
- generate directional poses from that reference;
- generate animation states;
- freeze the proportions;
- reuse the same character reference for future ability effects.

Do not generate a new visual identity for each weapon or armor item.

### 7.2 Normal enemies

For each enemy family:

- establish one silhouette;
- establish its palette;
- establish its attack visual language;
- generate movement, attack, hit, and death states;
- create limited variants through color, shape, and behavior changes.

Normal enemies should be visually distinct by role, not just by color.

### 7.3 Bosses

Bosses receive more generation iterations and bespoke effects.

Generate separately:

- base silhouette;
- idle or movement pose;
- phase poses;
- attack telegraphs;
- projectiles;
- arena effects;
- death effect.

Keep the boss recognizable even when its effects are active.

### 7.4 Environments

Revised 2026-11-18: **rooms are built from a tileset, not generated as whole images.**

The original plan generated each room as one image and then mirrored and rotated rooms procedurally. With a slightly angled camera and a consistent light direction, rotating a room breaks both — walls show their front faces and the light swings around. A whole-image room also needs its collision traced by hand, and every new layout is a new generation.

Instead:

1. **Light comes from above** (straight down, slightly toward the viewer), so mirroring a room left-to-right changes nothing about the lighting. Shadows fall straight below objects, as on the style board.
2. **Rooms may be mirrored left-to-right. They are never rotated or flipped top-to-bottom.**
3. Build a **small tileset** — floor variants, wall tops and faces, corners, door gaps, water/edge — plus separate prop sprites (torches, barrels, crates, rubble).
4. Lay out rooms in a tile editor (Tiled, free, exports JSON). Collision comes from the tiles; spawn points, loot points, entry/exit and the boss marker are an object layer in the same file — so art and gameplay data live side by side but separately.
5. Variety comes from many cheap authored layouts × mirroring × spawn sets × prop variants, rather than from rotation.

AI is still useful here — for the tile and prop art, and for room *concepts* to lay out by hand — but expect hand cleanup: AI output is rarely seamless enough to tile.

### 7.5 Projectiles and effects

Use AI to explore effect shapes and color language, then convert the approved effects into a controlled reusable library.

Create templates for:

- single projectiles;
- spread shots;
- radial bursts;
- piercing shots;
- beams;
- circular telegraphs;
- cone telegraphs;
- impact effects;
- enemy death effects;
- ability activation effects.

Projectiles should be simple enough that their hitbox and danger are visually obvious.

### 7.6 Item icons

Generate one icon at a time with:

- a fixed square canvas;
- a single object;
- no text;
- a clear silhouette;
- controlled rarity treatment added outside the generation model.

Use the application to add names, numbers, borders, and stat text.

## 8. Content scaling strategy

Use three levels of visual investment.

### Standard content

Reuse templates, palettes, and effect families for:

- ordinary enemies;
- normal weapons;
- common armor;
- ordinary rings;
- common room decorations;
- basic projectiles.

### Premium content

Spend more effort on:

- bosses;
- unique items;
- rare rings;
- late-game abilities;
- major dungeon landmarks;
- new classes.

### Controlled variation

Generate variety through:

- palette variants;
- silhouette variants;
- attack-pattern changes;
- projectile changes;
- room ordering;
- environmental decorations;
- effect color families.

Do not generate every common item or room as an unrelated visual concept.

## 9. Quality gates

Every asset should pass these checks before being accepted.

### Style consistency

- Does it look like it belongs to the anchor pack?
- Is the camera angle consistent?
- Are the proportions plausible?
- Does the light come from the same direction?
- Is the palette compatible?

### Gameplay readability

- Is the silhouette recognizable at actual gameplay size?
- Can the player distinguish it from the background?
- Is its attack readable?
- Does its projectile look dangerous for the right reason?
- Is the effect too visually noisy?

### Technical cleanliness

- Is the subject centered?
- Is the anchor point correct?
- Is the background truly transparent?
- Are there stray pixels or artifacts?
- Is there any generated text or watermark?
- Are animation frames aligned?
- Are collision and visual boundaries intentionally separate?

### Legal and provenance

- Is the design original rather than a close copy?
- Are references and source images recorded?
- Are model and generation settings recorded where practical?
- Are any external assets used under a compatible license?

## 10. Recommended first work package

The first actual image-generation session should produce a style exploration board containing several original directions, not final game assets.

After selecting one direction, generate the anchor pack:

- player skin;
- enemy;
- boss;
- environment;
- projectile;
- ability effect;
- item icon;
- UI sample.

Only after those are approved should we begin producing a full class, dungeon, or enemy roster.

## 11. Current recommendation

Use an AI-generated, reference-controlled, crisp 2D pixel-style pipeline with:

- one complete skin per class, three drawn facings plus mirroring;
- no character equipment layers;
- rooms built from a tileset in a tile editor, mirrored left-to-right only, lit from above (§7.4);
- the color roles in §2.3;
- limited palettes;
- reference-guided generation;
- large-source generation followed by standardized pixelization;
- small-frame-count animation;
- reusable projectile and VFX templates;
- manual or scripted cleanup;
- bespoke treatment for bosses and unique items.

The target is not “AI generated everything independently.” The target is “AI generates within a controlled visual system.”

