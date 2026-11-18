# Halcyon Rift — Game Design Document

Status: Concept and pre-implementation design  
Last updated: 2026-11-17  
Working name: Halcyon Rift  
Audience: Future collaborators and AI agents  

## 1. Purpose of this document

This document records the current design for Halcyon Rift, a browser-based top-down action RPG with character permadeath, procedural dungeons, persistent vault storage, and future optional co-op.

It is intentionally written as a handoff document. A future AI should use it to understand:

- what has already been decided;
- what is a recommendation rather than a commitment;
- what is explicitly out of scope;
- what remains unresolved;
- which decisions must not be casually changed;
- what should be discussed before implementation begins.

This is still a design-phase document. No implementation should begin merely because a system is mentioned here. Open questions should be resolved first, and tentative recommendations should not be treated as settled rules.

### Decision labels

- DECIDED — explicitly agreed upon.
- RECOMMENDED — a proposed baseline that has not necessarily been finally approved.
- OPEN — requires further design discussion.
- DEFERRED — intentionally postponed until the core game is established.

When a later user decision conflicts with an older recommendation, the later user decision wins.

## 2. Executive summary

Halcyon Rift is a browser-first, desktop-only, top-down projectile-focused action RPG and procedural dungeon crawler.

Players maintain a roster of persistent characters. Each character belongs to one class and can never change class. A character enters short, finite, named dungeons, fights enemies, collects class-appropriate gear, gains experience, and decides whether to safely recall or push toward the boss for better rewards.

Death permanently destroys the character. Everything carried by that character is lost, including equipment, inventory, level, and stat progression. Equipment stored in the account-wide vault survives and can be used by future characters.

The game is inspired by the combat, projectile patterns, permadeath, classes, procedural dungeons, loot rarity, fast session loop, visual readability, and risk/reward structure of games such as Realm of the Mad God and Darza's Dominion. It is not intended to be a full MMO.

### Core elevator pitch

> A browser-based, top-down, bullet-heavy action RPG where one to four players explore dangerous procedural worlds, defeat bosses, collect equipment, and risk losing their current character when they die.

The more precise current description is:

> A casual but dangerous character-permadeath dungeon crawler where players build a roster, choose their own dungeons, extract loot by recalling to town, and risk everything carried by a character when pushing for boss rewards.

## 3. Product identity and design pillars

### 3.1 Primary design pillars

#### Readable projectile combat

Combat should emphasize planning, positioning, and avoiding patterns rather than perfect reflexes or invulnerability-dodge timing.

Projectiles, enemy attacks, terrain, and safe spaces must be visually legible. Difficulty should come from choosing and maintaining safe positions, not from hidden or unavoidable damage.

#### Meaningful character loss

Characters should become valuable because they accumulate levels, stats, gear, and history. Death must matter enough that players feel tension when carrying valuable equipment.

The game should still make rebuilding approachable. A new character can use vaulted gear immediately if it fits the class, and a skilled low-level character should remain able to contribute in difficult content.

#### Safe long-term storage

The vault is the account's main persistent safety net. It lets players protect equipment for future characters without requiring a large account-wide power-progression system.

The vault should create meaningful decisions:

- keep valuable gear safe;
- equip it for more power;
- risk it in a dungeon;
- fuse duplicate gear into a better roll.

#### Player agency

Players choose which dungeon to enter and are never forced into a particular progression path. Instant recall is always available. The game may communicate danger and recommended strength, but it should not require a rigid quest or dungeon sequence.

#### Content depth over launch breadth

The long-term ambition is a large volume of dungeons, enemies, equipment, enchantments, classes, and bosses. The first release should establish reusable content structures and a strong core loop rather than attempting to ship the full content volume immediately.

#### Solo-first, co-op-compatible

Every class should function alone. The initial game should be balanced around solo play, while preserving a clean path to one-to-four-player co-op later.

There should be no mandatory healer, tank, or support role.

### 3.2 Desired player feeling

The desired emotional rhythm is:

