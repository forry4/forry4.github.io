/* THE HERO'S HITBOX (owner's pick, 2026-11-28): one circle for every attack — shots,
 * the Pyre's arms, mortars, fire pools and the Crypt Trio's marks — on the torso, so
 * the hat, the face and the weapons no longer count. It used to be the hero's whole
 * body (PLAYER_R 0.32, about 85% of the sprite), so a Null Cantor mine that only
 * crossed the top of the hat hit for 19.
 *
 * It belongs to the hero's POSITION, not to the drawing: the walk bounce and facing
 * left move only the sprite. Walls, doors, pickups and room sealing keep the body
 * (PLAYER_R). sim.js and crypt.js both read it here, so neither imports the other. */
export const HIT_R = 0.22;      // tiles
export const HIT_DY = 0.10;     // tiles below the hero's position (the sprite's centre)
