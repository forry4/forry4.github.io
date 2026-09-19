from core.rooms import authorized_open_host, remove_open_seat


def _room():
    return {
        "status": "open",
        "host": "host",
        "players": {"host": "Host", "guest": "Guest"},
        "meta": {"guest": {"token": "guest-secret"}},
        "sockets": {"guest": object()},
        "boards": {"guest": "blue"},
        "game": {"players": {"guest": {"setup": True}}},
    }


def test_open_guest_can_release_only_with_their_room_token():
    room = _room()
    ok, message = remove_open_seat(room, "guest", room_token="guest-secret")
    assert (ok, message) == (True, None)
    assert "guest" not in room["players"]
    assert "guest" not in room["meta"]
    assert "guest" not in room["sockets"]
    assert "guest" not in room["boards"]
    assert "guest" not in room["game"]["players"]


def test_bad_proof_does_not_release_a_seat():
    room = _room()
    ok, message = remove_open_seat(room, "guest", room_token="wrong")
    assert not ok
    assert message == "could not verify this seat"
    assert "guest" in room["players"]


def test_host_must_cancel_and_started_rooms_cannot_release_a_seat():
    room = _room()
    ok, message = remove_open_seat(room, "host", room_token="anything")
    assert not ok
    assert message == "the host must cancel the table"

    room = _room()
    room["status"] = "playing"
    ok, message = remove_open_seat(room, "guest", room_token="guest-secret")
    assert not ok
    assert message == "the game has already started"


def test_open_host_cancel_requires_the_host_proof_too():
    room = _room()
    room["meta"]["host"] = {"token": "host-secret"}
    assert not authorized_open_host(room, "host", room_token="wrong")
    assert authorized_open_host(room, "host", room_token="host-secret")
    assert authorized_open_host(room, "host", session_uid="host")
    assert not authorized_open_host(room, "guest", room_token="guest-secret")