- relaxed choice in town;
- immediate access to a dungeon;
- focused movement and projectile avoidance;
- growing confidence while collecting loot;
- a decision about whether to recall;
- temptation to risk the character for the boss;
- satisfaction when returning with valuable gear;
- concern when deciding what to vault and what to equip.

The structure should be casual in accessibility and session length, but not consequence-free.

## 4. Explicit non-goals

The following are not part of the initial product direction:

- full MMO-scale public worlds;
- persistent shared overworlds;
- hundreds of players in one dungeon;
- public-world population management;
- a narrative campaign;
- lore, dialogue, quests, or story progression;
- PvP;
- guilds, public chat, or broad social systems;
- mobile support;
- controller support;
- Steam as a launch platform;
- monetization of any kind;
- currencies;
- shops;
- player-to-player trading;
- durability;
- item levels separate from tiers;
- equipment set bonuses;
- a large account-wide power tree;
- mandatory party composition;
- a required progression path through dungeons;
- status effects in the initial combat system;
- complicated cooldown management;
- automatic loot collection.

These may be revisited only deliberately. They should not be added merely because they are common in other action RPGs.

## 5. Platform and presentation

### 5.1 Platform

DECIDED:

- Browser desktop is the first and primary platform.
- The game is online-only, including solo play.
- Mouse and keyboard are the supported controls.
- Mobile and controller support are not initial requirements.
- Steam is not part of the launch plan.

The browser is appropriate because this is a two-dimensional, one-to-four-player online game that benefits from instant access, easy updates, and integration with the existing website.

The game should not be designed around browser-specific limitations in a way that makes it feel like a reduced native game. It should be a deliberate browser game with a responsive desktop presentation.

### 5.2 Visual direction

DECIDED:

- The visual inspiration is the readable, compact, sprite-oriented style of Realm of the Mad God and Darza's Dominion.
- The game should use original visual assets and its own visual identity.
- Projectiles and danger telegraphs must remain readable against the environment.

OPEN:

- Exact art style;
- pixel scale;
- tile dimensions;
- sprite resolution;
- color palette;
- amount of animation;
- UI styling;
- camera zoom;
- whether the game uses a fixed logical resolution or a more flexible viewport.

### 5.3 Screen-size goals

RECOMMENDED:

- Primary target: 1280×720.
- Common laptop target: 1366×768.
- Large desktop target: 1920×1080.
- Practical lower target: approximately 1024×600.

The playfield should scale cleanly while preserving gameplay readability. Menus and inventory screens should be responsive independently of the game world.

## 6. Core game loop

The intended loop is:

1. Enter town.
2. Review the character roster.
3. Equip or vault gear.
4. Fuse duplicate items if desired.
5. Choose any available dungeon.
6. Enter a newly generated finite dungeon.
7. Fight enemies and collect loot manually.
8. Regenerate slowly and use recovery pickups when needed.
9. Decide whether to recall or continue.
10. Recall safely, or push onward toward the boss.
11. Complete the dungeon for its best rewards, or die and lose the character.
12. Return to town.
13. Sort, equip, vault, discard, or fuse gear.
14. Repeat with the same character or create a replacement.

### 6.1 Town

Town is the safe management space. It should provide:

- character selection;
- character creation;
- dungeon selection;
- vault access;
- equipment management;
- inventory management;
- item fusion;
- the ability to discard or reorganize gear;
- future co-op party entry, if co-op is later added.

Town is also the major reset point for character health and recovery capacity.

### 6.2 Dungeons

Dungeons are:

- finite;
- named;
- procedurally assembled from authored room templates;
- mostly linear initially;
- selectable directly from town;
- playable without a mandatory order;
- designed around a specific difficulty and loot profile;
- ended by a boss encounter.

An easy dungeon may take roughly one minute. A hard dungeon may take roughly five minutes. Exact durations are OPEN and should be tuned through play.

## 7. Character model

### 7.1 Character roster

DECIDED:

