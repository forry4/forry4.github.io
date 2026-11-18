# Halcyon Rift — AI Art Asset Acquisition Plan

Status: Pre-implementation plan  
Purpose: Define the art and supporting asset package needed for the first playable implementation  
Primary style reference: The approved pixel-art style board supplied in the design conversation  
Working name: Halcyon Rift

## 1. Objective

Produce enough coherent, game-ready visual material to begin implementing the first playable vertical slice of Halcyon Rift.

The goal is not to generate every asset the finished game will ever need. The goal is to create:

- a locked visual direction;
- one complete playable class;
- one complete introductory dungeon;
- enough enemies, projectiles, effects, items, and UI to exercise the core loop;
- consistent metadata so another AI can integrate the assets without guessing.

The final game will need substantially more content, but architecture should begin once the minimum vertical-slice package is approved.

## 2. Current visual direction

Use the approved style board as the canonical visual reference.

The target language is:

- original crisp 2D pixel-style raster art;
- top-down or slightly angled top-down view;
- chunky pixel clusters;
- strong near-black outlines;
- saturated purple, blue, and indigo tones;
- controlled warm red and orange accents;
- dark navy backgrounds;
- simple, readable silhouettes;
- restrained glow and particle effects;
- enough detail to feel polished without reducing gameplay readability.

Do not create each asset from an unrelated prompt. Every generation must use the approved style board or an approved descendant asset as a reference.

The board is a style and role reference. It should not be treated as a final production sprite sheet unless individual elements are separately cleaned and prepared.

## 3. Generation principles

### 3.1 Generate in dependency order

The visual dependencies should be established in this order:

1. Style and technical specification.
2. Scale reference.
3. Player character.
4. Normal enemy scale and silhouettes.
5. Boss scale.
6. Environment rooms and terrain.
7. Projectiles and attack effects.
8. Loot and item icons.
9. UI and feedback effects.
10. Additional variants.

Later assets should use earlier approved assets as references.

### 3.2 Use one asset per generation request

Do not ask the image model to produce a large mixed sprite sheet unless the result is only a concept board.

For production assets, prefer:

- one character or enemy at a time;
- one item icon at a time;
- one effect at a time;
- one room template at a time.

This makes cropping, alignment, cleanup, and reference reuse much easier.

### 3.3 Keep generation separate from finalization

Every generated asset goes through:

1. Candidate generation.
2. Selection.
3. Background removal.
4. Cropping and alignment.
5. Pixelization or palette treatment.
6. Artifact cleanup.
7. Gameplay-size review.
8. Animation assembly, if applicable.
9. Metadata creation.
10. Approval.

A generated image is not automatically a game-ready asset.

## 4. Technical art specification to lock first

Before generating the production pack, finalize these technical values:

- logical tile size;
- character canvas size;
- enemy canvas sizes;
- boss canvas sizes;
- directional count;
- animation frame counts;
- pixel scaling method;
- palette rules;
- outline rules;
- sprite anchor convention;
- shadow convention;
- effect blending convention;
- source and export formats.

### Recommended initial values

These are starting recommendations, not final commitments:

- use a fixed logical pixel grid;
- use eight directions for the player;
- use fewer directions for ordinary enemies where possible;
- use small frame counts rather than elaborate animation;
- use transparent PNG exports;
- use nearest-neighbor scaling;
- keep shadows visually separate from the main silhouette;
- keep collision geometry separate from the art;
- generate at a larger source resolution and reduce consistently.

The exact canvas dimensions should be tested with the player, an enemy, and a projectile before bulk generation.

## 5. Minimum vertical-slice asset package

This is the minimum package required for a convincing first playable loop.

### 5.1 Style and reference assets

Required:

- approved style board;
- palette reference;
- scale comparison sheet;
- one environment sample;
- one player sample;
- one enemy sample;
- one projectile sample;
- one effect sample;
- one item icon sample.

The scale comparison sheet should show player, normal enemy, boss, projectile, and room proportions together.

### 5.2 Player class package

The initial playable class is Ranger.

Required:

- complete Ranger skin;
- idle animation;
- movement animation;
- basic attack animation;
- ability animation;
- hit reaction;
- death animation;
- shadow;
- selection or portrait image;
- class icon;
- basic weapon icon;
- ability icon.

The character should be a complete fixed skin. Do not generate equipment overlays.

The weapon and ability can be represented visually through:

- the character's attack animation;
- projectile art;
- ability effects;
- inventory icons;
- equipment icons.

### 5.3 Initial enemies

The first dungeon needs a small, understandable enemy set.

Required categories:

- basic melee chaser;
- basic aimed shooter;
- fast mobile enemy;
- stationary radial shooter;
- one boss.

Each normal enemy needs:

- idle or movement state;
- attack state;
- hit reaction;
- death animation;
- attack telegraph;
- projectile or attack effect where applicable;
- enemy icon or loot representation if exposed in the interface.

The boss needs:

