//! Small fast PRNG (splitmix64) + Fisher-Yates shuffle.
//!
//! Used for `new_game` dealing and (later) MCTS determinization. It does NOT need to bit-match
//! Python's `random` — parity tests start from Python-dumped states and replay fixed action
//! sequences, so the engine's RNG is only exercised for game *generation*, where any good stream
//! is fine.

pub struct Rng {
    state: u64,
}

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng { state: seed }
    }

    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        // splitmix64
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    /// Uniform-ish index in 0..n (modulo bias negligible for our sizes <= 90).
    #[inline]
    pub fn below(&mut self, n: usize) -> usize {
        (self.next_u64() % (n as u64)) as usize
    }

    /// In-place Fisher-Yates shuffle.
    pub fn shuffle<T>(&mut self, v: &mut [T]) {
        let n = v.len();
        if n <= 1 {
            return;
        }
        for i in (1..n).rev() {
            let j = (self.next_u64() % ((i + 1) as u64)) as usize;
            v.swap(i, j);
        }
    }
}