- Each account has four character slots.
- A character belongs permanently to one class.
- A character cannot change class.
- A new character can be created after another dies.
- The initial game begins with one class.
- The first class planned for the initial content slice is Ranger, but class-specific design is intentionally outside the current general-design discussion.

### 7.2 Character death

When a character dies:

- the character is permanently deleted;
- its level is lost;
- its stat progression is lost;
- its equipped gear is lost;
- its inventory gear is lost;
- any carried loot is lost;
- anything consumed or earned by that character is lost with it;
- gear in the account vault remains safe;
- the player may create or select another character immediately.

This is character permadeath with persistent account storage, rather than a full account reset.

### 7.3 Rebuilding

Rebuilding should be fast enough that death does not end a play session. A new character should be able to:

- level quickly at the beginning;
- equip appropriate vaulted gear immediately;
- enter any dungeon immediately;
- contribute damage in co-op with veterans;
- survive through skillful play even when undergeared.

Veteran characters should have a meaningful advantage, but not such a large advantage that a new character is instantly killed or irrelevant.

## 8. Combat rules

### 8.1 Controls

DECIDED:

- WASD movement.
- Mouse controls independent aiming.
- The player can move while firing.
- Auto-fire can be held or toggled.
- The player fires in the direction of the cursor.
- There is no ammunition.
- Basic attacks are generally continuous.
- Abilities are activated manually with a key or button.
- Abilities can be used while the character is firing.

### 8.2 Movement and collision

DECIDED:

- Characters can be blocked by solid terrain.
- Projectiles can be blocked by certain terrain.
- Characters do not collide with one another.
- There is no dodge-through or invulnerability-roll mechanic.
- Avoidance is based on ordinary movement and positioning.

OPEN:

- Whether enemies collide with one another;
- whether enemies collide with terrain;
- exact collision shapes;
- whether some projectiles pass through specific terrain;
- whether the game has knockback;
- whether movement has acceleration or is immediately responsive.

### 8.3 Combat priorities

Combat should prioritize:

- planning;
- positioning;
- target priority;
- projectile awareness;
- terrain use;
- choosing when to spend mana;
- deciding when to recall.

It should not primarily prioritize:

- reaction-time tests with tiny telegraphs;
- animation-cancel mastery;
- memorizing long cooldown rotations;
- unavoidable burst damage;
- party role requirements.

### 8.4 Abilities

DECIDED:

- Abilities are class-specific active skills.
- Abilities cost MP.
- Abilities generally do not have a cooldown.
- Abilities can be used while basic attacks continue.
- Mana regeneration is constant but slow.

The mana cost is the primary limiter for the initial ability system. Some future abilities may have cooldowns if necessary, but cooldowns should not become the dominant management system.

OPEN:

- Whether ability activation has an animation time;
- whether abilities can be interrupted;
- whether ability use changes movement;
- exact MP costs;
- whether all abilities scale from ability power;
- whether any abilities can restore health.

### 8.5 Status effects

Status effects are deferred. The initial combat system should avoid poison, stun, silence, slow, root, burn, and similar effects unless a specific future design discussion adds them.

## 9. Health, healing, and mana

### 9.1 Health values

The character has:

- maximum HP;
- current HP;
- a recovery limit.

The invariant is:

~~~text
0 <= current HP <= recovery limit <= maximum HP
~~~

### 9.2 Recovery limit

The recovery limit represents how high ordinary healing can restore the character.

The current intended rule is:

- the character begins at full HP and full recovery capacity;
- when the character reaches a new lower HP value, the recovery limit decreases;
- HP regeneration restores current HP but never increases the recovery limit;
- map pickups can increase the recovery limit and current HP;
- healing cannot exceed the recovery limit;
- returning to town restores current HP and recovery capacity to maximum;
- entering a new dungeon also restores current HP and recovery capacity to maximum;
- instant recall restores current HP and recovery capacity to maximum.

The exact formula is currently based on the intended model:

~~~text
recovery limit = min(maximum HP, 100 + lowest HP reached)
~~~

