"""The browser simulation's unit tests (webapp/test/unit/halcyonSim.test.mjs) play
dungeons written out from the real generator. This holds those files to it: change
the generator and this fails until the fixtures are rewritten, so the sim is never
tested against a dungeon shape the server no longer makes.

Rewrite them with:
    python -c "import json; from halcyon import dungeon as D; [open(f'webapp/test/unit/fixtures/halcyon-dungeon-{s}.json','w').write(json.dumps(D.generate('shallows', s), sort_keys=True)+'\\n') for s in ('unit-a','unit-b')]"
"""
import json
from pathlib import Path

import pytest

from halcyon import dungeon as D

FIXTURES = Path(__file__).resolve().parents[2] / "webapp" / "test" / "unit" / "fixtures"


@pytest.mark.parametrize("seed", ["unit-a", "unit-b"])
def test_the_sim_fixtures_are_what_the_generator_makes(seed):
    on_disk = json.loads((FIXTURES / f"halcyon-dungeon-{seed}.json").read_text(encoding="utf-8"))
    assert on_disk == D.generate("shallows", seed), "stale fixture: rewrite it (see this module's docstring)"


def test_the_sim_tests_level_table_is_the_servers():
    """The sim takes the level table as data (the state route ships content.LEVEL_XP);
    its unit tests carry a copy, held to the real one here."""
    import re
    from halcyon import content as C
    src = (FIXTURES.parent / "halcyonSim.test.mjs").read_text(encoding="utf-8")
    m = re.search(r"const LEVELS = \[([0-9, ]+)\];", src)
    assert m, "the sim tests no longer define LEVELS"
    assert tuple(int(x) for x in m.group(1).split(",")) == C.LEVEL_XP, "rewrite LEVELS from content.LEVEL_XP"
