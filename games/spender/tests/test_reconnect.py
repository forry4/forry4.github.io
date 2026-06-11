import importlib


def test_reconnect_token_exposed():
    m = importlib.import_module('games.spender.main')
    # create a fake room
    room = 'TEST'
    pid = 'P1'
    # Directly manipulate ROOMS to simulate a created room
    m.ROOMS[room] = {"players": {pid: 'Player'}, "sockets": {}, "status": "waiting", "game": None, "meta": {pid: {"token": "abc123"}}}
    state = m.mk_room_state(room)
    assert 'reconnect_tokens' in state
    assert state['reconnect_tokens'][pid] == 'abc123'