The fixed 100 value is provisional and may be changed after testing.

### 9.3 HP regeneration

DECIDED:

- HP regeneration exists as a stat.
- It is constant but slow.
- It restores current HP only.
- It cannot raise the recovery limit.
- It stops restoring health when current HP reaches the recovery limit.

### 9.4 Map pickups

Map pickups are manually collected. They may:

- restore current HP;
- raise the recovery limit;
- do both simultaneously.

OPEN:

- pickup size and frequency;
- whether pickups are shared in future co-op;
- whether pickups disappear after a timer;
- whether there are multiple pickup strengths;
- whether MP pickups exist.

### 9.5 Mana

DECIDED:

- Characters have maximum MP.
- Abilities consume MP.
- Mana regeneration is constant but slow.
- Mana regeneration can be improved through stats or enchantments.

OPEN:

- whether MP regeneration occurs during all activity;
- whether taking damage changes mana regeneration;
- exact starting and maximum MP values;
- whether map pickups restore MP.

## 10. Character progression

### 10.1 Levels

DECIDED:

- Characters begin at level 1.
- Characters progress to level 20.
- Early levels should be gained relatively quickly.
- The XP requirement increases at each level.
- The easiest dungeon provides enough XP for approximately level 1 → level 2.
- Beach is intended to provide early XP but no stat increases.

The exact XP curve is OPEN. A likely baseline is:

- early dungeons provide approximately one early level;
- later levels require multiple clears;
- harder dungeons provide more XP;
- completing difficult content should eventually be more efficient than farming the easiest dungeon.

OPEN:

- whether XP is awarded continuously from enemies;
- whether XP is lost or retained when recalling;
- whether boss completion gives a large XP bonus;
- whether a dungeon must be completed for its XP;
- exact level 20 pacing.

### 10.2 Stats

The current planned stats are:

- maximum HP;
- maximum MP;
- attack power;
- defense;
- attack speed;
- ability power;
- mana regeneration;
- HP regeneration.

Each stat can be permanently increased for the current character up to a cap.

There are no stat potions. Instead, some mid- and late-game dungeons automatically increase one specific stat when successfully completed.

RECOMMENDED baseline:

- a dungeon has an associated stat reward;
- defeating its boss and completing the dungeon grants progress in that stat;
- the reward is repeatable until the character reaches that stat's cap;
- recalling before completion grants no stat increase;
- harder dungeons eventually offer more efficient progression;
- each stat eventually has more than one possible dungeon source.

OPEN:

- exact stat caps;
- exact amount gained per completion;
- whether the reward is a full point or fractional progress;
- whether the dungeon reward triggers on boss death or a later completion event;
- which dungeons improve which stats;
- whether a few late dungeons offer a choice of stats;
- whether all characters of all classes share cap values.

### 10.3 Account progression

DEFERRED:

- account-wide skill trees;
- permanent account power bonuses;
- account-wide stat increases;
- quests;
- achievements;
- cosmetics;
- extra character slots;
- extra vault space.

The vault is the primary account-level progression system initially. Future account unlocks should generally be horizontal rather than direct power increases.

## 11. Equipment and loot

### 11.1 Equipment slots

Each character has five equipment slots:

1. Weapon
2. Armor
3. Ability
4. Ring 1
5. Ring 2

### 11.2 Equipment restrictions

DECIDED:

- Weapons, armor, and abilities are class-specific.
- Rings are shared across all classes.
- A character may not equip two copies of the same ring.
- A character may equip two different rings.
- A level-one character may equip any vaulted gear that fits its class.
- Equipment is not level-gated.

The duplicate-ring restriction is based on the same base ring item, even if two copies have different enchantment rolls.

### 11.3 Tiers and item levels

DECIDED:

- There are five gear tiers.
- Items do not have separate item levels.
- A gear item's tier is its main base-power classification.
- Each base item within a tier has fixed base statistics.
- Equipment can roll zero to four enchantments.
- Unique items may have unusual behavior-changing effects.
- Standard items generally have stat-oriented enchantments.
- There are no set bonuses.
- There is no durability.

