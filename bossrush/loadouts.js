import { CLASS_INFO } from "./sim.js";

// Fixed kits keep the run independent of the Halcyon roster and its gear economy.
const kits = {
	ranger: ["longbow", "leather_vest", "volley_quiver"],
	paladin: ["mace", "plate_armor", "stillness_orb"],
	diviner: ["starstaff", "seer_robes", "star_tome"],
	ninja: ["shuriken", "shadow_garb", "mirror_charm"],
	simon: ["ring_staff", "ring_robe", "haste_charm"],
};

export const CHARACTERS = Object.fromEntries(Object.entries(kits).map(([id, kit]) => [
	id, { ...CLASS_INFO[id], gear: kit.map((base_id) => ({ base_id, tier: 3 })) },
]));