- idle or movement state;
- at least two attack patterns;
- phase or intensity transition;
- hit reaction;
- death animation;
- attack telegraphs;
- boss-specific effects;
- boss portrait or selection icon if used by the UI.

Exact enemy identities and mechanics remain a design choice. The art package should not be generated until those roles are confirmed.

### 5.4 Introductory dungeon package

The first dungeon is Beach.

Required:

- entrance room;
- several reusable combat-room templates;
- transition or connector pieces;
- boss room;
- walkable ground;
- blocked terrain;
- terrain edges;
- water or environmental boundary;
- rock or obstacle objects;
- decorative props;
- room shadows;
- room collision masks;
- boss-room boundary or encounter marker;
- dungeon icon;
- dungeon-selection thumbnail.

The initial dungeon should use complete authored room templates rather than unconstrained random tile generation. Procedural logic can select, arrange, mirror, and populate the rooms.

Each room needs separate data for:

- visual art;
- walkable areas;
- blocked areas;
- enemy spawn points;
- loot spawn points;
- entry and exit points;
- boss or encounter markers.

AI should generate the visual room concepts and room art. Collision and spawn metadata should be authored separately.

### 5.5 Projectiles and combat effects

Required:

- Ranger basic projectile;
- Ranger ability projectile or effect;
- one projectile for each ranged enemy;
- boss projectile patterns;
- projectile impact;
- player hit effect;
- enemy hit effect;
- enemy death effect;
- boss phase transition effect;
- boss death effect;
- attack telegraphs;
- recall effect;
- level-up effect;
- dungeon-completion effect;
- death effect.

Effects must be judged at gameplay size. Large concept-board effects often become unreadable or visually noisy when reduced.

### 5.6 Pickups and loot

Required:

- health recovery pickup;
- optional MP pickup if the first design includes one;
- common gear pickup appearance;
- uncommon or better gear pickup appearance;
- unique gear pickup appearance;
- item rarity glow or outline;
- item-ground shadow;
- dropped-item state;
- pickup interaction indicator;
- discarded-item state if visually distinct.

There is no automatic collection. Pickup visuals must make it obvious:

- what can be collected;
- what is equipment;
- what is a recovery pickup;
- what is rare;
- what is already on the ground.

### 5.7 Initial item icons

For a first Ranger slice, create a small representative set rather than the complete future equipment library.

Required categories:

- one or more weapon icons;
- one or more armor icons;
- one or more ability icons;
- several normal ring icons;
- at least one unusual or unique ring icon;
- icons for each initial gear tier included in the prototype;
- fusion result presentation;
- empty-slot icon;
- invalid or incompatible-item indicator if needed.

Equipment does not need to appear on the character. Icon quality and readability are therefore especially important.

### 5.8 Town and interface art

Required for a playable loop:

- town background or simple town scene;
- dungeon-selection background or panel;
- character-slot portrait;
- inventory panel styling;
- vault panel styling;
- equipment-slot frames;
- item rarity frames;
- fusion panel art;
- recall button icon;
- death screen illustration or background;
- completion screen illustration or background;
- HP bar;
- recovery-limit indicator;
- MP bar;
- ability icon frame;
- XP bar;
- stat icons;
- warning or danger icons.

Simple layout panels, bars, labels, and text should be created in HTML/CSS or code rather than generated as raster art. AI should generate illustrations, icons, textures, and decorative elements—not text that must be accurate.

## 6. Asset metadata required alongside images

Every final asset needs metadata. AI cannot reliably create this correctly.

At minimum, record:

- asset ID;
- asset type;
- source reference;
- prompt;
- generation date;
- source image or model version where available;
- canvas dimensions;
- frame dimensions;
- animation states;
- frame order;
- anchor point;
- intended world scale;
- palette family;
- collision shape or collision-mask reference;
- hitbox or hurtbox notes;
- intended use;
- approval status.

For example:

~~~text
asset_id: ranger_basic_projectile
asset_type: projectile
source_reference: approved_style_anchor
canvas: 16x16 logical pixels
frames: 4
anchor: center
collision: circular, smaller than visible sprite
palette: player_blue
states: travel, impact
status: approved
~~~

The exact file format can be chosen later. The important principle is that art and gameplay metadata are separate but linked.

## 7. AI prompt workflow

### 7.1 Master style prompt

Create one stable style section that appears in every prompt:

~~~text
Original crisp 2D top-down pixel-style raster game art. Chunky pixel clusters,
strong near-black outlines, saturated indigo, violet, blue, red, and orange palette,
dark navy background, readable silhouettes, restrained glow, consistent pixel density,
clear game-asset framing, no text, no logo, no watermark, no extra objects.
~~~

This should be combined with an asset-specific request.

### 7.2 Asset-specific prompts

Each prompt should identify:

- the asset's gameplay role;
- its approximate size or visual importance;
- its silhouette;
- its palette family;
- its attack or material;
- the reference image being used;
- what must not change.