### 11.4 Enchantments

Enchantments may:

- modify the item's statistics;
- modify character statistics;
- alter an attack;
- alter an ability;
- create other special effects.

Enchantments should be readable and bounded. The system should avoid requiring enormous combinations of random effects to produce a viable character.

OPEN:

- enchantment families;
- whether enchantment values have ranges;
- which effects can appear on which item slots;
- whether effects stack additively or multiplicatively;
- whether unique items can roll ordinary enchantments;
- whether all four slots can contain major effects;
- exact rarity distribution of slot counts.

### 11.5 Vault

DECIDED:

- The account has a shared vault.
- The vault has 64 slots initially.
- Vaulted gear survives character death.
- Gear can be stored for future characters and future classes.
- Rings can be used by any future class.

The vault is the only reliable protection for gear from character death.

### 11.6 Character inventory

DECIDED:

- Characters have 16 inventory slots.
- Inventory gear is at risk during character death.
- Equipment can be left on the ground.
- Equipment can be swapped with an existing inventory item.
- Ordinary gear can be discarded anywhere.
- Discarded gear remains on the ground until the dungeon instance ends.
- There is no automatic loot collection.

OPEN:

- exact pickup interaction;
- whether inventory is sorted automatically;
- whether items display class compatibility prominently;
- whether gear can be rearranged during combat;
- whether ground loot has ownership rules in future co-op;
- whether ground loot has a maximum count or timer.

### 11.7 Item fusion

DECIDED:

- Fusion is guaranteed to succeed.
- Two inputs must be the same base item.
- Two inputs must have the same tier.
- Two inputs must have the same number of enchantment slots.
- Standard items can only fuse with identical standard items.
- Unique items can only fuse with identical unique items.
- Standard and unique items cannot be mixed.
- Both inputs are consumed.
- The result keeps the same base item and tier.
- All enchantments are completely rerolled.
- No enchantments are inherited.
- The result normally keeps the same slot count.
- The result may rarely gain multiple slots.
- The maximum is four slots.

Future possibility:

- a rare consumable may allow one chosen enchantment to be locked during fusion;
- inheritance remains disallowed unless deliberately revisited.

## 12. Loot and dungeon reward philosophy

The game has no money, shop, or trading economy. Meaningful rewards are:

- experience;
- equipment;
- enchantment quality;
- unique effects;
- stat progression from qualifying dungeon completions;
- future horizontal account unlocks.

Loot should create decisions rather than only create numerical accumulation.

Ordinary room loot can be collected and safely extracted through recall. Boss completion should provide a strong reason to continue instead of recalling.

RECOMMENDED:

- normal enemies provide common and mid-value gear;
- boss encounters provide the best dungeon-specific gear;
- certain boss completions provide stat progression;
- higher difficulty improves tier, slot quality, uniqueness, or stat efficiency;
- all loot remains subject to character death until safely placed in the vault.

OPEN:

- exact drop probabilities;
- whether a boss gives guaranteed reward categories;
- whether ordinary room loot can ever exceed the dungeon's expected tier;
- whether rare uniques are dungeon-specific;
- how much loot a typical inventory fills during a run;
- whether loot tables are weighted by dungeon difficulty or room type.

## 13. Recall, completion, and death rules

### 13.1 Recall

DECIDED:

- Recall is instant.
- Recall is always available.
- Recall has no cooldown.
- Recall restores current HP and recovery capacity to full.
- Loot already picked up remains on the character after recall.
- The current dungeon instance is abandoned.
- New dungeon entry creates a new instance.

OPEN:

- whether the player can recall from the boss arena;
- whether a boss arena prevents walking out but still permits recall;
- whether any completion rewards are granted immediately on boss death or after a formal completion state;
- whether recall preserves experience gained during the current instance.

The intended design is that recall is a safe extraction option, not a failure. The player gives up the remaining dungeon and its completion rewards in exchange for safety.

### 13.2 Completion

