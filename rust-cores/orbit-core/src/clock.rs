//! A monotonic-enough millisecond clock that also exists in a browser worker.
//!
//! `std::time::Instant` panics on `wasm32-unknown-unknown` -- there is no clock
//! behind it -- and the search is budget-driven, so it reads the time on every
//! simulation. Native keeps `Instant`; wasm reads `Date.now()`, which every
//! worker has without pulling in `js-sys` or `web-sys`. `Date.now()` is coarse
//! (and deliberately coarsened further by some browsers), which is fine against
//! a budget measured in hundreds of milliseconds but is NOT a profiling clock.

#[cfg(not(target_arch = "wasm32"))]
mod platform {
    use std::time::Instant;
    pub struct Clock(Instant);
    impl Clock {
        pub fn start() -> Self {
            Self(Instant::now())
        }
        pub fn elapsed_ms(&self) -> f64 {
            self.0.elapsed().as_secs_f64() * 1000.0
        }
    }
}

#[cfg(target_arch = "wasm32")]
mod platform {
    use wasm_bindgen::prelude::*;
    #[wasm_bindgen]
    extern "C" {
        #[wasm_bindgen(js_namespace = Date, js_name = now)]
        fn date_now() -> f64;
    }
    pub struct Clock(f64);
    impl Clock {
        pub fn start() -> Self {
            Self(date_now())
        }
        /// Wall time can step backwards; a negative budget would end the search
        /// immediately, so the elapsed reading is clamped at zero.
        pub fn elapsed_ms(&self) -> f64 {
            (date_now() - self.0).max(0.0)
        }
    }
}

pub use platform::Clock;