### 7.3 Reference hierarchy

Use references in this order:

1. Approved style board.
2. Approved scale sheet.
3. Approved asset from the same family.
4. Approved final asset for variants.

Do not allow unrelated generations to become references merely because they look attractive.

## 8. Acceptance criteria

A candidate is approved only if it passes all four categories.

### Visual consistency

- It belongs to the established style.
- It uses compatible proportions.
- Its lighting and outline match.
- It does not look like it came from another game.
- It uses the approved palette family.

### Gameplay readability

- It is recognizable at actual gameplay scale.
- Its silhouette is distinct.
- Its attack or effect is easy to understand.
- It does not blend into expected environments.
- It does not obscure more important effects.

### Technical cleanliness

- It has the correct canvas size.
- It has a clean transparent background where required.
- It has no text or watermark.
- It has no accidental extra objects.
- Its anchor point is consistent.
- Its frames align.
- Its collision metadata can be authored separately.

### Production usefulness

- It can be reused as a reference.
- It can produce variants without major style drift.
- It fits the intended content budget.
- It does not require a completely new rendering rule.
- It has a known purpose in the vertical slice.

## 9. Production phases

### Phase 0 — Lock the style

Deliverables:

- approved style board;
- written art direction;
- palette reference;
- technical-size experiment;
- scale comparison;
- decision on directional and animation standards.

Exit condition:

- the style can be reproduced for at least three unrelated asset roles.

### Phase 1 — Generate the player and scale references

Deliverables:

- complete first-class key art;
- small animation test;
- player shadow;
- basic attack effect;
- ability effect;
- scale sheet against a normal enemy and boss silhouette.

Exit condition:

- the player remains readable during movement, firing, and ability use.

### Phase 2 — Generate the enemy family

Deliverables:

- three or four normal enemy families;
- enemy attack telegraphs;
- enemy projectiles;
- hit and death effects;
- boss key art;
- boss attack effects.

Exit condition:

- enemies are visually distinguishable by combat role.

### Phase 3 — Generate the introductory dungeon

Deliverables:

- Beach room templates;
- terrain and obstacle art;
- room decorations;
- boss room;
- collision masks;
- spawn markers;
- dungeon icon.

Exit condition:

- rooms can be assembled into a complete route without visual seams.

### Phase 4 — Generate loot and interface assets

Deliverables:

- initial equipment icons;
- rings;
- rarity frames;
- pickup effects;
- inventory and vault panels;
- fusion interface;
- health, recovery, mana, XP, and ability UI;
- death, recall, and completion feedback.

Exit condition:

- a player can understand the full town-to-dungeon-to-loot loop without placeholder art.

### Phase 5 — Integration review

Review the complete slice at:

- normal gameplay scale;
- several desktop resolutions;
- a crowded combat scene;
- low health;
- full inventory;
- rare loot;
- boss combat;
- death;
- recall;
- vault management.

Fix style and readability problems before expanding the content library.

## 10. What can wait

The following do not need to exist before architecture begins:

- all five gear tiers;
- every enchantment icon;
- every class;
- every dungeon;
- every boss;
- every unique item;
- complete future UI decoration;
- co-op-specific visuals;
- account-progression art;
- advanced status-effect visuals;
- full procedural tileset coverage.

They can be added incrementally after the data model and rendering pipeline are stable.

## 11. When architecture can begin

Architecture can begin after the following are approved:

- style reference;
- technical asset specification;
- one playable character;
- one basic projectile;
- one ability effect;
- three normal enemy placeholders or final assets;
- one boss placeholder or final asset;
- one small dungeon-room set;
- a few item icons;
- basic UI panels;
- asset metadata conventions.

The full art library is not required.

A good engineering handoff can use final art for the most important assets and temporary colored placeholders for anything not yet generated. This is preferable to delaying architecture until every future asset exists.

## 12. Handoff package for the architecture chat

The next implementation chat should receive:

1. docs/halcyon-rift-game-design.md
2. docs/halcyon-rift-art-direction.md
3. this asset plan
4. the approved style-reference image
5. the asset manifest
6. any generated source and exported images
7. the list of open art questions
8. the intended vertical-slice scope

The implementation chat should be instructed to:

- build the asset-loading and rendering path around the manifest;
- keep visual assets replaceable;
- use placeholders where final art is missing;
- avoid hard-coding game logic to image dimensions;
- keep collision and gameplay metadata separate from art;
- avoid expanding beyond the vertical slice without approval.

## 13. Final recommendation

Do not attempt to generate every game asset before writing architecture.

Generate the first vertical-slice pack first:

- one class;
- one dungeon;
- a few enemies;
- one boss;
- a small gear set;
- core projectiles and effects;
- basic town and inventory UI.

Once that pack and its metadata are approved, another AI can begin implementing the rendering, asset loading, dungeon-room, combat, loot, inventory, recall, death, vault, and fusion architecture. The rest of the art library can then be produced against a working game instead of being generated speculatively.