The likely completion condition is:

- reach the boss;
- defeat the boss;
- receive the dungeon's completion rewards;
- return to town or enter a completed state.

The exact reward timing is OPEN.

### 13.3 Death

Death immediately ends the character's run and permanently deletes the character. Any loot on the ground, carried by the character, or equipped by the character is lost. Vault contents remain unaffected.

## 14. Dungeon design

### 14.1 World structure

DECIDED:

- The player begins in town.
- Town presents a list of dungeons.
- There is no overworld.
- Dungeons are named and finite.
- Dungeons are procedurally generated from their dungeon type.
- Dungeons are mostly linear initially.
- Players may backtrack through ordinary areas.
- Bosses are at the end.
- There are no fog-of-war requirements.
- There are no secrets initially.
- There are no shortcuts initially.
- There are no world events initially.
- There are no required safe areas inside dungeons.
- Players may retreat through cleared areas.
- Players may recall at any time.
- Every dungeon is available immediately.
- Dungeons have different difficulty levels.
- There is no mandatory difficulty progression.

### 14.2 Procedural generation

RECOMMENDED baseline:

~~~text
dungeon type
  -> linear room sequence
  -> authored room templates
  -> generated room ordering and orientation
  -> generated enemy composition
  -> generated loot placement
  -> fixed or selected boss arena
~~~

The system should not begin with unconstrained random terrain. Reusable authored rooms provide stronger readability and make it easier to guarantee completion.

Variation can come from:

- room selection;
- room ordering;
- mirroring and rotation;
- enemy composition;
- enemy spawn positions;
- obstacle placement;
- projectile-pattern selection;
- loot placement;
- boss phase selection.

### 14.3 Hidden procedural seeds

DECIDED:

- There are no player-facing seeds.
- Every generated dungeon should still have an internal server-generated seed.

The hidden seed is for:

- reproducing bugs;
- testing map validity;
- investigating unfair layouts;
- debugging procedural generation;
- reproducing a particular run when necessary.

It is not a player-facing game feature.

### 14.4 Initial dungeon

DECIDED:

- The initial dungeon is called Beach.
- Beach is entry-level.
- Beach provides early XP and early-game loot.
- Beach does not increase character stats.
- Detailed Beach room, enemy, boss, and loot design remains open.

## 15. Enemy and boss philosophy

The initial enemy vocabulary should be small and reusable.

RECOMMENDED baseline archetypes:

- direct chaser;
- slow aimed shooter;
- stationary radial shooter;
- fast mobile attacker;
- charger or ambusher;
- area controller for later content;
- summoner for later content.

Enemies should have distinct jobs rather than merely different health values.

### 15.1 Telegraphs and fairness

Enemies should generally:

- communicate attacks visually;
- give the player time to reposition;
- create avoidable danger;
- use terrain and group composition to create pressure;
- avoid unexplained one-shot damage;
- avoid hard crowd control initially;
- avoid attacks that are impossible to avoid through ordinary movement.

### 15.2 Bosses

Bosses should be more than high-health enemies. They should:

- have recognizable phases;
- create different projectile geometries;
- use arena space meaningfully;
- have clear transitions;
- reward learning and positioning;
- provide the strongest dungeon rewards.

Bosses should not require a specific class or party role.

## 16. Co-op direction

Co-op is deferred as a feature, but the game should not make future co-op impossible.

DECIDED:

- The eventual maximum party size is one to four players.
- The first version is single-player.
- Solo is the primary balance target.
- Every class should be able to solo.
- There are no required party roles.
- Player characters do not collide with one another.

OPEN:

- invite-only versus public parties;
- party creation and matchmaking;
- whether players can join an active dungeon;
- player scaling;
- enemy scaling;
- shared or personal loot;
- revives;
- spectator mode;
- disconnect and reconnect rules;
- co-op dungeon reward scaling;
- whether dead players receive anything if the party finishes;
- whether all players see the same loot.

Recommended future direction:

- each dungeon is a session with one to four player characters;
- solo is simply a session containing one player;
- loot is initially personal rather than contested;
- enemy difficulty scales without making low-level players irrelevant;
- no class should become mandatory for dungeon completion.

## 17. Content volume and production model

The long-term goal is a large content volume, but the first release should establish reusable structures.

Future content categories include:

- dungeon types;
- room templates;
- enemy archetypes;
- boss patterns;
- classes;
- weapons;
- armor;
- abilities;
- rings;
- enchantments;
- unique items;
- stat-reward dungeons;
- cosmetic or horizontal account unlocks.

RECOMMENDED initial content representation:

- versioned data definitions for items, enchantments, enemies, and dungeon types;
- reusable authored room files;
- behavior logic in code;
- simple hand-authored content initially;
- no custom editor initially;
- no database-driven content authoring initially.

As the content volume grows, useful tooling may include:

- dungeon validity checks;
- loot table reports;
- enchantment distribution reports;
- room previews;
- enemy spawn previews;
- boss pattern visualization;
- content schema validation;
- balance dashboards.

## 18. Technical direction, kept intentionally high-level

This section is guidance rather than a final implementation specification.

### 18.1 Client

RECOMMENDED:

- React remains the website shell;
- the game scene uses a dedicated 2D Canvas/WebGL renderer;
- Phaser or a similar 2D framework is a reasonable starting point;
- the real-time game loop should not be represented as thousands of React components;
- React can render town, inventory, vault, menus, and overlays.

### 18.2 Server authority

The existing project uses server-authoritative game state. Halcyon Rift should follow the same principle:

- the client sends input and intentions;
- the server determines movement validity, collisions, damage, cooldown/resource validity, death, loot, and rewards;
- the client may predict or visually smooth movement, but it cannot authoritatively grant items or stats.

The current board-game room architecture should not be copied blindly. A real-time action game needs a continuous simulation loop rather than turn-based room updates.

### 18.3 Persistence

Active dungeon state can remain transient while a session is active. Durable state includes:

- account identity;
- character roster;
- character progression;
- equipped gear;
- character inventory;
- vault contents;
- fusion operations;
- completed dungeon rewards.

The system should not write movement and projectile state to the database every frame.

### 18.4 Performance target

The initial technical target is one to four players in a two-dimensional dungeon with substantial projectile counts and many enemies on screen. The exact benchmark is OPEN and should be established before content volume grows.

## 19. Accessibility and usability

Initial accessibility should remain practical rather than expansive.

RECOMMENDED:

- readable projectile colors;
- strong enemy attack telegraphs;
- adjustable audio volume;
- adjustable effects volume;
- reduced screen shake;
- reduced flashing;
- scalable UI;
- clear item rarity colors plus non-color cues;
- key rebinding for keyboard controls;
- readable inventory and vault sorting;
- clear death and loss explanations.

Mobile and controller support are not initial requirements, but UI layout should not be deliberately impossible at different desktop sizes.

## 20. Economy and abuse boundaries

There is no monetary economy and no player trading.

The game still needs to protect the internal item economy from accidental duplication. Each persistent item should eventually have a stable identity, and vault/fusion operations should be atomic.

The major item sinks are:

- character death;
- fusion;
- deliberate discard;
- future optional systems.

There is no need to invent a currency simply to make the economy look more conventional.

## 21. Testing philosophy

The project does not need a massive test suite before the first playable version.

The initial minimum should cover:

- character creation;
- character death;
- loss of carried gear;
- vault preservation;
- inventory swapping;
- discard behavior;
- fusion validation;
- fusion rerolls;
- health and recovery-limit rules;
- HP and MP regeneration;
- dungeon completion rewards;
- stat progression rewards;
- XP progression;
- procedural dungeon completeness;
- basic browser rendering at several desktop sizes.

Load testing, extensive co-op testing, replay systems, and large-scale simulation tests can be added when those features are actually implemented.

The highest-priority tests are anything that could permanently destroy or duplicate player progress.

## 22. Open questions and next design decisions

These are the most important unresolved items.

### Progression

- What are the exact caps for all eight stats?
- How much does one dungeon completion increase a stat?
- Are increases whole points or fractional progress?
- Which dungeons improve which stats?
- Are stat rewards guaranteed or chance-based?
- Can players choose a stat in some dungeons?
- What is the exact XP curve from level 1 to 20?
- Is XP awarded on enemy defeat, room completion, boss completion, or some combination?
- Is XP retained after recall?

### Health and resources

- What exact amount does a recovery pickup restore?
- Does it always raise the recovery limit by the same amount?
- Are recovery pickups placed deliberately or generated?
- Are MP pickups needed?
- Does HP or MP regeneration continue at the same rate while firing?
- Can any future ability heal?

### Loot and inventory

- What exact interaction picks up an item?
- Can the player reorganize inventory during combat?
- How are full inventories communicated?
- Can ordinary items be destroyed instantly?
- How many items should a typical dungeon produce?
- What are the initial rarity and tier probabilities?
- How are enchantment slot counts distributed?
- How rare are unique items?
- Can rings with different enchantments but the same base item still not be equipped together?

### Dungeon structure

- How many room templates are needed per dungeon type?
- How is linearity guaranteed?
- How much backtracking is expected?
- What makes a dungeon mechanically distinct from another?
- Which dungeon types grant each stat?
- How much more efficient are late-game stat dungeons?
- Does the boss arena prevent walking out while still allowing instant recall?

### Co-op

- What party system should be used?
- Is loot personal?
- How does difficulty scale?
- Can players join active instances?
- What happens when one player dies?
- Does a dead player receive anything if the party completes the dungeon?
- What happens during disconnection?

## 23. Recommended design order from here

Before implementation, the most useful sequence is:

1. Finalize the stat-progression contract.
2. Finalize XP and level pacing.
3. Finalize the health/recovery/pickup rules.
4. Define the generic item and enchantment model.
5. Define the dungeon-generation grammar.
6. Define the general loot-table model.
7. Define the first vertical-slice scope.
8. Only then choose the detailed client and server implementation plan.

The first vertical slice should remain deliberately small:

- one class;
- one dungeon;
- a few enemy archetypes;
- one boss;
- basic gear tiers;
- basic enchantments;
- levels and XP;
- death;
- vault;
- fusion;
- recall;
- no co-op yet.

## 24. Handoff instructions for another AI

When working on Halcyon Rift:

1. Treat all DECIDED items in this document as constraints.
2. Do not silently turn RECOMMENDED items into requirements.
3. Ask about OPEN questions when they materially affect the design.
4. Do not add MMO, narrative, monetization, trading, currency, or party-role systems without explicit approval.
5. Preserve the central loop of choosing a dungeon, risking a character, collecting loot, and deciding when to recall.
6. Preserve the distinction between character progression and vault/account persistence.
7. Keep solo play valid for every class.
8. Treat the vault as safe and all character-carried state as vulnerable to death.
9. Keep loot collection manual.
10. Keep dungeon access open and avoid inventing mandatory progression gates.
11. Prefer readable, data-driven, reusable systems over large amounts of one-off content.
12. Before coding, summarize which decisions are being relied upon and which assumptions remain open.

## 25. Current one-paragraph summary

Halcyon Rift is a browser-based, desktop-only, top-down projectile action RPG and procedural dungeon crawler. Players maintain four class-locked characters, enter short named dungeons from a town, manually collect class-appropriate gear, gain levels, and decide whether to recall safely or continue toward a boss for better rewards. Characters permanently die with all carried gear, inventory, level, and stats, while a shared 64-slot vault protects equipment for future characters. Gear has five tiers and zero to four enchantments; duplicate matching items can be fused into rerolled versions. There are no currencies, shops, trading, narrative systems, PvP, or mandatory progression paths. Some mid- and late-game dungeon completions increase specific stats until a character's caps. The first version is single-player, but the design should remain compatible with future one-to-four-player co-op.

